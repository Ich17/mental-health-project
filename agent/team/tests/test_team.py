import pytest
from fastapi.testclient import TestClient

import agent.memory as memory
from agent import guardrails
from agent.scripted_utils import _post
from agent.memory import InMemoryMemory
from agent.team import council
from agent.team.scripted import ScriptedTeamLLM
from agent.team.tools import TOOLS
from agent.toolkit import RunContext, ToolError, run_tool
from data import team_view


def test_company_review_three_agents_talk():
    store = InMemoryMemory()
    r = council.run(llm=ScriptedTeamLLM(), store=store)
    assert r["status"] == "done"
    flow = [(m["author"], m["kind"]) for m in r["messages"]]
    assert flow[1:4] == [("observateur", "signal"), ("mesure", "mesure"), ("conseiller", "question")]
    assert ("observateur", "reponse") in flow and flow[-1] == ("conseiller", "message_final")
    # La règle vise l'unité qui dérive le plus
    assert [x["payload"]["team_id"] for x in r["rules"]] == ["ma"]
    # La Mesure a enregistré l'effet de la règle déjà appliquée : la boucle d'apprentissage
    seeded = store.team_rules()[0]
    assert seeded["status"] == "measured" and "récupération" in seeded["measured_effect"]
    assert guardrails.check_hr_text(r["final_message"]) == []


def test_no_duplicate_suggestion_on_second_run():
    store = InMemoryMemory()
    council.run(llm=ScriptedTeamLLM(), store=store)
    r2 = council.run(llm=ScriptedTeamLLM(), store=store)
    assert r2["rules"] == []
    assert sum(x["status"] == "suggested" for x in store.team_rules()) == 1


class LeakyFirstDraft(ScriptedTeamLLM):
    def __init__(self):
        self.n = 0

    def _conseiller(self, board, kinds, res):
        if kinds == ["proposition"] or ("proposition" in kinds and "| revue]" not in board and "| reponse]" in board):
            self.n += 1
            if self.n == 1:
                return _post("orchestrateur", "proposition", "3 personnes de M&A sont épuisées.")
        return super()._conseiller(board, kinds, res)


def test_small_counts_are_sent_back():
    r = council.run(llm=LeakyFirstDraft(), store=InMemoryMemory())
    revues = [m for m in r["messages"] if m["kind"] == "revue"]
    assert revues[0]["data"]["approved"] is False and revues[-1]["data"]["approved"] is True


def test_small_team_is_never_exposed():
    assert "restru" not in team_view.reportable_units()          # 4 personnes : masquée
    assert team_view.team_trends("restru") == {"insufficient_group": True}
    for u in team_view.company_overview():
        assert set(u) == {"unit_id", "team", "n_bucket", "share_in_debt", "top_cause",
                          "cause_change", "recovery_change"}   # aucune donnée individuelle
        assert u["n_bucket"] in {"8-12", "12-20", "20+"}


def test_tools_refuse_non_reportable_units_and_unapplied_rules():
    store = InMemoryMemory()
    ctx = RunContext(store=store)
    with pytest.raises(ToolError):
        run_tool(ctx, TOOLS, "suggest_rule", {"unit_id": "restru", "rule_text": "x", "rationale": "y"},
                 ["suggest_rule"])
    rid = store.suggest_team_rule("ma", "Pas de réunion après 18h")
    with pytest.raises(ToolError):
        run_tool(ctx, TOOLS, "measure_rule_effect", {"rule_id": rid}, ["measure_rule_effect"])
    with pytest.raises(ToolError):
        run_tool(ctx, TOOLS, "record_rule_effect", {"rule_id": rid, "measured_effect": "2 salariés vont mieux"},
                 ["record_rule_effect"])


def test_rule_lifecycle_through_api(monkeypatch):
    from api.main import app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENT_MODE", "scripted")
    monkeypatch.setattr(memory, "_store", None)
    c = TestClient(app)

    assert c.get("/api/team/overview").json()[0]["unit_id"] == "ma"
    r = c.post("/api/agent/team-runs", json={"wait": True}).json()
    assert r["status"] == "done"
    rule_id = r["rules"][0]["id"]

    applied = c.post(f"/api/team/rules/{rule_id}/apply").json()
    assert applied["status"] == "applied" and applied["start_date"]
    assert c.post(f"/api/team/rules/{rule_id}/apply").status_code == 409

    # Run suivant : la nouvelle règle est trop récente pour être mesurée, elle reste « applied »
    c.post("/api/agent/team-runs", json={"wait": True})
    rule = next(x for x in c.get("/api/team/rules").json() if x["id"] == rule_id)
    assert rule["status"] == "applied"

    bg = c.post("/api/agent/team-runs", json={}).json()
    assert bg["status"] == "running"
