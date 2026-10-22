"""Cerveau de démo déterministe pour les agents d'équipe (sans clé API).
Mêmes outils et mêmes données que les agents LLM ; sert aux tests et au plan B."""
from __future__ import annotations

from agent.scripted_utils import _board_data, _call, _post, _results
from agent.llm import Reply

RULES_BY_CAUSE = {
    "réunions ajoutées le jour même": "Pas d'ajout de réunion le jour même après 17h",
    "réunions en dehors des horaires": "Pas de réunion après 19h sauf urgence client",
    "nombre de réunions": "Réunions récurrentes plafonnées à 30 minutes",
}


class ScriptedTeamLLM:
    def complete(self, *, agent, system, messages, tools, tool_choice=None) -> Reply:
        board, _, _ = messages[0]["content"].partition("## Consigne de l'orchestrateur")
        kinds = next(t for t in tools if t["name"] == "post_message")["input_schema"]["properties"]["kind"]["enum"]
        return getattr(self, f"_{agent}")(board, kinds, _results(messages))

    def _observateur(self, board, kinds, res) -> Reply:
        if "company_overview" not in res:
            return Reply("tool_use", [_call("company_overview")])
        units = res["company_overview"][0]
        top = units[0]
        if "team_trends" not in res:
            return Reply("tool_use", [_call("team_trends", unit_id=top["unit_id"])])
        trend = res["team_trends"][0]["trend"]
        if kinds == ["reponse"]:
            return _post("conseiller", "reponse", f"{top['team']}, récupération moyenne par semaine : "
                         + ", ".join(f"{w['week']} : {w['avg_recovery']}" for w in trend) + ".")
        stable = [u["team"] for u in units[1:] if u["recovery_change"] >= 0]
        return _post("mesure", "signal",
                     f"Unité prioritaire : {top['team']} ({top['n_bucket']} personnes). Récupération moyenne "
                     f"{top['recovery_change']:+d} points vs le début de période ; part de l'équipe en dette "
                     f"de récupération : {top['share_in_debt']}. Cause principale : {top['top_cause']} ({top['cause_change']}). "
                     f"Stables : {', '.join(stable) or 'aucune'}. "
                     "Les équipes de moins de 8 personnes ne sont pas affichées.",
                     {"prioritaire": top["unit_id"], "nom": top["team"], "cause": top["top_cause"],
                      "evolution_cause": top["cause_change"], "recovery_change": top["recovery_change"]})

    def _mesure(self, board, kinds, res) -> Reply:
        if "get_team_rules" not in res:
            return Reply("tool_use", [_call("get_team_rules")])
        applied = [r for r in res["get_team_rules"][0] if r["status"] in ("applied", "measured")]
        if applied and "measure_rule_effect" not in res:
            return Reply("tool_use", [_call("measure_rule_effect", rule_id=r["id"]) for r in applied])
        effects = res.get("measure_rule_effect", [])
        done = [e for e in effects if e.get("verdict") in ("efficace", "sans effet net")]
        if done and "record_rule_effect" not in res:
            return Reply("tool_use", [_call(
                "record_rule_effect", rule_id=e["rule_id"],
                measured_effect=f"{e['recovery_change']:+d} points de récupération, {e['cause_change']} de "
                                f"{e['cause_metric']}, en {e['weeks_since']} semaines") for e in done])
        good = next((e for e in done if e["verdict"] == "efficace"), None)
        if not effects:
            return _post("conseiller", "mesure", "Aucune règle appliquée pour l'instant : rien à mesurer.")
        lines = [f"« {e['rule_text']} » : " + (
            f"{e['verdict']}, récupération {e['recovery_before']} → {e['recovery_after']}, "
            f"{e['cause_metric']} {e['cause_change']} en {e['weeks_since']} semaines"
            if e["verdict"] != "trop tôt" else "trop récente pour être mesurée") for e in effects]
        return _post("conseiller", "mesure", " ; ".join(lines) + "."
                     + (" Une règle de ce type peut être transposée à l'unité prioritaire." if good else ""),
                     {"regle_efficace": good["rule_text"] if good else None,
                      "effet": f"{good['recovery_change']:+d} points de récupération" if good else None})

    def _conseiller(self, board, kinds, res) -> Reply:
        signal, mesure = _board_data(board, "signal"), _board_data(board, "mesure")
        rule = RULES_BY_CAUSE.get(signal.get("cause"), "Pas d'ajout de réunion le jour même après 17h")
        if "question" in kinds and "| reponse]" not in board:
            return _post("observateur", "question",
                         f"Donne-moi la courbe semaine par semaine de {signal.get('nom')} : "
                         "la dérive est-elle récente ou installée ?")
        if "proposition" in kinds:
            if "suggest_rule" not in res:
                return Reply("tool_use", [_call("suggest_rule", unit_id=signal["prioritaire"], rule_text=rule,
                                                rationale=f"cause principale : {signal.get('cause')}")])
            ref = (f" La même logique (« {mesure['regle_efficace']} ») a donné {mesure['effet']} dans une autre équipe."
                   if mesure.get("regle_efficace") else "")
            return _post("orchestrateur", "proposition",
                         f"Règle suggérée pour {signal.get('nom')} : « {rule} ». Elle agit directement sur la "
                         f"cause principale ({signal.get('cause')}, {signal.get('evolution_cause')}).{ref}")
        ref = (f" Une règle du même type a déjà donné {mesure['effet']} ailleurs dans l'entreprise ; "
               "on mesurera l'effet de celle-ci dans 4 semaines." if mesure.get("regle_efficace") else "")
        return _post("tous", "message_final",
                     f"{signal.get('nom')} : récupération moyenne en baisse ({signal.get('recovery_change'):+d} points), "
                     f"la cause principale étant les {signal.get('cause')} ({signal.get('evolution_cause')}). "
                     f"Règle suggérée : « {rule} ».{ref} Les autres unités sont stables.")
