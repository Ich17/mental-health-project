"""Cerveau de démo déterministe : même interface que ClaudeLLM.

Il appelle les vrais outils (donc les vraies données de contracts.py) et
construit ses messages à partir de leurs résultats, avec des règles simples.
Il sert à :
- faire tourner la CI et les tests sans clé API ;
- développer le front sans consommer de tokens ;
- avoir un plan B si l'API ou le réseau lâchent pendant la démo.

Il suit le même protocole que les agents LLM (questions, révisions), ce qui
permet de tester l'orchestrateur de bout en bout.
"""
from __future__ import annotations

import ast
import itertools
import json
import re
from datetime import date
from statistics import mean

from agent.llm import Reply

_ids = itertools.count(1)


def _call(name: str, **args) -> dict:
    return {"type": "tool_use", "id": f"s{next(_ids)}", "name": name, "input": args}


def _post(to: str, kind: str, content: str, data: dict | None = None) -> Reply:
    args = {"to": to, "kind": kind, "content": content}
    if data:
        args["data"] = data
    return Reply("tool_use", [_call("post_message", **args)])


def _board_data(board: str, kind: str) -> dict:
    """Récupère le champ `data` du dernier message d'un type donné sur le tableau."""
    blocks = [b for b in board.split("\n\n[") if f"| {kind}]" in b.split("\n")[0]]
    if not blocks:
        return {}
    m = re.search(r"Données : (\{.*\})", blocks[-1], re.S)
    return ast.literal_eval(m.group(1)) if m else {}


def _results(messages: list[dict]) -> dict[str, object]:
    """Résultats des outils déjà appelés à ce tour, indexés par nom d'outil."""
    names, out = {}, {}
    for m in messages:
        if m["role"] == "assistant":
            for b in m["content"]:
                if b["type"] == "tool_use":
                    names[b["id"]] = b["name"]
        elif isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_result" and not b.get("is_error"):
                    try:
                        out.setdefault(names[b["tool_use_id"]], []).append(json.loads(b["content"]))
                    except (json.JSONDecodeError, KeyError):
                        pass
    return out


PEAKS = ("pic_passe", "pic_attendu")
# Bloc proposé par défaut, et celui qu'on essaie si l'Évaluateur juge les déjeuners sans effet.
BLOCK_DEFAULT = ("dejeuner", "12:30", "13:30")
BLOCK_SWITCH = ("sport", "18:00", "19:00")
BLOCK_LABELS = {"dejeuner": "pause(s) déjeuner protégée(s)", "sport": "créneau(x) sport en fin de journée"}
BLOCK_PITCH = {"dejeuner": "protéger ta pause déjeuner", "sport": "bloquer un créneau sport en fin de journée"}   # tendances d'assess_trend qui ne sont pas une dérive de fond
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _jour(iso: str) -> str:
    from datetime import date

    d = date.fromisoformat(iso)
    return f"{JOURS[d.weekday()]} {d.day}"


def _pct(new: float, old: float) -> int:
    return round(100 * (new - old) / old) if old else 0


class ScriptedLLM:
    def complete(self, *, agent, system, messages, tools, tool_choice=None) -> Reply:
        prompt = messages[0]["content"]
        board, _, instruction = prompt.partition("## Consigne de l'orchestrateur")
        kinds = next(t for t in tools if t["name"] == "post_message")["input_schema"]["properties"]["kind"]["enum"]
        res = _results(messages)
        return getattr(self, f"_{agent}")(board, instruction, kinds, res)

    # ------------------------------------------------------------------ Détection
    def _detection(self, board, instruction, kinds, res) -> Reply:
        if "get_daily_metrics" not in res:
            return Reply("tool_use", [_call("get_daily_metrics", days=42), _call("forecast_week"),
                                      _call("assess_trend")])
        days = res["get_daily_metrics"][0]
        forecast = res["forecast_week"][0] if "forecast_week" in res else []
        trend = res["assess_trend"][0] if "assess_trend" in res else {"tendance": "inconnue", "explication": ""}

        if kinds == ["reponse"]:
            recent = days[-14:]
            heavy = [d["recovery"] for d in recent if d["last_minute_meetings"] >= 3]
            light = [d["recovery"] for d in recent if d["last_minute_meetings"] <= 1]
            if not heavy or not light:
                return _post("analyse", "reponse", "Pas de comparaison possible sur les 14 derniers jours : "
                             "il faut des jours avec et sans calls ajoutés le jour même.")
            return _post("analyse", "reponse",
                         f"Sur les 14 derniers jours : récupération moyenne {mean(heavy):.0f} après les jours "
                         f"à 3 calls ajoutés ou plus ({len(heavy)} jours), contre {mean(light):.0f} après les "
                         f"jours à 0 ou 1 ({len(light)} jours).",
                         {"recup_jours_charges": round(mean(heavy)), "recup_jours_legers": round(mean(light))})

        base, last = days[-35:-7], days[-7:]
        avg = lambda rows, k: mean(r[k] for r in rows)  # noqa: E731
        drift = {k: _pct(avg(last, k), avg(base, k)) for k in
                 ("recovery", "hrv", "sleep_h", "meeting_hours", "last_minute_meetings")}
        red = [d["date"] for d in forecast if d["risk"] == "rouge"]
        tendance = trend["tendance"]
        if tendance in ("pic_passe", "stable"):      # le passé ne compte plus : seuls les jours à venir
            level = "rouge" if len(red) >= 3 else "orange" if red else "vert"
        elif tendance in ("pic_attendu", "baisse_recente"):
            level = "rouge" if len(red) >= 3 else "orange"
        else:
            level = "rouge" if drift["recovery"] <= -20 or len(red) >= 3 else \
                    "orange" if drift["recovery"] <= -10 or red else "vert"
        reasons = "; ".join(f"{_jour(d['date'])} ({d['predicted_recovery']}, {d['reason']})"
                            for d in forecast if d["risk"] == "rouge")
        return _post("analyse", "signal",
                     f"Niveau {level}. Tendance : {tendance}. {trend['explication']} "
                     f"Sur 7 jours vs la base des 4 semaines précédentes : récupération "
                     f"{drift['recovery']:+d} %, HRV {drift['hrv']:+d} %, sommeil {drift['sleep_h']:+d} %. "
                     f"Côté charge : réunions {drift['meeting_hours']:+d} %, calls ajoutés le jour même "
                     f"{drift['last_minute_meetings']:+d} %. Jours rouges à venir : {reasons or 'aucun'}.",
                     {"niveau": level, "tendance": tendance, "jours_rouges": red,
                      "derives": {k: f"{v:+d} %" for k, v in drift.items()}})

    # ------------------------------------------------------------------ Évaluateur
    def _evaluateur(self, board, instruction, kinds, res) -> Reply:
        if "get_memory" not in res:
            return Reply("tool_use", [_call("get_memory"), _call("evaluate_blocks")])
        today = date.today().isoformat()
        ended = [e for e in res["get_memory"][0]["experiments"] if str(e.get("end_date") or "9999") < today]
        if ended and "evaluate_experiment" not in res:
            return Reply("tool_use", [_call("evaluate_experiment", experiment_id=ended[-1]["id"])])

        blocs = res["evaluate_blocks"][0]["blocs"]
        exp = res.get("evaluate_experiment", [None])[0]
        exp_ok = bool(exp) and str(exp.get("verdict", "")).startswith(("garder", "efficace"))
        if "record_evaluation" not in res:
            calls = [_call("record_evaluation", subject=f"bloc_{b['bloc']}", verdict=b["verdict"],
                           effect_text=f"{b['ecart_points']:+d} points de récupération le lendemain "
                                       f"({b['jours_avec_bloc']} jours avec bloc)", confidence="moyenne")
                     for b in blocs if b["verdict"] != "trop tôt"]
            if exp and exp.get("verdict"):
                calls.append(_call("record_evaluation", subject=f"experience_{exp['id']}",
                                   verdict="efficace" if exp_ok else "sans effet net",
                                   effect_text=f"« {exp['rule_text']} » : {exp['verdict']}", confidence="moyenne"))
            if calls:
                return Reply("tool_use", calls[:3])

        lines = []
        for b in blocs:
            if b["verdict"] == "trop tôt":
                lines.append(f"Blocs {b['bloc']} : trop tôt pour conclure ({b['jours_avec_bloc']} jour(s)).")
                continue
            note = f" ({b['note']})" if b.get("note") else ""
            lines.append(f"Blocs {b['bloc']} acceptés ({b['jours_avec_bloc']} jours) : récupération "
                         f"{b['recuperation_avec_bloc']} le lendemain contre {b['recuperation_sans_bloc']} les autres "
                         f"jours ouvrés ({b['ecart_points']:+d} points) → {b['verdict']}{note}.")
        if exp:
            lines.append(f"Expérience « {exp['rule_text']} » : {exp.get('verdict') or 'en cours'}.")
        return _post("analyse", "evaluation",
                     " ".join(lines) or "Rien n'a encore été mis en place : rien à évaluer.",
                     {"blocs": [{"bloc": b["bloc"], "verdict": b["verdict"], "ecart_points": b.get("ecart_points")}
                                for b in blocs],
                      "experience_validee": exp["rule_text"] if exp_ok else None,
                      "derniere_experience": exp["rule_text"] if exp else None})

    # ------------------------------------------------------------------ Analyse
    def _analyse(self, board, instruction, kinds, res) -> Reply:
        if kinds == ["reponse"]:
            if "get_drivers" not in res:
                return Reply("tool_use", [_call("get_drivers"), _call("get_memory")])
            d = res["get_drivers"][0][:2]
            exps = [e for e in res["get_memory"][0]["experiments"] if str(e.get("verdict", "")).startswith("garder")]
            memo = f" Ce qui a déjà marché : « {exps[-1]['rule_text']} » ({exps[-1]['verdict']})." if exps else ""
            return _post("action", "reponse",
                         "Deux causes ressortent : " + " ; ".join(f"{x['label'].lower()} ({x['effect']})" for x in d)
                         + "." + memo, {"causes": [x["factor"] for x in d]})
        peak = _board_data(board, "signal").get("tendance") in PEAKS
        if "question" in kinds and "| reponse]" not in board and not peak:
            return _post("detection", "question",
                         "Les calls ajoutés le jour même expliquent-ils la baisse ? Donne-moi la récupération "
                         "moyenne après les jours chargés en calls de dernière minute vs les jours légers.")
        if "get_drivers" not in res:
            return Reply("tool_use", [_call("get_drivers"), _call("get_memory")])
        drivers = res["get_drivers"][0][:2]
        ev = _board_data(board, "evaluation")
        valid = ev.get("experience_validee")
        tested = (ev.get("derniere_experience") or "").lower()
        to_test = None
        if "last_minute_meetings" in [d["factor"] for d in drivers] and "jour même" not in tested and not peak:
            to_test = "Refuser les calls ajoutés le jour même après 17h"
        answer = _board_data(board, "reponse")
        confirm = (f" La détection confirme : {answer['recup_jours_charges']} de récupération après les jours "
                   f"chargés contre {answer['recup_jours_legers']} après les jours légers.") if answer else ""
        causes = "; ".join(f"{d['label']} ({d['effect']}, confiance {d['confidence']})" for d in drivers)
        memo = f" Déjà validé pour cette personne (évaluateur) : « {valid} »." if valid else ""
        test = f" À tester : « {to_test} »." if to_test else ""
        if peak:
            causes = ("la baisse vient d'un pic de charge ponctuel, pas d'une cause de fond. "
                      f"Facteurs habituels pour mémoire : {causes}")
        return _post("action", "analyse", f"Causes probables : {causes}.{confirm}{memo}{test}",
                     {"causes": [d["factor"] for d in drivers], "a_tester": to_test, "deja_valide": valid})

    # ------------------------------------------------------------------ Action
    def _action(self, board, instruction, kinds, res) -> Reply:
        signal, analysis = _board_data(board, "signal"), _board_data(board, "analyse")
        if "[personne → action | question]" in board:  # mode chat
            if "question" in kinds and "| reponse]" not in board:
                return _post("analyse", "question",
                             "La personne demande pourquoi elle est à plat certains jours. "
                             "Quelles causes ressortent de ses données et de sa mémoire ?")
            answer = next((b for b in board.split("\n\n[") if b.startswith("analyse → action | reponse]")), "")
            text = answer.split("\n", 1)[1].split("\nDonnées :")[0] if answer else ""
            return _post("tous", "message_final",
                         (f"D'après tes données : {text} " if text else "")
                         + "Ce sont des hypothèses : on peut en tester une pendant deux semaines si tu veux.")
        red = signal.get("jours_rouges", [])[:2]
        peak = signal.get("tendance") in PEAKS
        lunch = next((b for b in _board_data(board, "evaluation").get("blocs", []) if b["bloc"] == "dejeuner"), {})
        purpose, start, end = BLOCK_SWITCH if lunch.get("verdict") == "sans effet net" else BLOCK_DEFAULT

        if "proposition" in kinds:
            if "get_free_slots" not in res and red:
                return Reply("tool_use", [_call("get_free_slots", date=d) for d in red])
            if "propose_block" not in res and "start_experiment" not in res:
                calls = [_call("propose_block", date=d, start=start, end=end, purpose=purpose) for d in red]
                if peak:
                    pass  # pic ponctuel : pas d'expérience, on protège seulement les jours à risque
                elif analysis.get("a_tester"):
                    calls.append(_call("start_experiment", rule_text=analysis["a_tester"], days=14))
                elif analysis.get("deja_valide"):
                    calls.append(_call("start_experiment", rule_text=analysis["deja_valide"], days=14))
                if calls:
                    return Reply("tool_use", calls)
            n_blocks = len(res.get("propose_block", []))
            exp = res.get("start_experiment", [{}])[0].get("payload", {}).get("rule_text")
            if not n_blocks and not exp:
                return _post("orchestrateur", "proposition",
                             "Plan vide : la baisse était ponctuelle et aucun jour à risque n'arrive. "
                             "Rien à bloquer cette semaine.")
            return _post("orchestrateur", "proposition",
                         f"Plan : {n_blocks} {BLOCK_LABELS[purpose]} sur les jours rouges"
                         + (f", et une expérience de 14 jours : « {exp} »" if exp else "")
                         + ". Objectif : limiter la dette de récupération sur les jours à risque.")

        rec = int(signal.get("derives", {}).get("recovery", "0 %").replace(" %", ""))
        if signal.get("tendance") == "pic_passe":
            trend = ("Ta récupération avait baissé pendant ta semaine très chargée, mais elle est revenue "
                     "à ton niveau habituel : pas de dérive de fond.")
        elif signal.get("tendance") == "pic_attendu":
            trend = ("Ta récupération baisse cette semaine, pendant un pic de charge attendu. "
                     "Je vérifie la semaine prochaine qu'elle remonte.")
        elif rec < 0:
            trend = (f"Ta récupération a baissé de {-rec} % cette semaine par rapport à ton habitude, "
                     "surtout après les jours chargés en calls ajoutés au dernier moment.")
        else:
            trend = "Ta récupération est stable par rapport à ton habitude."
        parts = [trend]
        if lunch.get("verdict") == "efficace":
            parts.append(f"Tes déjeuners protégés ont marché ({lunch.get('ecart_points', 0):+d} points de récupération "
                         "le lendemain) : on continue.")
        elif lunch.get("verdict") == "sans effet net" and red:
            parts.append("Tes déjeuners protégés n'ont rien changé à ta récupération : on essaie autre chose.")
        if red:
            n = "Une journée s'annonce difficile" if len(red) == 1 else f"{len(red)} journées s'annoncent difficiles"
            parts.append(f"{n} ({', '.join(_jour(d) for d in red)}) : je te propose d'y {BLOCK_PITCH[purpose]}.")
        if analysis.get("deja_valide") and not peak:
            parts.append(f"La dernière fois, « {analysis['deja_valide']} » t'avait réussi.")
        if analysis.get("a_tester"):
            parts.append(f"Je te propose aussi de tester pendant 14 jours : « {analysis['a_tester']} ».")
        if red or analysis.get("a_tester") or (analysis.get("deja_valide") and not peak):
            parts.append("Tout est prêt : tu acceptes ou tu refuses en un clic.")
        else:
            parts.append("Rien à bloquer cette semaine.")
        return _post("tous", "message_final", " ".join(parts))
