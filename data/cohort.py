"""Cohorte RH simulée (CLAUDE.md §4) et agrégats anonymes pour la vue équipe.

40 salariés, 4 équipes, 8 semaines. Chaque équipe a son histoire :
- M&A (12)        : calls ajoutés après 18h en forte hausse sur les 3 dernières semaines ;
- Leveraged Fin. (11) : charge stable, rien à signaler ;
- Coverage (10)   : beaucoup de calls de dernière minute, puis la règle
                    « pas d'ajout de réunion le jour même après 17h » appliquée
                    il y a 4 semaines : la mesure doit montrer son effet ;
- Data (7)        : moins de 8 personnes, jamais affichée seule.

Confidentialité (CLAUDE.md §3), appliquée ici et pas dans les agents :
- aucune fonction publique ne renvoie de donnée individuelle ;
- une équipe de moins de 8 personnes n'est jamais exposée. Son département
  est alors présenté en bloc, sans ses équipes sœurs, pour éviter la
  déduction par différence ;
- valeurs lissées : moyennes arrondies, parts qualitatives, effectifs en tranches.

À remplacer par des requêtes ClickHouse sur la cohorte réelle, mêmes sorties.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from functools import lru_cache
from statistics import mean

MIN_GROUP = 8
WEEKS = 8
RULE_WEEK = 4  # la règle Coverage démarre au début de la semaine 4

TEAMS = {
    "ma": {"name": "M&A", "department": "Banque d'affaires", "size": 12},
    "levfin": {"name": "Leveraged Finance", "department": "Banque d'affaires", "size": 11},
    "coverage": {"name": "Coverage", "department": "Coverage & Data", "size": 10},
    "data": {"name": "Data", "department": "Coverage & Data", "size": 7},
}

LOAD = {
    "last_minute_meetings": "réunions ajoutées le jour même",
    "meetings_after_18h": "réunions ajoutées après 18h",
    "meeting_hours": "heures de réunion",
}

SEED_RULE = {"team_id": "coverage", "rule_text": "Pas d'ajout de réunion le jour même après 17h"}


def start_monday() -> date:
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(weeks=WEEKS)


def rule_start_date() -> str:
    return (start_monday() + timedelta(weeks=RULE_WEEK)).isoformat()


def _team_load(team: str, week: int) -> dict:
    """Charge moyenne d'une journée de semaine, selon l'histoire de l'équipe."""
    if team == "ma":
        ramp = max(0, week - 4)                      # dérive sur les dernières semaines
        return {"meeting_hours": 5.0 + 0.4 * ramp, "last_minute_meetings": 1.2 + 0.3 * ramp,
                "meetings_after_18h": 0.6 + 0.45 * ramp}
    if team == "coverage":
        before = week < RULE_WEEK
        return {"meeting_hours": 5.2, "last_minute_meetings": 2.6 if before else 1.0,
                "meetings_after_18h": 1.2 if before else 0.6}
    if team == "data":
        return {"meeting_hours": 3.5, "last_minute_meetings": 0.8, "meetings_after_18h": 0.4}
    return {"meeting_hours": 4.6, "last_minute_meetings": 1.0, "meetings_after_18h": 0.5}


@lru_cache(maxsize=1)
def _simulate() -> tuple:
    """Lignes individuelles (privées à ce module) : (team, person, week, metrics)."""
    rng = random.Random(7)
    rows = []
    for team, meta in TEAMS.items():
        for p in range(meta["size"]):
            base = rng.gauss(64, 5)
            for week in range(WEEKS):
                load = _team_load(team, week)
                days = []
                for _ in range(5):
                    mh = max(0.5, rng.gauss(load["meeting_hours"], 0.9))
                    lm = max(0, round(rng.gauss(load["last_minute_meetings"], 0.8)))
                    late = max(0, round(rng.gauss(load["meetings_after_18h"], 0.6)))
                    rec = base - 1.5 * max(0, mh - 4) - 3.5 * lm - 4.0 * late + rng.gauss(0, 5)
                    days.append({"meeting_hours": mh, "last_minute_meetings": lm,
                                 "meetings_after_18h": late, "recovery": max(10, min(95, rec))})
                rows.append((team, p, week, {k: mean(d[k] for d in days) for k in days[0]}))
    return tuple(rows)


def _rows(teams: list[str]) -> list[tuple]:
    return [r for r in _simulate() if r[0] in teams]


def _bucket(n: int) -> str:
    lo = (n // 5) * 5
    return f"{lo}-{lo + 5}"


def _share_label(share: float) -> str:
    return "minorité" if share < 0.35 else "environ la moitié" if share <= 0.65 else "majorité"


def _week_label(week: int) -> str:
    y, w, _ = (start_monday() + timedelta(weeks=week)).isocalendar()
    return f"{y}-W{w:02d}"


def _aggregate(unit_id: str, name: str, teams: list[str], scope: str) -> dict:
    rows = _rows(teams)
    people = {(t, p) for t, p, _, _ in rows}
    trend = [{"week": _week_label(w), "avg_recovery": round(mean(m["recovery"] for _, _, wk, m in rows if wk == w))}
             for w in range(WEEKS)]

    early, late = range(0, 4), range(WEEKS - 2, WEEKS)
    in_debt = 0
    for person in people:
        mine = {wk: m for t, p, wk, m in rows if (t, p) == person}
        before = mean(mine[w]["recovery"] for w in early)
        after = mean(mine[w]["recovery"] for w in late)
        in_debt += after < 0.9 * before

    changes = {}
    for k in LOAD:
        b = mean(m[k] for _, _, w, m in rows if w in early)
        a = mean(m[k] for _, _, w, m in rows if w in late)
        changes[k] = (a - b) / b if b else 0
    top = max(changes, key=changes.get)
    return {
        "unit_id": unit_id, "team": name, "scope": scope, "n_bucket": _bucket(len(people)),
        "share_in_debt": _share_label(in_debt / len(people)),
        "top_cause": LOAD[top] if changes[top] > 0.1 else "aucune cause nette",
        "cause_change": f"{changes[top]:+.0%}".replace("%", " %"),
        "recovery_change": trend[-1]["avg_recovery"] - round(mean(t["avg_recovery"] for t in trend[:4])),
        "trend": trend,
    }


def reportable_units() -> dict[str, dict]:
    """Unités affichables : une équipe si elle compte au moins 8 personnes,
    sinon son département entier (sans ses équipes sœurs)."""
    small_depts = {m["department"] for m in TEAMS.values() if m["size"] < MIN_GROUP}
    units = {}
    for tid, m in TEAMS.items():
        if m["department"] in small_depts:
            dept_id = "dept:" + m["department"].lower().replace(" ", "-").replace("&", "et")
            teams = [t for t, x in TEAMS.items() if x["department"] == m["department"]]
            units[dept_id] = {"name": m["department"], "teams": teams, "scope": "département"}
        else:
            units[tid] = {"name": m["name"], "teams": [tid], "scope": "équipe"}
    return units


def unit_of(team_id: str) -> str | None:
    for uid, u in reportable_units().items():
        if team_id in u["teams"]:
            return uid
    return None


def team_trends(team_id: str) -> dict:
    """Agrégats d'une unité. {"insufficient_group": True, "unit_id": ...} si l'équipe
    demandée n'est pas affichable seule."""
    units = reportable_units()
    if team_id not in units:
        if team_id in TEAMS:
            return {"insufficient_group": True, "unit_id": unit_of(team_id)}
        return {"error": f"unité inconnue : {team_id}"}
    u = units[team_id]
    return _aggregate(team_id, u["name"], u["teams"], u["scope"])


def company_overview() -> list[dict]:
    """Toutes les unités affichables, de la plus en dérive à la plus stable."""
    out = [team_trends(uid) for uid in reportable_units()]
    for o in out:
        o.pop("trend")
    return sorted(out, key=lambda o: o["recovery_change"])


def rule_effect(unit_id: str, start: str, metric: str = "last_minute_meetings") -> dict:
    """Effet d'une règle : moyennes de l'unité avant / depuis son démarrage."""
    units = reportable_units()
    if unit_id not in units:
        return {"error": f"unité inconnue ou non affichable : {unit_id}"}
    start_week = (date.fromisoformat(str(start)) - start_monday()).days // 7
    weeks_since = WEEKS - start_week
    if weeks_since < 2:
        return {"unit_id": unit_id, "verdict": "trop tôt", "weeks_since": max(0, weeks_since),
                "note": "au moins 2 semaines de recul nécessaires"}
    rows = _rows(units[unit_id]["teams"])
    before = [m for _, _, w, m in rows if start_week - 3 <= w < start_week]
    after = [m for _, _, w, m in rows if w >= start_week]
    rb, ra = mean(m["recovery"] for m in before), mean(m["recovery"] for m in after)
    lb, la = mean(m[metric] for m in before), mean(m[metric] for m in after)
    return {
        "unit_id": unit_id, "weeks_since": weeks_since,
        "recovery_before": round(rb), "recovery_after": round(ra), "recovery_change": round(ra - rb),
        "cause_metric": LOAD.get(metric, metric), "cause_change": f"{(la - lb) / lb:+.0%}".replace("%", " %"),
        "verdict": "efficace" if ra - rb >= 3 else "sans effet net",
    }
