"""L'orchestrateur : fait circuler la parole entre Détection, Analyse et Action.

Déroulé par défaut (run « semaine ») :

    Détection --signal--> Analyse --analyse--> Action --proposition--> revue (code)
         ^                  |  ^                 |                         |
         +----question------+  +----question-----+   <--- à corriger ------+
                                                         validé -> message_final

- Une question passe la parole au destinataire, sa réponse la rend à l'auteur.
  Une question maximum par agent et par run.
- La revue du plan est faite par du code (guardrails.py), pas par un LLM :
  vocabulaire, titre « Occupé », orientation si plusieurs jours rouges.
  2 révisions maximum, puis les actions non conformes sont écartées.
- Les actions validées sont enregistrées en `proposed`. Rien n'est exécuté
  avant le clic de l'utilisateur (route API /api/actions/{id}/accept).
"""
from __future__ import annotations

from typing import Callable

import contracts
from agent import guardrails
from pathlib import Path

from agent.agents import Agent
from agent.board import Board, Message
from agent.individuel.scripted import ScriptedLLM
from agent.individuel.tools import AGENT_TOOLS, TOOLS
from agent.llm import LLM, default_llm
from agent.memory import get_store
from agent.toolkit import RunContext

AGENTS = ["detection", "analyse", "action"]
PROMPTS = Path(__file__).with_name("prompts")
# Types de messages que chaque agent a le droit de poster.
AGENT_KINDS = {
    "detection": ["signal", "reponse"],
    "analyse": ["analyse", "question", "reponse"],
    "action": ["proposition", "message_final", "question"],
}
RECIPIENTS = AGENTS + ["orchestrateur"]
MAX_TURNS = 12
MAX_REVISIONS = 2

BRIEFS = {
    "semaine": "Préparer la semaine à venir : repérer les dérives, expliquer les causes, "
               "proposer un plan qui protège les jours à risque.",
    "jour": "Check du jour : la journée de demain est-elle à risque, et faut-il protéger un créneau ?",
    "chat": "La personne pose une question (ci-dessous). L'agent Action répond, en demandant "
            "si besoin une précision à la Détection ou à l'Analyse.",
}

INSTRUCTIONS = {
    "detection": "Analyse les données et poste ton `signal` à l'analyse.",
    "analyse": "Lis le signal, consulte les causes et la mémoire, puis poste ton `analyse` à l'action.",
    "action": "Construis le plan avec tes outils puis poste ta `proposition` à l'orchestrateur.",
}


def run(user_id: str, kind: str = "semaine", question: str | None = None, *,
        llm: LLM | None = None, store=None,
        on_message: Callable[[dict], None] | None = None,
        on_start: Callable[[int], None] | None = None) -> dict:
    llm = llm or default_llm(ScriptedLLM)
    store = store or get_store()
    store.seed(user_id)
    ctx = RunContext(store=store, user_id=user_id)
    board = Board(run_kind=kind, subject=user_id)
    run_id = store.create_run(kind, user_id)
    if on_start:
        on_start(run_id)
    agents = {name: Agent(name, PROMPTS, TOOLS, AGENT_TOOLS[name], AGENT_KINDS[name]) for name in AGENTS}
    trace: list[dict] = []
    red_days = sum(d["risk"] == "rouge" for d in contracts.forecast_week(user_id))

    def post(msg: Message) -> Message:
        board.post(msg)
        store.append_message(run_id, msg.__dict__)
        if on_message:
            on_message(msg.__dict__)
        return msg

    def orchestrator(to: str, kind_: str, content: str, data: dict | None = None):
        return post(Message(author="orchestrateur", to=to, kind=kind_, content=content, data=data or {}))

    # --- état de la délibération
    asked: set[str] = set()          # agents ayant déjà posé leur question
    waiting: list[str] = []          # pile des agents qui attendent une réponse
    revisions = 0
    final_rewrite_used = False
    approved_actions: list[dict] = []
    final: Message | None = None

    start = "action" if kind == "chat" else "detection"
    orchestrator(start, "consigne", BRIEFS[kind] + (f"\n\nQuestion de la personne : {question}" if question else ""))
    if question:
        post(Message(author="personne", to="action", kind="question", content=question))

    speaker, instruction, kinds = start, (
        "Réponds à la personne. Tu peux d'abord poser une question à la détection ou à l'analyse, "
        "ou proposer des actions (puis `proposition`)." if kind == "chat" else INSTRUCTIONS[start]), None
    if kind == "chat":
        kinds = ["message_final", "question", "proposition"]

    try:
        for _ in range(MAX_TURNS):
            allowed = [k for k in (kinds or _default_kinds(speaker)) if k != "question" or speaker not in asked]
            msg = post(agents[speaker].take_turn(llm, board, ctx, instruction, RECIPIENTS, allowed, trace))

            if msg.kind == "question":
                asked.add(speaker)
                waiting.append(speaker)
                speaker, kinds = msg.to, ["reponse"]
                instruction = f"L'agent {msg.author} te pose une question (dernier message). Réponds-lui par une `reponse`."
                continue

            if msg.kind == "reponse":
                speaker, kinds = waiting.pop(), None
                instruction = "La réponse à ta question est sur le tableau. Termine ton travail. " + \
                              ("" if kind == "chat" else INSTRUCTIONS[speaker])
                if kind == "chat" and speaker == "action":
                    kinds = ["message_final", "proposition"]
                continue

            if msg.kind == "signal":
                speaker, kinds, instruction = "analyse", None, INSTRUCTIONS["analyse"]
                continue

            if msg.kind == "analyse":
                speaker, kinds, instruction = "action", None, INSTRUCTIONS["action"]
                continue

            if msg.kind == "proposition":
                issues = guardrails.check_plan(ctx.draft_actions, msg.content)
                if issues and revisions < MAX_REVISIONS:
                    revisions += 1
                    orchestrator("action", "revue", "Plan refusé. À corriger :\n- " + "\n- ".join(issues),
                                 {"approved": False, "issues": issues})
                    ctx.draft_actions.clear()
                    speaker, kinds = "action", ["proposition"]
                    instruction = "Le plan a été refusé (voir la revue). Refais-le en corrigeant chaque point."
                    continue
                kept = [a for a in ctx.draft_actions if not guardrails.check_plan([a])]
                dropped = len(ctx.draft_actions) - len(kept)
                pending = store.list_actions(user_id, "proposed")
                for a in kept:  # une action déjà proposée et identique n'est pas dupliquée
                    same = next((p for p in pending if p["kind"] == a["kind"] and p["payload"] == a["payload"]), None)
                    a["id"] = same["id"] if same else store.add_action(user_id, a["kind"], a["payload"])
                approved_actions = kept
                ctx.draft_actions.clear()
                orchestrator("action", "revue",
                             f"Plan validé : {len(kept)} action(s) proposée(s) à la personne"
                             + (f", {dropped} écartée(s) car non conformes." if dropped else "."),
                             {"approved": True, "action_ids": [a["id"] for a in kept]})
                speaker, kinds = "action", ["message_final"]
                instruction = ("Le plan est validé. Poste le `message_final` adressé à tous, "
                               "le texte que lira la personne.")
                continue

            if msg.kind == "message_final":
                issues = guardrails.check_text(msg.content) + guardrails.check_orientation(red_days, msg.content)
                if issues and not final_rewrite_used:
                    final_rewrite_used = True
                    orchestrator("action", "revue", "Message refusé. À corriger :\n- " + "\n- ".join(issues),
                                 {"approved": False, "issues": issues})
                    speaker, kinds = "action", ["message_final"]
                    instruction = "Réécris le `message_final` en corrigeant chaque point de la revue."
                    continue
                if issues:  # toujours non conforme : message de repli écrit par le code
                    msg = orchestrator("tous", "message_final", _fallback_message(red_days, approved_actions))
                final = msg
                break
        else:
            raise RuntimeError(f"pas de message final après {MAX_TURNS} tours")

        store.finish_run(run_id, "done", final.content)
        status = "done"
    except Exception as e:  # le run est journalisé même en cas d'échec
        store.finish_run(run_id, "error", f"{type(e).__name__}: {e}")
        status = "error"
        if not on_message:
            raise

    return {"run_id": run_id, "status": status, "kind": kind,
            "final_message": final.content if final else None,
            "actions": approved_actions, "messages": board.to_dict()["messages"], "tool_trace": trace}


def _default_kinds(agent: str) -> list[str]:
    return {"detection": ["signal"], "analyse": ["analyse", "question"],
            "action": ["proposition", "question"]}[agent]


def _fallback_message(red_days: int, actions: list[dict]) -> str:
    parts = [f"Ta semaine compte {red_days} jour(s) où ta récupération risque d'être basse."]
    if actions:
        parts.append(f"J'ai préparé {len(actions)} proposition(s) que tu peux accepter en un clic.")
    if red_days >= guardrails.RED_DAYS_FOR_ORIENTATION:
        parts.append("Si ça dure, le médecin du travail ou un psy pris en charge par ta mutuelle "
                     "peuvent t'aider à faire le point.")
    return " ".join(parts)
