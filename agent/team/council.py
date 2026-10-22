"""Orchestrateur côté équipe : l'Observateur et le Conseiller délibèrent,
le code relit, la RH reçoit une règle suggérée.

    Observateur --signal--> Conseiller --proposition--> revue (code) --> message_final
         ^                     |
         +------question-------+

Point de départ volontairement simple, à enrichir (ex. un agent qui mesure
l'effet des règles appliquées). La mécanique (Agent, Board, mémoire, revue)
est la même que côté individuel.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import contracts
from agent import guardrails
from agent.agents import Agent
from agent.board import Board, Message
from agent.llm import LLM, default_llm
from agent.memory import get_store
from agent.team.scripted import ScriptedTeamLLM
from agent.team.tools import AGENT_TOOLS, TOOLS
from agent.toolkit import RunContext

AGENTS = ["observateur", "conseiller"]
RECIPIENTS = AGENTS + ["orchestrateur"]
PROMPTS = Path(__file__).with_name("prompts")
AGENT_KINDS = {
    "observateur": ["signal", "reponse"],
    "conseiller": ["proposition", "message_final", "question"],
}
MAX_TURNS = 8
MAX_REVISIONS = 2


def run(team_id: str, *, llm: LLM | None = None, store=None,
        on_message: Callable[[dict], None] | None = None,
        on_start: Callable[[int], None] | None = None) -> dict:
    llm = llm or default_llm(ScriptedTeamLLM)
    store = store or get_store()
    store.seed_team(team_id)
    ctx = RunContext(store=store, team_id=team_id)
    board = Board(run_kind="equipe", subject=team_id)
    run_id = store.create_run("equipe", team_id)
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

    # Groupe trop petit : on ne lance même pas les agents (CLAUDE.md §3).
    if contracts.team_trends(team_id).get("insufficient_group"):
        final = orchestrator("tous", "message_final",
                             "Équipe trop petite pour une analyse anonyme : les tendances sont "
                             "regroupées au niveau du département.")
        store.finish_run(run_id, "done", final.content)
        return {"run_id": run_id, "status": "done", "final_message": final.content,
                "rules": [], "messages": board.to_dict()["messages"], "tool_trace": trace}

    orchestrator("observateur", "consigne", "Revue hebdomadaire de l'équipe : tendance, cause, règle à suggérer.")
    speaker, kinds, instruction = "observateur", ["signal"], "Lis les tendances et poste ton `signal` au conseiller."
    asked, revisions, final, rules = False, 0, None, []

    try:
        for _ in range(MAX_TURNS):
            msg = post(agents[speaker].take_turn(llm, board, ctx, instruction, RECIPIENTS, kinds, trace))

            if msg.kind == "question":
                asked = True
                speaker, kinds = "observateur", ["reponse"]
                instruction = "Le conseiller te pose une question (dernier message). Réponds par une `reponse`."
            elif msg.kind in ("signal", "reponse"):
                speaker = "conseiller"
                kinds = ["proposition"] + ([] if asked else ["question"])
                instruction = "Lis le signal, consulte les règles passées, puis poste ta `proposition`."
            elif msg.kind == "proposition":
                issues = guardrails.check_hr_text(
                    msg.content + " " + " ".join(a["payload"]["rule_text"] for a in ctx.draft_actions))
                if issues and revisions < MAX_REVISIONS:
                    revisions += 1
                    ctx.draft_actions.clear()
                    orchestrator("conseiller", "revue", "Proposition refusée :\n- " + "\n- ".join(issues),
                                 {"approved": False, "issues": issues})
                    kinds, instruction = ["proposition"], "Refais la proposition en corrigeant chaque point."
                    continue
                for a in ctx.draft_actions[:1]:  # une règle maximum
                    if not guardrails.check_hr_text(a["payload"]["rule_text"]):
                        a["id"] = store.suggest_team_rule(team_id, a["payload"]["rule_text"])
                        rules.append(a)
                ctx.draft_actions.clear()
                orchestrator("conseiller", "revue", f"Validé : {len(rules)} règle(s) suggérée(s) à la RH.",
                             {"approved": True, "rule_ids": [r["id"] for r in rules]})
                kinds, instruction = ["message_final"], "Poste le `message_final` pour la RH."
            elif msg.kind == "message_final":
                if guardrails.check_hr_text(msg.content):
                    msg = orchestrator("tous", "message_final",
                                       "Tendance d'équipe disponible ; une règle a été suggérée. "
                                       "Détails dans l'onglet Règles.")
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
