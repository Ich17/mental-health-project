import pytest

from agent import guardrails
from agent.individuel import council
from agent.memory import InMemoryMemory
from agent.individuel.scripted import ScriptedLLM, _post
from agent.individuel.tools import TOOLS
from agent.toolkit import RunContext, ToolError, run_tool


def kinds(result):
    return [(m["author"], m["kind"]) for m in result["messages"]]


def test_full_week_run_agents_talk_to_each_other():
    store = InMemoryMemory()
    r = council.run("ichane", "semaine", llm=ScriptedLLM(), store=store)
    assert r["status"] == "done"
    k = kinds(r)
    # Détection -> Évaluateur -> Analyse, l'Analyse questionne la Détection, puis passe la main à l'Action
    assert k[:6] == [("orchestrateur", "consigne"), ("detection", "signal"), ("evaluateur", "evaluation"),
                     ("analyse", "question"), ("detection", "reponse"), ("analyse", "analyse")]
    assert ("action", "proposition") in k and k[-1] == ("action", "message_final")
    assert guardrails.check_text(r["final_message"]) == []
    # Les actions validées sont en attente du clic, jamais exécutées
    actions = [a for a in store.list_actions("ichane") if not a["payload"].get("demo")]   # hors historique de démo
    assert actions and all(a["status"] == "proposed" for a in actions)
    blocks = [a for a in actions if a["kind"] == "calendar_block"]
    assert all(b["payload"]["title"] == "Occupé" and b["payload"]["visibility"] == "private" for b in blocks)
    # Toute la discussion est journalisée
    assert len(store.get_run(r["run_id"])["messages"]) == len(r["messages"])


class SloppyFirstDraft(ScriptedLLM):
    """L'Action propose d'abord un plan non conforme, puis corrige après la revue."""

    def __init__(self):
        self.drafts = 0

    def _action(self, board, instruction, kinds, res):
        if kinds == ["proposition"] or ("proposition" in kinds and "| revue]" not in board):
            self.drafts += 1
            if self.drafts == 1:
                return _post("orchestrateur", "proposition", "Plan contre le stress de la semaine.")
        return super()._action(board, instruction, kinds, res)


def test_plan_is_sent_back_for_revision():
    llm = SloppyFirstDraft()
    r = council.run("ichane", "semaine", llm=llm, store=InMemoryMemory())
    revues = [m for m in r["messages"] if m["kind"] == "revue"]
    assert revues[0]["data"]["approved"] is False
    assert revues[-1]["data"]["approved"] is True
    assert r["status"] == "done"


class AlwaysBadFinal(ScriptedLLM):
    def _action(self, board, instruction, kinds, res):
        if kinds == ["message_final"]:
            return _post("tous", "message_final", "Ton humeur est en baisse, gère ton stress.")
        return super()._action(board, instruction, kinds, res)


def test_final_message_falls_back_to_safe_text():
    r = council.run("ichane", "semaine", llm=AlwaysBadFinal(), store=InMemoryMemory())
    assert r["status"] == "done"
    assert r["messages"][-1]["author"] == "orchestrateur"
    assert guardrails.check_text(r["final_message"]) == []


def test_agents_only_get_their_own_tools():
    ctx = RunContext(store=InMemoryMemory(), user_id="ichane")
    with pytest.raises(ToolError):
        run_tool(ctx, TOOLS, "get_daily_metrics", {}, allowed=["get_free_slots"])


def test_blocks_must_fit_free_slots():
    ctx = RunContext(store=InMemoryMemory(), user_id="ichane")
    with pytest.raises(ToolError):
        run_tool(ctx, TOOLS, "propose_block", {"date": "2026-10-26", "start": "10:00", "end": "11:00",
                                        "purpose": "focus"}, allowed=["propose_block"])
    out = run_tool(ctx, TOOLS, "propose_block", {"date": "2026-10-26", "start": "12:30", "end": "13:30",
                                          "purpose": "dejeuner"}, allowed=["propose_block"])
    assert out["payload"]["title"] == "Occupé"
    assert len(ctx.draft_actions) == 1


def test_chat_mode():
    r = council.run("ichane", "chat", "Pourquoi je suis à plat le lundi ?", llm=ScriptedLLM(),
                    store=InMemoryMemory())
    assert r["status"] == "done" and r["final_message"]


def test_claude_client_parses_tool_use(monkeypatch):
    """Vérifie le branchement au SDK sans appel réseau."""
    from types import SimpleNamespace as NS

    import anthropic

    from agent.llm import ClaudeLLM

    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            return NS(stop_reason="tool_use", content=[
                NS(type="text", text="Je regarde."),
                NS(type="tool_use", id="t1", name="get_drivers", input={})])

    monkeypatch.setattr(anthropic, "Anthropic", lambda: NS(messages=FakeMessages()))
    reply = ClaudeLLM(model="m").complete(agent="analyse", system="s", messages=[{"role": "user", "content": "x"}],
                                          tools=[], tool_choice={"type": "any"})
    assert reply.tool_calls[0]["name"] == "get_drivers" and reply.text == "Je regarde."
    assert sent["tool_choice"] == {"type": "any"} and sent["model"] == "m"
