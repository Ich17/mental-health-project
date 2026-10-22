"""Outils des agents d'équipe et leurs droits.

Confidentialité appliquée par le code (CLAUDE.md §3) :
- aucun outil n'expose de donnée individuelle : tout passe par les agrégats
  de contracts.py (seuil n ≥ 8 appliqué dans la couche data) ;
- une règle ne peut viser qu'une équipe affichable (au moins 8 personnes) ;
- suggest_rule remplit un brouillon, enregistré seulement après la revue du code ;
  l'application d'une règle est un clic RH (route API), jamais un agent.
"""
from __future__ import annotations

import contracts
from agent import guardrails
from agent.toolkit import RunContext, Tool, ToolError, obj


def _units() -> set[str]:
    return {u["unit_id"] for u in contracts.company_overview()}


# --- Observateur -------------------------------------------------------------

def company_overview(ctx: RunContext):
    return contracts.company_overview()


def team_trends(ctx: RunContext, unit_id: str):
    return contracts.team_trends(unit_id)


# --- Mesure --------------------------------------------------------------------

def get_team_rules(ctx: RunContext):
    return ctx.store.team_rules()


def measure_rule_effect(ctx: RunContext, rule_id: int):
    rule = ctx.store.get_team_rule(int(rule_id))
    if rule is None:
        raise ToolError(f"règle {rule_id} introuvable")
    if rule["status"] not in ("applied", "measured") or not rule.get("start_date"):
        raise ToolError("seule une règle appliquée peut être mesurée")
    return {"rule_id": rule["id"], "rule_text": rule["rule_text"],
            **contracts.measure_rule_effect(rule["team_id"], str(rule["start_date"]))}


def record_rule_effect(ctx: RunContext, rule_id: int, measured_effect: str):
    issues = guardrails.check_hr_text(measured_effect)
    if issues:
        raise ToolError("texte refusé : " + "; ".join(issues))
    ctx.store.update_team_rule(int(rule_id), measured_effect=measured_effect, status="measured")
    return {"ok": True}


# --- Conseiller --------------------------------------------------------------

def suggest_rule(ctx: RunContext, unit_id: str, rule_text: str, rationale: str):
    if unit_id not in _units():
        raise ToolError(f"unité « {unit_id} » non affichable. Unités possibles : {sorted(_units())}")
    if ctx.draft_actions:
        raise ToolError("une seule règle par run")
    ctx.draft_actions.append({"kind": "team_rule", "payload": {
        "team_id": unit_id, "rule_text": rule_text, "rationale": rationale}})
    return {"note": "brouillon : relu par le code puis proposé à la RH"}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("company_overview", "Toutes les équipes affichables (au moins 8 personnes), de la "
         "plus en dérive à la plus stable : récupération, part en dette, cause principale.",
         obj(), company_overview),
    Tool("team_trends", "Détail d'une unité : récupération moyenne semaine par semaine, cause principale.",
         obj({"unit_id": {"type": "string"}}, ["unit_id"]), team_trends),
    Tool("get_team_rules", "Toutes les règles d'équipe : suggérées, appliquées, mesurées, avec leur effet.",
         obj(), get_team_rules),
    Tool("measure_rule_effect", "Mesure l'effet d'une règle appliquée : récupération moyenne avant / depuis.",
         obj({"rule_id": {"type": "integer"}}, ["rule_id"]), measure_rule_effect),
    Tool("record_rule_effect", "Enregistre en mémoire l'effet mesuré d'une règle (texte court, sans effectif).",
         obj({"rule_id": {"type": "integer"}, "measured_effect": {"type": "string"}},
             ["rule_id", "measured_effect"]), record_rule_effect),
    Tool("suggest_rule", "Ajoute au plan une règle d'équipe à suggérer à la RH (une par run).",
         obj({"unit_id": {"type": "string"}, "rule_text": {"type": "string"}, "rationale": {"type": "string"}},
             ["unit_id", "rule_text", "rationale"]), suggest_rule),
]}

AGENT_TOOLS: dict[str, list[str]] = {
    "observateur": ["company_overview", "team_trends"],
    "mesure": ["get_team_rules", "measure_rule_effect", "record_rule_effect"],
    "conseiller": ["get_team_rules", "suggest_rule"],
}
