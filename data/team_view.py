"""Vue RH : agrégats anonymes par équipe, calculés sur la cohorte de data/simulate.py.

C'est la seule porte d'entrée des agents d'équipe vers les données (via contracts.py).
Confidentialité (CLAUDE.md §3), appliquée ici et pas dans les agents :
- aucune fonction publique ne renvoie de donnée individuelle ;
- une équipe de moins de 8 personnes est masquée. Elle n'est pas non plus fondue dans
  un total plus large, sinon on la retrouverait par différence (Restructuring, 4 personnes) ;
- valeurs lissées : moyennes arrondies, parts qualitatives, effectifs en tranches.

Source : table ClickHouse `daily_base` (5 équipes) si CLICKHOUSE_URL est défini, avec le
seuil n >= 8 dans la requête SQL ; sinon (tests, local) la cohorte pandas de data/simulate.py.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd

from data import simulate as sim

log = logging.getLogger(__name__)

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


def _pd_reportable_units() -> dict[str, dict]:
    df = _weekly()
    sizes = df.groupby("team_id")["user_id"].nunique()
    names = df.drop_duplicates("team_id").set_index("team_id")["team_name"]
    return {t: {"name": names[t], "size": int(n)} for t, n in sizes.items() if n >= MIN_GROUP}


def _pd_team_trends(team_id: str) -> dict:
    df = _weekly()
    if team_id not in set(df["team_id"]):
        return {"error": f"équipe inconnue : {team_id}"}
    units = _pd_reportable_units()
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


def _pd_company_overview() -> list[dict]:
    out = []
    for t in _pd_reportable_units():
        row = _pd_team_trends(t)
        row.pop("trend")
        out.append(row)
    return sorted(out, key=lambda o: o["recovery_change"])


def _pd_rule_effect(team_id: str, start: str, metric: str = "last_minute_meetings") -> dict:
    if team_id not in _pd_reportable_units():
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


# --- ClickHouse : table daily_base (5 équipes de data/simulate_daily.py) -------------------
# Le seuil n >= 8 est dans chaque requête (HAVING uniqExact(user_id) >= 8) : une équipe trop
# petite ne sort jamais de ClickHouse. Seuls des agrégats par équipe sont lus.

TEAM_NAMES = {"top_management": "Top management", "finance": "Finance", "sales": "Sales",
              "rh": "RH", "it": "IT"}
LOAD_CH = {
    "last_minute_meetings": "réunions ajoutées le jour même",
    "emails_received_night": "mails reçus la nuit",
    "n_meetings": "nombre de réunions",
}
SEED_RULE_CH = {"team_id": "finance", "rule_text": "Pas d'ajout de réunion le jour même après 17h",
                "days_ago": 27}
REF = "(SELECT max(date) FROM daily_base)"   # dernier jour des données = « aujourd'hui »
WEEKS_AGO = f"intDiv(dateDiff('day', date, {REF}), 7)"

SQL_WEEKLY = f"""
SELECT team_id, {WEEKS_AGO} AS weeks_ago, toString({REF} - weeks_ago * 7) AS week_end,
       avg(recovery) AS recovery, {', '.join(f'avg({k}) AS {k}' for k in LOAD_CH)},
       uniqExact(user_id) AS n
FROM daily_base
WHERE {WEEKS_AGO} < {WEEKS}
GROUP BY team_id, weeks_ago
HAVING n >= {MIN_GROUP}
ORDER BY team_id, weeks_ago DESC
"""

# Part de l'équipe dont la récupération des 3 dernières semaines est < 90 % de celle des semaines -8 à -5.
# Le détail par personne reste dans la sous-requête : seul le total par équipe sort.
SQL_SHARE = f"""
SELECT team_id, avg(after < 0.9 * before) AS share, count() AS n
FROM (
    SELECT team_id, user_id,
           avgIf(recovery, {WEEKS_AGO} BETWEEN {EARLY.start} AND {EARLY.stop - 1}) AS before,
           avgIf(recovery, {WEEKS_AGO} BETWEEN {LATE.start} AND {LATE.stop - 1}) AS after
    FROM daily_base
    GROUP BY team_id, user_id
    HAVING isFinite(before) AND isFinite(after)
)
GROUP BY team_id
HAVING n >= {MIN_GROUP}
"""

SQL_RULE = f"""
SELECT dateDiff('day', toDate({{start:String}}), {REF}) AS days_since,
       avgIf(recovery, date >= toDate({{start:String}})) AS ra,
       avgIf(recovery, date < toDate({{start:String}})) AS rb,
       avgIf({{metric}}, date >= toDate({{start:String}})) AS ma,
       avgIf({{metric}}, date < toDate({{start:String}})) AS mb,
       uniqExact(user_id) AS n
FROM daily_base
WHERE team_id = {{team:String}} AND date >= toDate({{start:String}}) - 21
GROUP BY team_id
HAVING n >= {MIN_GROUP}
"""


def _use_clickhouse() -> bool:
    import os

    return bool(os.getenv("CLICKHOUSE_URL"))


def _ch_query(sql: str, params: dict | None = None) -> list[dict]:
    import os

    import clickhouse_connect

    url = os.environ["CLICKHOUSE_URL"]
    client = clickhouse_connect.get_client(dsn=url, secure=url.startswith("https"), connect_timeout=10)
    q = client.query(sql, parameters=params or {})
    return [dict(zip(q.column_names, r)) for r in q.result_rows]


@lru_cache(maxsize=1)
def _ch_data() -> dict:
    """Agrégats par équipe (déjà filtrés n >= 8 par ClickHouse), lus une fois puis gardés en mémoire."""
    weekly = _ch_query(SQL_WEEKLY)
    share = {r["team_id"]: r for r in _ch_query(SQL_SHARE)}
    teams: dict[str, list[dict]] = {}
    for r in weekly:
        teams.setdefault(r["team_id"], []).append(r)
    return {"weekly": teams, "share": share}


def _ch_team_trends(team_id: str) -> dict:
    data = _ch_data()
    weeks = data["weekly"].get(team_id)
    if not weeks or team_id not in data["share"]:
        return {"insufficient_group": True}   # inconnue ou < 8 : ClickHouse n'a rien renvoyé
    early = [w for w in weeks if w["weeks_ago"] in EARLY]
    late = [w for w in weeks if w["weeks_ago"] in LATE]
    mean = lambda rows, k: sum(r[k] for r in rows) / len(rows) if rows else 0   # noqa: E731
    changes = {k: (mean(late, k) - mean(early, k)) / mean(early, k) if mean(early, k) else 0 for k in LOAD_CH}
    top = max(changes, key=changes.get)
    n = max(w["n"] for w in weeks)
    return {
        "unit_id": team_id, "team": TEAM_NAMES.get(team_id, team_id), "n_bucket": _bucket(n),
        "share_in_debt": _share_label(float(data["share"][team_id]["share"])),
        "top_cause": LOAD_CH[top] if changes[top] > 0.1 else "aucune cause nette",
        "cause_change": _pct(mean(late, top), mean(early, top)),
        "recovery_change": round(mean(late, "recovery") - mean(early, "recovery")),
        "trend": [{"week": "{}-W{:02d}".format(*date.fromisoformat(w["week_end"]).isocalendar()[:2]),
                   "avg_recovery": round(w["recovery"])} for w in weeks],
    }


def _ch_rule_effect(team_id: str, start: str, metric: str = "last_minute_meetings") -> dict:
    metric = metric if metric in LOAD_CH else "last_minute_meetings"
    rows = _ch_query(SQL_RULE.replace("{metric}", metric),   # metric vient de LOAD_CH (liste fermée)
                     {"start": str(start)[:10], "team": team_id})
    if not rows:
        return {"error": f"équipe inconnue ou masquée : {team_id}"}
    r = rows[0]
    if r["days_since"] < 14:
        return {"unit_id": team_id, "verdict": "trop tôt", "weeks_since": r["days_since"] // 7,
                "note": "au moins 2 semaines de recul nécessaires"}
    return {
        "unit_id": team_id, "weeks_since": r["days_since"] // 7,
        "recovery_before": round(r["rb"]), "recovery_after": round(r["ra"]),
        "recovery_change": round(r["ra"] - r["rb"]),
        "cause_metric": LOAD_CH[metric], "cause_change": _pct(r["ma"], r["mb"]),
        "verdict": "efficace" if r["ra"] - r["rb"] >= 3 else "sans effet net",
    }


def _ch_ref_date() -> date:
    return date.fromisoformat(str(_ch_query(f"SELECT toString({REF}) AS d")[0]["d"]))


def _try_ch(ch_fn, pd_fn, *args):
    """ClickHouse si CLICKHOUSE_URL est défini ; sinon (ou s'il ne répond pas) la cohorte locale."""
    if _use_clickhouse():
        try:
            return ch_fn(*args)
        except Exception as e:
            log.warning("vue RH : ClickHouse illisible (%s), repli sur la cohorte locale", type(e).__name__)
    return pd_fn(*args)


# --- API publique (contracts.py) -------------------------------------------------------------

def reportable_units() -> dict[str, dict]:
    """Équipes affichables (au moins 8 personnes) : {team_id: {"name", "size"}}."""
    def ch():
        return {t: {"name": TEAM_NAMES.get(t, t), "size": max(w["n"] for w in ws)}
                for t, ws in _ch_data()["weekly"].items() if t in _ch_data()["share"]}
    return _try_ch(ch, _pd_reportable_units)


def team_trends(team_id: str) -> dict:
    """Agrégats d'une équipe ; {"insufficient_group": True} si elle compte moins de 8 personnes."""
    return _try_ch(_ch_team_trends, _pd_team_trends, team_id)


def company_overview() -> list[dict]:
    """Toutes les équipes affichables, de la plus en dérive à la plus stable (sans la courbe)."""
    def ch():
        out = []
        for t in _ch_data()["weekly"]:
            row = _ch_team_trends(t)
            if not row.get("insufficient_group"):
                row.pop("trend")
                out.append(row)
        return sorted(out, key=lambda o: o["recovery_change"])
    return _try_ch(ch, _pd_company_overview)


def rule_effect(team_id: str, start: str, metric: str = "last_minute_meetings") -> dict:
    """Moyennes de l'équipe sur les 3 semaines avant la règle vs depuis la règle."""
    return _try_ch(_ch_rule_effect, _pd_rule_effect, team_id, start, metric)


def seed_rule() -> dict:
    """Règle de démo déjà appliquée (team_id, rule_text, start_date), selon la source des données."""
    def ch():
        return {**SEED_RULE_CH, "start_date": (_ch_ref_date() - timedelta(days=SEED_RULE_CH["days_ago"])).isoformat()}
    return _try_ch(ch, lambda: {**SEED_RULE, "start_date": rule_start_date()})
