"""Routes des agents : lancer une délibération, la suivre en direct, accepter une action.

Le front lance un run (POST), puis interroge GET /api/agent/runs/{id} toutes les
secondes pour afficher les messages au fur et à mesure que les agents se parlent.
"""
import os
import threading
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import contracts
from agent.individuel import council
from agent.team import council as team_council
from agent.memory import get_store

router = APIRouter(prefix="/api")
USER_ID = os.getenv("USER_ID", "ichane")


class RunRequest(BaseModel):
    kind: Literal["semaine", "jour", "chat"] = "semaine"
    question: str | None = None
    wait: bool = False  # True : attend la fin du run (tests, CLI) ; False : renvoie l'id tout de suite


def _in_background(run_fn) -> dict:
    """Lance un run dans un thread et renvoie son id dès qu'il est créé.
    Le front suit ensuite la discussion via GET /api/agent/runs/{id}."""
    started = threading.Event()
    box: dict = {}

    def on_start(run_id: int):
        box["run_id"] = run_id
        started.set()

    def target():
        try:
            run_fn(on_start=on_start, on_message=lambda m: None)
        finally:
            started.set()

    threading.Thread(target=target, daemon=True).start()
    started.wait(timeout=10)
    if "run_id" not in box:
        raise HTTPException(500, "le run n'a pas démarré")
    return {"run_id": box["run_id"], "status": "running"}


@router.post("/agent/runs")
def start_run(req: RunRequest):
    if req.kind == "chat" and not req.question:
        raise HTTPException(422, "question obligatoire en mode chat")
    if req.wait:
        return council.run(USER_ID, req.kind, req.question)
    return _in_background(lambda **kw: council.run(USER_ID, req.kind, req.question, **kw))


class TeamRunRequest(BaseModel):
    wait: bool = False


@router.post("/agent/team-runs")
def start_team_run(req: TeamRunRequest = TeamRunRequest()):
    """Revue d'entreprise par les agents d'équipe (agrégats uniquement)."""
    if req.wait:
        return team_council.run()
    return _in_background(team_council.run)


@router.get("/agent/runs")
def list_runs(limit: int = 20):
    return get_store().list_runs(limit)


@router.get("/agent/runs/{run_id}")
def get_run(run_id: int):
    run = get_store().get_run(run_id)
    if run is None:
        raise HTTPException(404, "run introuvable")
    return run


@router.get("/actions")
def list_actions(status: str | None = "proposed"):
    return get_store().list_actions(USER_ID, status)


@router.post("/actions/{action_id}/accept")
def accept_action(action_id: int):
    """Seul endroit où une action est exécutée : après le clic de la personne."""
    store = get_store()
    action = store.get_action(action_id)
    if action is None or action["user_id"] != USER_ID:
        raise HTTPException(404, "action introuvable")
    if action["status"] != "proposed":
        raise HTTPException(409, f"action déjà {action['status']}")

    p, result = action["payload"], {}
    if action["kind"] == "calendar_block":
        result = contracts.create_calendar_block(USER_ID, p["start"], p["end"])
    elif action["kind"] == "experiment":
        result = {"experiment_id": store.start_experiment(
            USER_ID, p["rule_text"], p["start_date"], p["end_date"], p.get("baseline_recovery"))}
    elif action["kind"] == "draft_message":
        result = {"text": p["text"], "note": "à envoyer toi-même si tu le souhaites"}
    store.set_action_status(action_id, "done" if action["kind"] != "draft_message" else "accepted")
    return {"action_id": action_id, "result": result}


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: int):
    store = get_store()
    action = store.get_action(action_id)
    if action is None or action["user_id"] != USER_ID:
        raise HTTPException(404, "action introuvable")
    store.set_action_status(action_id, "rejected")
    return {"action_id": action_id, "status": "rejected"}


# --- Vue RH : agrégats et règles d'équipe ------------------------------------

@router.get("/team/overview")
def team_overview():
    """Unités affichables (n ≥ 8, sinon département en bloc). Aucune donnée individuelle."""
    return contracts.company_overview()


@router.get("/team/rules")
def team_rules():
    return get_store().team_rules()


def _rule_or_404(rule_id: int) -> dict:
    rule = get_store().get_team_rule(rule_id)
    if rule is None:
        raise HTTPException(404, "règle introuvable")
    return rule


@router.post("/team/rules/{rule_id}/apply")
def apply_rule(rule_id: int):
    """La RH applique une règle suggérée : la Mesure en évaluera l'effet aux runs suivants."""
    rule = _rule_or_404(rule_id)
    if rule["status"] != "suggested":
        raise HTTPException(409, f"règle déjà {rule['status']}")
    get_store().update_team_rule(rule_id, status="applied", start_date=date.today().isoformat())
    return _rule_or_404(rule_id)


@router.post("/team/rules/{rule_id}/dismiss")
def dismiss_rule(rule_id: int):
    rule = _rule_or_404(rule_id)
    if rule["status"] != "suggested":
        raise HTTPException(409, f"règle déjà {rule['status']}")
    get_store().update_team_rule(rule_id, status="dismissed")
    return _rule_or_404(rule_id)
