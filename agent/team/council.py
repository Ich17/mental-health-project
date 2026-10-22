"""Orchestrateur côté entreprise : Observateur, Mesure et Conseiller délibèrent,
le code relit, la RH reçoit au plus une règle suggérée.

    Observateur --signal--> Mesure --mesure--> Conseiller --proposition--> revue (code) --> message_final
         ^                    ^                    |
         +----question--------+------question------+

Cycle de vie d'une règle (« s'améliore avec le temps ») :
    suggested  (Conseiller, après revue)
 -> applied    (clic RH : POST /api/team/rules/{id}/apply)
 -> measured   (Mesure, au run suivant, une fois 2 semaines de recul)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent import guardrails
from agent.agents import Agent
from agent.board import Board, Message
from agent.llm import LLM, default_llm
from agent.memory import get_store
from agent.team.scripted import ScriptedTeamLLM
from agent.team.tools import AGENT_TOOLS, TOOLS
from agent.toolkit import RunContext
from data import cohort

AGENTS = ["observateur", "mesure", "conseiller"]
RECIPIENTS = AGENTS + ["orchestrateur"]
PROMPTS = Path(__file__).with_name("prompts")
AGENT_KINDS = {
    "observateur": ["signal", "reponse"],
    "mesure": ["mesure", "reponse"],
    "conseiller": ["proposition", "message_final", "question"],
}
MAX_TURNS = 10
MAX_REVISIONS = 2

INSTRUCTIONS = {
    "observateur": "Fais le tour de l'entreprise et poste ton `signal` à la mesure.",
    "mesure": "Mesure les règles appliquées, enregistre leur effet, puis poste ta `mesure` au conseiller.",
    "conseiller": "Lis le signal et la mesure, puis poste ta `proposition` à l'orchestrateur.",
}


def demo_rules() -> list[dict]:
    """Règle déjà appliquée il y a 4 semaines dans la cohorte simulée : la Mesure en calcule l'effet."""
    return [{"team_id": cohort.unit_of(cohort.SEED_RULE["team_id"]),
             "rule_text": cohort.SEED_RULE["rule_text"] + " (équipe Coverage)",
             "start_date": cohort.rule_start_date(), "measured_effect": None, "status": "applied"}]


def run(*, llm: LLM | None = None, store=None,
        on_message: Callable[[dict], None] | None = None,
        on_start: Callable[[int], None] | None = None) -> dict:
    llm = llm or default_llm(ScriptedTeamLLM)
    store = store or get_store()
    store.seed_team_rules(demo_rules())
    ctx = RunContext(store=store)
    board = Board(run_kind="equipe", subject="entreprise")
    run_id = store.create_run("equipe", "entreprise")
    if on_start:
        on_start(run_id)
    agents = {n: Agent(n, PROMPTS, TOOLS, AGENT_TOOLS[n], AGENT_KINDS[n]) for n in AGENTS}
    trace: list[dict] = []

    def post(msg: Message) -> Message:
        board.post(msg)
        store.append_message(run_id, msg.__dict__)
        if on_message:
            on_message(msg.__dict__)
        return msg

    def orchestrator(to, kind, content, data=None):
        return post(Message(author="orchestrateur", to=to, kind=kind, content=content, data=data or {}))

    orchestrator("observateur", "consigne",
                 "Revue hebdomadaire de l'entreprise : quelle unité dérive, quelles règles ont marché, "
                 "quelle règle suggérer à la RH.")
    speaker, kinds, instruction = "observateur", None, INSTRUCTIONS["observateur"]
    asked, waiting, revisions, final, rules = False, None, 0, None, []

    try:
        for _ in range(MAX_TURNS):
            allowed = [k for k in (kinds or AGENT_KINDS[speaker]) if k != "question" or not asked]
            msg = post(agents[speaker].take_turn(llm, board, ctx, instruction, RECIPIENTS, allowed, trace))

            if msg.kind == "question":
                asked, waiting = True, speaker
                speaker, kinds = msg.to, ["reponse"]
                instruction = f"{msg.author} te pose une question (dernier message). Réponds par une `reponse`."
            elif msg.kind == "reponse":
                speaker, kinds = waiting, ["proposition"]
                instruction = "La réponse est sur le tableau. " + INSTRUCTIONS[speaker]
            elif msg.kind == "signal":
                speaker, kinds, instruction = "mesure", None, INSTRUCTIONS["mesure"]
            elif msg.kind == "mesure":
                speaker, kinds, instruction = "conseiller", None, INSTRUCTIONS["conseiller"]
            elif msg.kind == "proposition":
                texts = [msg.content] + [a["payload"]["rule_text"] for a in ctx.draft_actions]
                issues = guardrails.check_hr_text(" ".join(texts))
                if issues and revisions < MAX_REVISIONS:
                    revisions += 1
                    ctx.draft_actions.clear()
                    orchestrator("conseiller", "revue", "Proposition refusée :\n- " + "\n- ".join(issues),
                                 {"approved": False, "issues": issues})
                    kinds, instruction = ["proposition"], "Refais la proposition en corrigeant chaque point."
                    continue
                active = {(r["team_id"], r["rule_text"]) for r in store.team_rules()
                          if r["status"] in ("suggested", "applied")}
                for a in ctx.draft_actions:
                    p = a["payload"]
                    if guardrails.check_hr_text(p["rule_text"]) or (p["team_id"], p["rule_text"]) in active:
                        continue
                    a["id"] = store.suggest_team_rule(p["team_id"], p["rule_text"])
                    rules.append(a)
                ctx.draft_actions.clear()
                orchestrator("conseiller", "revue", f"Validé : {len(rules)} règle(s) suggérée(s) à la RH.",
                             {"approved": True, "rule_ids": [r["id"] for r in rules]})
                kinds, instruction = ["message_final"], "Poste le `message_final` pour la RH."
            elif msg.kind == "message_final":
                if guardrails.check_hr_text(msg.content):
                    msg = orchestrator("tous", "message_final",
                                       "Revue d'équipe terminée : une unité est en dérive et une règle a été "
                                       "suggérée. Détails dans l'onglet Règles.")
                final = msg
                break
        else:
            raise RuntimeError(f"pas de message final après {MAX_TURNS} tours")
        store.finish_run(run_id, "done", final.content)
        status = "done"
    except Exception as e:
        store.finish_run(run_id, "error", f"{type(e).__name__}: {e}")
        status = "error"
        if not on_message:
            raise

    return {"run_id": run_id, "status": status, "final_message": final.content if final else None,
            "rules": rules, "messages": board.to_dict()["messages"], "tool_trace": trace}
