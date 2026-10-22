"""Simulateur : ~50 juniors fictifs (agenda + mails + présence + récupération WHOOP).

Pourquoi : la vue RH a besoin d'équipes de 8+ personnes, et l'agent a besoin d'un profil de
secours (`persona_demo`) si les vraies données ne montrent rien de net.

Modèle (volontairement simple, mais réaliste) :
- chaque équipe a son rythme (réunions, mails, week-ends) et ses périodes de rush ;
- chaque personne a SA baseline (récupération, HRV, FC repos, sommeil) et SES sensibilités :
  pour l'un ce sont les calls ajoutés le jour même, pour l'autre les réunions après 20h ;
- la récupération de J+1 = baseline − effet de la charge de J − dette accumulée + bruit ;
- histoires pour la démo : l'équipe M&A se dégrade sur les 3 dernières semaines (réunions
  ajoutées après 18h, +40 %), l'équipe Conseil applique une règle (« pas d'ajout le jour même
  après 17h ») depuis 4 semaines et récupère mieux ; l'équipe Restructuring a < 8 personnes
  (pour montrer le refus « groupe trop petit »).

Calibrage : `--calibrate data/raw/whoop_daily.json` (ou le résumé `whoop_calibration.json`
produit par `python -m data.calibrate`) recentre les niveaux (moyennes, variabilité,
effet du jour de la semaine) sur de vraies données WHOOP. Sinon : fourchettes WHOOP plausibles.

    python -m data.simulate                       # → data/sim_out/*.csv (ignoré par git)
    python -m data.simulate --calibrate data/raw/whoop_daily.json
    python -m data.simulate --clickhouse          # charge aussi dans ClickHouse (CLICKHOUSE_URL)

Jamais de contenu : aucun titre, aucun texte, seulement des horaires et des comptes.
"""
import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from data.calibrate import calibrate

OUT = Path(__file__).resolve().parent / "sim_out"

# team_id: (nom affiché, effectif, réunions/jour, mails/jour, travail le week-end 0..1, part externe)
TEAMS = {
    "ma":      ("M&A",               14, 6.5, 85, 0.45, 0.35),
    "pe":      ("Private Equity",    12, 5.5, 70, 0.35, 0.45),
    "conseil": ("Conseil Stratégie", 12, 6.0, 60, 0.15, 0.50),
    "levfin":  ("Leveraged Finance",  8, 5.5, 75, 0.35, 0.30),
    "restru":  ("Restructuring",      4, 6.0, 80, 0.40, 0.40),  # < 8 : jamais affiché seul
}

# Fourchettes WHOOP plausibles (adultes 22-30 ans), remplacées par --calibrate.
DEFAULT_CAL = {
    "recovery_mean": 58.0, "recovery_sd": 17.0,
    "hrv_median": 58.0, "rhr_mean": 57.0, "rhr_sd": 2.5,
    "sleep_h_mean": 6.9, "sleep_h_sd": 0.75,
    "sleep_consistency_mean": 72.0, "strain_mean": 10.5, "bedtime_h": 23.8,
    "weekday_recovery": [0, 0, 0, 0, 0, 0, 0],  # lundi..dimanche, écart à la moyenne
}

# Effet moyen de chaque indicateur sur la récupération de J+1 (points, par unité).
DRIVERS = {
    "last_minute_meetings": -3.0,    # par call ajouté < 24h avant
    "meetings_after_20h": -4.5,      # par réunion qui commence après 20h
    "meeting_hours": -1.0,           # par heure de réunion
    "emails_in_per20": -0.8,         # par tranche de 20 mails reçus
    "green_hours_over10": -1.5,      # par heure « vert » au-delà de 10h
}
SLEEP_MIN = {"last_minute_meetings": -12, "meetings_after_20h": -20, "green_hours_over10": -8}


@dataclass
class Person:
    user_id: str
    team_id: str
    rec_mu: float
    hrv_mu: float
    rhr_mu: float
    sleep_mu: float
    consistency_mu: float
    bedtime_h: float
    noise: float
    sens: dict = field(default_factory=dict)  # multiplicateur personnel par driver


# --- Population ---------------------------------------------------------------

def make_people(rng: np.random.Generator, cal: dict) -> list[Person]:
    people = []
    for team_id, (_, size, *_rest) in TEAMS.items():
        for i in range(size):
            people.append(_person(rng, cal, f"{team_id}_{i + 1:02d}", team_id))
    # Profil de secours : effets nets et peu de bruit, sensible aux calls de dernière minute.
    demo = _person(rng, cal, "persona_demo", "ma")
    demo.rec_mu, demo.sleep_mu, demo.noise = cal["recovery_mean"] + 4, cal["sleep_h_mean"], 0.45
    demo.sens = {"last_minute_meetings": 2.4, "meetings_after_20h": 1.6, "meeting_hours": 0.6,
                 "emails_in_per20": 0.3, "green_hours_over10": 0.5}
    people.append(demo)
    return people


def _person(rng, cal, user_id, team_id) -> Person:
    # Une sensibilité dominante par personne → « ce qui épuise CETTE personne » diffère.
    keys = list(DRIVERS)
    sens = {k: float(rng.uniform(0.3, 1.1)) for k in keys}
    sens[keys[rng.integers(len(keys))]] = float(rng.uniform(1.8, 2.6))
    return Person(
        user_id=user_id, team_id=team_id,
        rec_mu=float(np.clip(rng.normal(cal["recovery_mean"] + 6, 7), 35, 80)),
        hrv_mu=float(np.clip(cal["hrv_median"] * rng.lognormal(0, 0.3), 22, 140)),
        rhr_mu=float(np.clip(rng.normal(cal["rhr_mean"], 5), 44, 72)),
        sleep_mu=float(np.clip(rng.normal(cal["sleep_h_mean"] + 0.3, 0.4), 5.8, 8.2)),
        consistency_mu=float(np.clip(rng.normal(cal["sleep_consistency_mean"], 8), 45, 92)),
        bedtime_h=float(rng.normal(cal["bedtime_h"], 0.5)),
        noise=float(rng.uniform(0.8, 1.15)),
        sens=sens,
    )


# --- Agenda / mails / présence -------------------------------------------------

def team_context(team_id: str, day: date, first: date, today: date) -> dict:
    """Paramètres du jour pour une équipe (rush, histoires démo)."""
    week = (day - first).days // 7
    weeks_left = (today - day).days // 7  # 0 = semaine en cours
    late, lastmin = 0.10, 0.22  # part des réunions après 20h / ajoutées < 24h avant
    rush = 1.0
    if team_id == "ma" and weeks_left < 3:  # dégradation récente : ajouts tardifs +40 %
        late, lastmin, rush = 0.15, 0.31, 1.15
    if team_id == "pe" and week in (2, 3):  # un closing
        rush = 1.3
    rule = team_id == "conseil" and weeks_left < 4
    if rule:  # règle d'équipe appliquée : plus d'ajout le jour même après 17h
        late, lastmin = 0.05, 0.12
    return {"late": late, "lastmin": lastmin, "rush": rush, "rule": rule}


def work_day(rng, p: Person, day: date, ctx: dict) -> tuple[list[dict], dict]:
    _, _, m_per_day, mails, weekend, ext = TEAMS[p.team_id]
    wd = day.weekday()
    intensity = ctx["rush"] * (weekend if wd >= 5 else 1.0) * rng.lognormal(0, 0.2)
    base = datetime(day.year, day.month, day.day)
    ev = []
    n = rng.poisson(m_per_day * intensity)
    f = {k: 0.0 for k in ("meeting_hours", "last_minute_meetings", "meetings_after_20h")}
    last_end = base + timedelta(hours=18)
    for _ in range(n):
        late = rng.random() < ctx["late"]
        h = rng.uniform(20, 22.5) if late else rng.uniform(8.5, 19.5)
        start = base + timedelta(hours=round(h * 4) / 4)
        dur = float(rng.choice([0.5, 0.5, 1, 1, 1, 1.5, 2]))
        end = start + timedelta(hours=dur)
        lastmin = rng.random() < ctx["lastmin"] and not (ctx["rule"] and h >= 17)
        created = start - (timedelta(minutes=round(rng.uniform(30, 1200))) if lastmin
                           else timedelta(minutes=round(rng.uniform(1.2, 15) * 1440)))
        status = "cancelled" if rng.random() < 0.05 else "confirmed"
        ev.append({"ts": start, "end_ts": end, "kind": "meeting", "created_ts": created,
                   "n_attendees": int(rng.integers(2, 12)), "is_external": int(rng.random() < ext),
                   "status": status})
        if status == "confirmed":
            f["meeting_hours"] += dur
            f["last_minute_meetings"] += lastmin
            f["meetings_after_20h"] += h >= 20
            last_end = max(last_end, end)

    n_in = rng.poisson(mails * intensity)
    for _ in range(n_in):
        h = rng.uniform(20, 24) if rng.random() < 0.15 * ctx["rush"] else rng.uniform(7.5, 20)
        ev.append(_simple(base, h, "email_in"))
    n_out = rng.poisson(0.35 * mails * intensity)
    late_out = 0
    for _ in range(n_out):
        h = rng.uniform(21, 25) if rng.random() < 0.12 * ctx["rush"] else rng.uniform(8, 21)
        late_out += h >= 21
        ev.append(_simple(base, h, "email_out"))

    green = 0.0
    if n or n_in:
        start = base + timedelta(minutes=round(60 * (rng.normal(8.6, 0.4) + (2 if wd >= 5 else 0))))
        stop = max(last_end, base + timedelta(minutes=round(60 * rng.normal(18 + 2.5 * intensity, 1))))
        if wd >= 5:
            stop = min(stop, start + timedelta(minutes=round(60 * (rng.uniform(1, 6) * intensity + 0.5))))
        green = max(0.0, (stop - start).total_seconds() / 3600)
        ev.append({"ts": start, "end_ts": stop, "kind": "presence_green"})
    f.update({"emails_in": n_in, "emails_out_after_21h": late_out, "green_hours": round(green, 2),
              "emails_in_per20": n_in / 20, "green_hours_over10": max(0.0, green - 10)})
    return ev, f


def _simple(base, h, kind):
    return {"ts": base + timedelta(seconds=round(h * 3600)), "end_ts": None, "kind": kind}


# --- Récupération ----------------------------------------------------------------

def recovery_next(rng, p: Person, f: dict, wd_next: int, debt: float, cal: dict) -> tuple[dict, float]:
    """Récupération du matin J+1 à partir de la charge du jour J."""
    load = sum(DRIVERS[k] * p.sens[k] * f[k] for k in DRIVERS)
    # Centre : une journée « normale » (≈ 5 réunions, 70 mails) ne coûte rien de spécial.
    typical = sum(DRIVERS[k] * p.sens[k] * v for k, v in
                  {"last_minute_meetings": 1.3, "meetings_after_20h": 0.5, "meeting_hours": 5,
                   "emails_in_per20": 3.5, "green_hours_over10": 1}.items())
    sleep_cost = sum(SLEEP_MIN[k] * p.sens[k] * f[k] for k in SLEEP_MIN) / 60
    sleep_h = float(np.clip(p.sleep_mu + sleep_cost + rng.normal(0, cal["sleep_h_sd"] * 0.7), 3.5, 10))
    sleep_dev = sleep_h - p.sleep_mu
    debt = 0.75 * debt + max(0.0, typical - load) * 0.25  # la charge s'accumule sur plusieurs jours
    rec = (p.rec_mu + (load - typical) - debt + 5.5 * sleep_dev + cal["weekday_recovery"][wd_next]
           + rng.normal(0, cal["recovery_sd"] * 0.8 * p.noise))
    rec = float(np.clip(rec, 3, 99))
    z = (rec - p.rec_mu) / 20
    bedtime_h = p.bedtime_h - min(sleep_cost, 0) * 0.6 + rng.normal(0, 0.4)
    row = {
        "recovery": round(rec),
        "hrv": round(float(p.hrv_mu * np.exp(0.22 * z + rng.normal(0, 0.08))), 1),
        "rhr": round(float(p.rhr_mu - 2.5 * z + rng.normal(0, cal["rhr_sd"] * 0.5))),
        "sleep_h": round(sleep_h, 2),
        "sleep_consistency": round(float(np.clip(p.consistency_mu - 6 * f["meetings_after_20h"]
                                                 + rng.normal(0, 7), 20, 99))),
        "bedtime_h": bedtime_h,
        "strain": round(float(np.clip(cal["strain_mean"] + rng.normal(0, 3), 2, 20)), 1),
    }
    return row, debt


# --- Orchestration ------------------------------------------------------------------

def simulate(weeks: int = 8, future_days: int = 14, seed: int = 42, cal: dict | None = None,
             today: date | None = None) -> dict[str, pd.DataFrame]:
    cal = {**DEFAULT_CAL, **{k: v for k, v in (cal or {}).items() if k in DEFAULT_CAL}}
    today = today or date.today()
    first = today - timedelta(days=7 * weeks)
    rng = np.random.default_rng(seed)
    people = make_people(rng, cal)
    events, rec_rows, truth = [], [], {}
    for p in people:
        debt = 0.0
        for i in range((today - first).days + future_days + 1):
            day = first + timedelta(days=i)
            ev, f = work_day(rng, p, day, team_context(p.team_id, day, first, today))
            for e in ev:
                events.append({"user_id": p.user_id, "team_id": p.team_id, "created_ts": None,
                               "n_attendees": 0, "is_external": 0, "status": "confirmed",
                               "source": "sim", **e})
            nxt = day + timedelta(days=1)
            if nxt > today:  # pas de récupération dans le futur, juste l'agenda
                continue
            row, debt = recovery_next(rng, p, f, nxt.weekday(), debt, cal)
            bed = datetime(day.year, day.month, day.day) + timedelta(hours=row.pop("bedtime_h"))
            rec_rows.append({"user_id": p.user_id, "team_id": p.team_id, "date": nxt,
                             "bedtime": bed.replace(second=0, microsecond=0), "source": "sim", **row})
        truth[p.user_id] = {"team_id": p.team_id,
                            "top_driver": max(p.sens, key=p.sens.get),
                            "sensitivity": {k: round(v, 2) for k, v in p.sens.items()}}

    users = pd.DataFrame([{"user_id": p.user_id, "team_id": p.team_id, "team_name": TEAMS[p.team_id][0]}
                          for p in people])
    work = pd.DataFrame(events).sort_values(["user_id", "ts"]).reset_index(drop=True)
    work = _derived(work)[["user_id", "team_id", "ts", "end_ts", "kind", "created_ts", "n_attendees",
                           "is_external", "status", "source", "duration_min", "is_after_hours",
                           "is_weekend"]]
    rec = pd.DataFrame(rec_rows)[["user_id", "team_id", "date", "recovery", "hrv", "rhr", "sleep_h",
                                  "sleep_consistency", "bedtime", "strain", "source"]]
    rule_start = today - timedelta(days=27)  # = team_context : weeks_left < 4
    stories = {
        "ma": "dégradation sur les 3 dernières semaines : réunions ajoutées tardivement +40 %",
        "conseil": f"règle « pas d'ajout le jour même après 17h » depuis le {rule_start}",
        "restru": "4 personnes : doit être masquée dans la vue RH (n < 8)",
    }
    return {"users": users, "work_events": work, "recovery_daily": rec,
            "truth": {"calibration": cal, "stories": stories, "people": truth}}


def _derived(work: pd.DataFrame) -> pd.DataFrame:
    """Mêmes champs dérivés que data/events.make_event (durée, hors horaires, week-end)."""
    from data.events import WORKDAY_END_H, WORKDAY_START_H

    end = pd.to_datetime(work["end_ts"])
    dur = ((end - work["ts"]).dt.total_seconds() // 60).fillna(0).clip(lower=0).astype(int)
    last = (end - pd.Timedelta(minutes=1)).where(end > work["ts"], work["ts"])
    after = ((work["ts"].dt.hour < WORKDAY_START_H) | (work["ts"].dt.hour >= WORKDAY_END_H)
             | (last.dt.hour >= WORKDAY_END_H) | (last.dt.date != work["ts"].dt.date))
    return work.assign(duration_min=dur, is_after_hours=after.astype(int),
                       is_weekend=(work["ts"].dt.weekday >= 5).astype(int))


def save(data: dict, out: Path = OUT) -> None:
    out.mkdir(exist_ok=True)
    for name in ("users", "work_events", "recovery_daily"):
        data[name].to_csv(out / f"{name}.csv", index=False)
    (out / "truth.json").write_text(json.dumps(data["truth"], indent=1, ensure_ascii=False, default=str))


def load_clickhouse(data: dict) -> None:
    """Insère dans les tables de data/clickhouse.sql (créées si besoin)."""
    import os

    import clickhouse_connect
    from dotenv import load_dotenv

    load_dotenv()
    client = clickhouse_connect.get_client(dsn=os.environ["CLICKHOUSE_URL"],
                                          secure=os.environ["CLICKHOUSE_URL"].startswith("https"))
    schema = (Path(__file__).parent / "clickhouse.sql").read_text(encoding="utf-8")
    # On retire les lignes de commentaire AVANT de couper sur « ; » (un commentaire peut en contenir).
    schema = "\n".join(line for line in schema.splitlines() if not line.strip().startswith("--"))
    for sql in (s.strip() for s in schema.split(";")):
        if sql:
            client.command(sql)
    # On ne remplace que la cohorte (ses équipes), pas les données mock de data/simulate_work.py.
    teams = ", ".join(f"'{t}'" for t in TEAMS)
    for table in ("work_events", "recovery_daily"):
        client.command(f"ALTER TABLE {table} DELETE WHERE source = 'sim' AND team_id IN ({teams})")
    for name in ("work_events", "recovery_daily"):
        df = data[name].astype(object).where(data[name].notna(), None)
        client.insert(name, df.values.tolist(), column_names=list(df.columns))
        print(f"ClickHouse : {len(df)} lignes → {name}")


def summary(data: dict) -> str:
    rec, users = data["recovery_daily"], data["users"]
    lines = [f"{len(users)} profils, {len(data['work_events'])} événements, {len(rec)} jours de récupération"]
    for team_id, g in users.groupby("team_id"):
        r = rec[rec.team_id == team_id]
        lines.append(f"  {TEAMS[team_id][0]:18s} n={len(g):2d}  récup moy {r.recovery.mean():4.1f}  "
                     f"(3 dernières sem. {r[r.date >= r.date.max() - timedelta(days=21)].recovery.mean():4.1f})")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Génère la cohorte simulée")
    ap.add_argument("--calibrate", help="data/raw/whoop_daily.json (vraies données) pour recentrer les niveaux")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--clickhouse", action="store_true", help="charge aussi dans ClickHouse")
    a = ap.parse_args()
    cal = calibrate(a.calibrate) if a.calibrate else None
    if cal:
        print("Calibrage :", cal)
    d = simulate(weeks=a.weeks, seed=a.seed, cal=cal)
    save(d)
    print(summary(d))
    print(f"→ {OUT.relative_to(OUT.parent.parent)}/")
    if a.clickhouse:
        load_clickhouse(d)
