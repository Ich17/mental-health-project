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
            return Reply("tool_use", [_call("get_daily_metrics", days=42), _call("forecast_week")])
        days = res["get_daily_metrics"][0]
        forecast = res["forecast_week"][0] if "forecast_week" in res else []

        if kinds == ["reponse"]:
            recent = days[-14:]
            heavy = [d["recovery"] for d in recent if d["last_minute_meetings"] >= 3]
            light = [d["recovery"] for d in recent if d["last_minute_meetings"] <= 1]
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
        level = "rouge" if drift["recovery"] <= -20 or len(red) >= 3 else \
                "orange" if drift["recovery"] <= -10 or red else "vert"
        reasons = "; ".join(f"{_jour(d['date'])} ({d['predicted_recovery']}, {d['reason']})"
                            for d in forecast if d["risk"] == "rouge")
        return _post("analyse", "signal",
                     f"Niveau {level}. Sur 7 jours vs la base des 4 semaines précédentes : récupération "
                     f"{drift['recovery']:+d} %, HRV {drift['hrv']:+d} %, sommeil {drift['sleep_h']:+d} %. "
                     f"Côté charge : réunions {drift['meeting_hours']:+d} %, calls ajoutés le jour même "
                     f"{drift['last_minute_meetings']:+d} %. Jours rouges à venir : {reasons or 'aucun'}.",
                     {"niveau": level, "jours_rouges": red,
                      "derives": {k: f"{v:+d} %" for k, v in drift.items()}})

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
        if "question" in kinds and "| reponse]" not in board:
            return _post("detection", "question",
                         "Les calls ajoutés le jour même expliquent-ils la baisse ? Donne-moi la récupération "
                         "moyenne après les jours chargés en calls de dernière minute vs les jours légers.")
        if "get_drivers" not in res:
            return Reply("tool_use", [_call("get_drivers"), _call("get_memory")])
        if "evaluate_experiment" not in res:
            exps = res["get_memory"][0]["experiments"]
            if exps:
                return Reply("tool_use", [_call("evaluate_experiment", experiment_id=exps[-1]["id"])])

        drivers = res["get_drivers"][0][:2]
        exp = res.get("evaluate_experiment", [None])[0]
        valid = exp["rule_text"] if exp and str(exp.get("verdict", "")).startswith("garder") else None
        tested = (exp or {}).get("rule_text", "").lower()
        to_test = None
        if "last_minute_meetings" in [d["factor"] for d in drivers] and "jour même" not in tested:
            to_test = "Refuser les calls ajoutés le jour même après 17h"
        answer = _board_data(board, "reponse")
        confirm = (f" La détection confirme : {answer['recup_jours_charges']} de récupération après les jours "
                   f"chargés contre {answer['recup_jours_legers']} après les jours légers.") if answer else ""
        causes = "; ".join(f"{d['label']} ({d['effect']}, confiance {d['confidence']})" for d in drivers)
        memo = (f" Déjà validé pour cette personne : « {exp['rule_text']} », {exp['verdict']}."
                if valid else "")
        test = f" À tester : « {to_test} »." if to_test else ""
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

        if "proposition" in kinds:
            if "get_free_slots" not in res and red:
                return Reply("tool_use", [_call("get_free_slots", date=d) for d in red])
            if "propose_block" not in res and "start_experiment" not in res:
                calls = [_call("propose_block", date=d, start="12:30", end="13:30", purpose="dejeuner")
                         for d in red]
                if analysis.get("a_tester"):
                    calls.append(_call("start_experiment", rule_text=analysis["a_tester"], days=14))
                elif analysis.get("deja_valide"):
                    calls.append(_call("start_experiment", rule_text=analysis["deja_valide"], days=14))
                if calls:
                    return Reply("tool_use", calls)
            n_blocks = len(res.get("propose_block", []))
            exp = res.get("start_experiment", [{}])[0].get("payload", {}).get("rule_text")
            return _post("orchestrateur", "proposition",
                         f"Plan : {n_blocks} pause(s) déjeuner protégée(s) sur les jours rouges"
                         + (f", et une expérience de 14 jours : « {exp} »" if exp else "")
                         + ". Objectif : limiter la dette de récupération sur les jours à risque.")

        rec = int(signal.get("derives", {}).get("recovery", "0 %").replace(" %", ""))
        trend = (f"Ta récupération a baissé de {-rec} % cette semaine par rapport à ton habitude, "
                 "surtout après les jours chargés en calls ajoutés au dernier moment." if rec < 0 else
                 "Ta récupération est stable par rapport à ton habitude.")
        parts = [trend]
        if red:
            n = "Une journée s'annonce difficile" if len(red) == 1 else f"{len(red)} journées s'annoncent difficiles"
            parts.append(f"{n} ({', '.join(_jour(d) for d in red)}) : je te propose d'y protéger ta pause déjeuner.")
        if analysis.get("deja_valide"):
            parts.append(f"La dernière fois, « {analysis['deja_valide']} » t'avait réussi.")
        if analysis.get("a_tester"):
            parts.append(f"Je te propose aussi de tester pendant 14 jours : « {analysis['a_tester']} ».")
        parts.append("Tout est prêt : tu acceptes ou tu refuses en un clic.")
        return _post("tous", "message_final", " ".join(parts))
