"""Vue RH : agrégats anonymes par équipe, calculés sur la cohorte de data/simulate.py.

C'est la seule porte d'entrée des agents d'équipe vers les données (via contracts.py).
Confidentialité (CLAUDE.md §3), appliquée ici et pas dans les agents :
- aucune fonction publique ne renvoie de donnée individuelle ;
- une équipe de moins de 8 personnes est masquée. Elle n'est pas non plus fondue dans
  un total plus large, sinon on la retrouverait par différence (Restructuring, 4 personnes) ;
- valeurs lissées : moyennes arrondies, parts qualitatives, effectifs en tranches.

Aujourd'hui en pandas sur la cohorte simulée ; à remplacer par les mêmes agrégats en
SQL ClickHouse (avec HAVING count() >= 8) sans changer les sorties.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import pandas as pd

from data import simulate as sim

MIN_GROUP = 8
WEEKS = 8
EARLY = range(4, 8)   # semaines -8 à -5 : la base de l'équipe
LATE = range(0, 3)    # 3 dernières semaines

LOAD = {
    "last_minute_meetings": "réunions ajoutées le jour même",
    "late_meetings": "réunions en dehors des horaires",
    "meetings": "nombre de réunions",
}

# Règle déjà appliquée dans la cohorte (data/simulate.py, team_context) : sert à la démo
# de la boucle d'apprentissage (l'agent Mesure en calcule l'effet).
SEED_RULE = {"team_id": "conseil", "rule_text": "Pas d'ajout de réunion le jour même après 17h",
             "days_ago": 27}


def rule_start_date() -> str:
    return (date.today() - timedelta(days=SEED_RULE["days_ago"])).isoformat()


@lru_cache(maxsize=1)
def _weekly() -> pd.DataFrame:
    """Une ligne par personne et par semaine (privé à ce module)."""
    d = sim.simulate()
    today = pd.Timestamp(date.today())

    w = d["work_events"]
    m = w[w["kind"] == "meeting"].copy()
    m["weeks_ago"] = (today - m["ts"].dt.normalize()).dt.days // 7
    m["last_minute"] = (m["ts"] - m["created_ts"]).dt.total_seconds().lt(24 * 3600) & m["created_ts"].notna()
    m = m[(m["weeks_ago"] >= 0) & (m["weeks_ago"] < WEEKS)]
    load = m.groupby(["team_id", "user_id", "weeks_ago"]).agg(
        meetings=("ts", "size"), last_minute_meetings=("last_minute", "sum"),
        late_meetings=("is_after_hours", "sum")).reset_index()

    r = d["recovery_daily"].copy()
    r["weeks_ago"] = (today - pd.to_datetime(r["date"])).dt.days // 7
    r = r[(r["weeks_ago"] >= 0) & (r["weeks_ago"] < WEEKS)]
    rec = r.groupby(["team_id", "user_id", "weeks_ago"])["recovery"].mean().rename("recovery").reset_index()

    out = rec.merge(load, on=["team_id", "user_id", "weeks_ago"], how="left").fillna(0)
    names = dict(zip(d["users"]["team_id"], d["users"]["team_name"]))
    out["team_name"] = out["team_id"].map(names)
    return out


def _bucket(n: int) -> str:
    """Effectif en tranche, sans jamais suggérer un groupe sous le seuil."""
    return "8-12" if n < 12 else "12-20" if n < 20 else "20+"


def _share_label(share: float) -> str:
    return "minorité" if share < 0.35 else "environ la moitié" if share <= 0.65 else "majorité"


def _week_label(weeks_ago: int) -> str:
    y, w, _ = (date.today() - timedelta(weeks=weeks_ago)).isocalendar()
    return f"{y}-W{w:02d}"


def _pct(a: float, b: float) -> str:
    return f"{(a - b) / b:+.0%}".replace("%", " %") if b else "n/a"


def reportable_units() -> dict[str, dict]:
    df = _weekly()
    sizes = df.groupby("team_id")["user_id"].nunique()
    names = df.drop_duplicates("team_id").set_index("team_id")["team_name"]
    return {t: {"name": names[t], "size": int(n)} for t, n in sizes.items() if n >= MIN_GROUP}


def team_trends(team_id: str) -> dict:
    """Agrégats d'une équipe ; {"insufficient_group": True} si elle compte moins de 8 personnes."""
    df = _weekly()
    if team_id not in set(df["team_id"]):
        return {"error": f"équipe inconnue : {team_id}"}
    units = reportable_units()
    if team_id not in units:
        return {"insufficient_group": True}
    t = df[df["team_id"] == team_id]
    by_week = t.groupby("weeks_ago")
    trend = [{"week": _week_label(w), "avg_recovery": round(by_week.get_group(w)["recovery"].mean())}
             for w in sorted(by_week.groups, reverse=True)]

    early, late = t[t["weeks_ago"].isin(EARLY)], t[t["weeks_ago"].isin(LATE)]
    person = pd.DataFrame({"before": early.groupby("user_id")["recovery"].mean(),
                           "after": late.groupby("user_id")["recovery"].mean()}).dropna()
    share = float((person["after"] < 0.9 * person["before"]).mean())

    changes = {k: (late[k].mean() - early[k].mean()) / early[k].mean() if early[k].mean() else 0 for k in LOAD}
    top = max(changes, key=changes.get)
    return {
        "unit_id": team_id, "team": units[team_id]["name"], "n_bucket": _bucket(units[team_id]["size"]),
        "share_in_debt": _share_label(share),
        "top_cause": LOAD[top] if changes[top] > 0.1 else "aucune cause nette",
        "cause_change": _pct(late[top].mean(), early[top].mean()),
        "recovery_change": round(late["recovery"].mean() - early["recovery"].mean()),
        "trend": trend,
    }


def company_overview() -> list[dict]:
    """Toutes les équipes affichables, de la plus en dérive à la plus stable (sans la courbe)."""
    out = []
    for t in reportable_units():
        row = team_trends(t)
        row.pop("trend")
        out.append(row)
    return sorted(out, key=lambda o: o["recovery_change"])


def rule_effect(team_id: str, start: str, metric: str = "last_minute_meetings") -> dict:
    """Moyennes de l'équipe sur les 3 semaines avant la règle vs depuis la règle."""
    if team_id not in reportable_units():
        return {"error": f"équipe inconnue ou masquée : {team_id}"}
    days_since = (date.today() - date.fromisoformat(str(start)[:10])).days
    if days_since < 14:
        return {"unit_id": team_id, "verdict": "trop tôt", "weeks_since": days_since // 7,
                "note": "au moins 2 semaines de recul nécessaires"}
    t = _weekly()[lambda x: x["team_id"] == team_id]
    split = days_since // 7          # semaines écoulées depuis la règle
    after = t[t["weeks_ago"] <= split]
    before = t[(t["weeks_ago"] > split) & (t["weeks_ago"] <= split + 3)]
    rb, ra = before["recovery"].mean(), after["recovery"].mean()
    return {
        "unit_id": team_id, "weeks_since": split,
        "recovery_before": round(rb), "recovery_after": round(ra), "recovery_change": round(ra - rb),
        "cause_metric": LOAD.get(metric, metric),
        "cause_change": _pct(after[metric].mean(), before[metric].mean()),
        "verdict": "efficace" if ra - rb >= 3 else "sans effet net",
    }
