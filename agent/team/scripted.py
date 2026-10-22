"""Cerveau de démo déterministe pour les agents d'équipe (sans clé API)."""
from __future__ import annotations

from agent.individuel.scripted import _board_data, _call, _post, _results
from agent.llm import Reply


class ScriptedTeamLLM:
    def complete(self, *, agent, system, messages, tools, tool_choice=None) -> Reply:
        board, _, instruction = messages[0]["content"].partition("## Consigne de l'orchestrateur")
        kinds = next(t for t in tools if t["name"] == "post_message")["input_schema"]["properties"]["kind"]["enum"]
        return getattr(self, f"_{agent}")(board, kinds, _results(messages))

    def _observateur(self, board, kinds, res) -> Reply:
        if "team_trends" not in res:
            return Reply("tool_use", [_call("team_trends")])
        t = res["team_trends"][0]
        trend = t["trend"]
        first, last = trend[0]["avg_recovery"], trend[-1]["avg_recovery"]
        if kinds == ["reponse"]:
            return _post("conseiller", "reponse",
                         "Récupération moyenne par semaine : "
                         + ", ".join(f"{w['week']} : {w['avg_recovery']}" for w in trend) + ".")
        direction = "baisse" if last < first - 2 else "hausse" if last > first + 2 else "stable"
        return _post("conseiller", "signal",
                     f"Équipe {t['team']} : récupération moyenne en {direction} ({first} → {last} sur "
                     f"{len(trend)} semaines). La {t['share_in_debt']} de l'équipe est en dette de récupération. "
                     f"Cause principale : {t['top_cause']} ({t['cause_change']}).",
                     {"tendance": direction, "cause": t["top_cause"], "evolution_cause": t["cause_change"]})

    def _conseiller(self, board, kinds, res) -> Reply:
        signal = _board_data(board, "signal")
        if "question" in kinds and "| reponse]" not in board:
            return _post("observateur", "question", "Donne-moi la récupération moyenne semaine par semaine.")
        if "proposition" in kinds:
            if "get_team_rules" not in res:
                return Reply("tool_use", [_call("get_team_rules")])
            if "suggest_rule" not in res:
                return Reply("tool_use", [_call(
                    "suggest_rule", rule_text="Pas de réunion ajoutée après 18h pour le lendemain avant 10h",
                    rationale=f"cause principale : {signal.get('cause')}")])
            past = [r for r in res["get_team_rules"][0] if r.get("measured_effect")]
            ref = f" Une règle comparable a donné {past[-1]['measured_effect']}." if past else ""
            return _post("orchestrateur", "proposition",
                         "Règle suggérée : pas de réunion ajoutée après 18h pour le lendemain avant 10h. "
                         f"Elle cible directement la cause principale ({signal.get('cause')}).{ref}")
        return _post("tous", "message_final",
                     f"La récupération moyenne de l'équipe est en {signal.get('tendance', 'évolution')}, "
                     f"principalement à cause des {signal.get('cause')} ({signal.get('evolution_cause')}). "
                     "Règle suggérée : pas de réunion ajoutée après 18h pour le lendemain avant 10h. "
                     "La dernière règle de ce type a amélioré la récupération moyenne de l'équipe ; "
                     "on mesurera l'effet de celle-ci sur 4 semaines."
                     )
