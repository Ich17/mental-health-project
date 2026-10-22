"""Outils des agents d'équipe et leurs droits.

Confidentialité appliquée par le code (CLAUDE.md §3) :
- le team_id vient du contexte du run, jamais d'un argument du LLM ;
- aucun outil d'équipe n'expose de donnée individuelle : team_trends ne
  renvoie que des agrégats, et le seuil n >= 8 est dans la requête SQL ;
- suggest_rule remplit un brouillon, enregistré seulement après la revue du code.
"""
from __future__ import annotations

import contracts
from agent.toolkit import RunContext, Tool, obj


def team_trends(ctx: RunContext):
    return contracts.team_trends(ctx.team_id)


def get_team_rules(ctx: RunContext):
    return ctx.store.team_rules(ctx.team_id)


def suggest_rule(ctx: RunContext, rule_text: str, rationale: str):
    ctx.draft_actions.append({"kind": "team_rule", "payload": {
        "team_id": ctx.team_id, "rule_text": rule_text, "rationale": rationale}})
    return {"note": "brouillon : relu par le code puis proposé à la RH"}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("team_trends", "Tendances anonymes de l'équipe : récupération moyenne par semaine, part en dette, "
         "cause principale. Agrégats uniquement (n ≥ 8 garanti par la requête).", obj(), team_trends),
    Tool("get_team_rules", "Règles d'équipe passées ou suggérées, avec leur effet mesuré.", obj(), get_team_rules),
    Tool("suggest_rule", "Ajoute au plan une règle d'équipe à suggérer à la RH.",
         obj({"rule_text": {"type": "string"}, "rationale": {"type": "string"}}, ["rule_text", "rationale"]),
         suggest_rule),
]}

AGENT_TOOLS: dict[str, list[str]] = {
    "observateur": ["team_trends"],
    "conseiller": ["get_team_rules", "suggest_rule"],
}
