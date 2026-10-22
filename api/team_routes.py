"""Routes de la vue RH : revue d'entreprise par les agents d'équipe et cycle de vie des règles.

Le front lance une revue (POST), puis interroge GET /api/agent/runs/{id} toutes les
secondes pour afficher les messages au fur et à mesure que les agents se parlent.
"""
import threading
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import contracts
from agent.memory import get_store
from agent.team import council as team_council

router = APIRouter(prefix="/api")


def _in_background(run_fn) -> dict:
    """Lance un run dans un thread et renvoie son id dès qu'il est créé."""
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
    started.wait(timeout=30)
    if "run_id" not in box:
        raise HTTPException(500, "le run n'a pas démarré")
    return {"run_id": box["run_id"], "status": "running"}


class TeamRunRequest(BaseModel):
    wait: bool = False  # True : attend la fin (tests, CLI) ; False : renvoie l'id tout de suite


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


@router.get("/team/overview")
def team_overview():
    """Équipes affichables (n ≥ 8), de la plus en dérive à la plus stable. Aucune donnée individuelle."""
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
    """La RH applique une règle suggérée : la Mesure en évaluera l'effet aux revues suivantes."""
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
