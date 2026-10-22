"""Remplit les 7 colonnes de travail à partir de la santé, pour Ichane puis pour une cohorte d'équipes.

    python -m data.simulate_daily     # lit data/raw/whoop_daily_clean.json
                                      # → data/raw/ichane_daily.csv (Ichane seul)
                                      # → data/raw/team_daily.csv (Ichane + cohorte simulée, même période)

Formules (validées avec Boss le 2026-10-22) :
- facteur du jour, tiré uniformément : semaine U(0,8 ; 1,2) ; week-end selon l'équipe (plage qui descend
  sous 0 = journée off, p. ex. Finance samedi U(−0,3 ; 0,2) ≈ 60 % off) ; pas de plage = jamais de week-end ;
- charge = facteur × (1 + 0,3 × écart de récup du lendemain), écart = −z-score de la récupération D+1 ;
- colonnes = valeurs habituelles de l'équipe × charge, puis chaque colonne × U(1 − δ ; 1 + δ).
Les mails de nuit (19h → 6h) et les réunions de dernière minute sont une part du jour qui grimpe avec la charge.

Santé de la cohorte : calée sur les moyennes / écarts-types d'Ichane (rien d'autre n'en sort). Chaque personne
a sa propre moyenne de récup (décalage d'équipe + écart individuel) et sa propre variabilité ; les jours
s'enchaînent (une mauvaise nuit pèse sur la suivante) ; HRV, FC repos, sommeil suivent la récup.
"""
import argparse
import json
import random
import statistics as st
from datetime import date, datetime, timedelta

from data.check_whoop import METRICS, RAW, write_csv

# Jour de semaine « normal » de chaque équipe. delta = variance (± en proportion).
# sat / sun = plage du facteur week-end (None = jamais travaillé). recovery = décalage de récup d'équipe.
TEAMS = {
    "top_management": {"meetings": 8, "emails_received": 140, "sent_ratio": 0.5, "night": 0.20,
                       "last_minute": 0.30, "delta": 0.35, "sat": (-0.1, 0.4), "sun": (-0.2, 0.3),
                       "recovery": -8, "size": 8},
    "finance":        {"meetings": 6, "emails_received": 110, "sent_ratio": 0.4, "night": 0.15,
                       "last_minute": 0.25, "delta": 0.35, "sat": (-0.3, 0.2), "sun": (-0.35, 0.15),
                       "recovery": -5, "size": 8},
    "sales":          {"meetings": 7, "emails_received": 130, "sent_ratio": 0.35, "night": 0.03,
                       "last_minute": 0.20, "delta": 0.25, "sat": None, "sun": None,
                       "recovery": -2, "size": 8},
    "rh":             {"meetings": 4, "emails_received": 50, "sent_ratio": 0.4, "night": 0.0,
                       "last_minute": 0.10, "delta": 0.15, "sat": None, "sun": None,
                       "recovery": 4, "size": 8},
    "it":             {"meetings": 3, "emails_received": 40, "sent_ratio": 0.3, "night": 0.0,
                       "last_minute": 0.08, "delta": 0.10, "sat": None, "sun": None,
                       "recovery": 6, "size": 8},
}
MIN_GROUP = 8           # seuil de la vue RH (CLAUDE.md §3) : une équipe plus petite y est masquée
WEEKDAY_RANGE = (0.8, 1.2)
DROP = ("source", "imputed")  # inutiles dans la base finale (gardés dans whoop_daily_clean)
RECOVERY_WEIGHT = 0.3   # 1 écart-type de récup en moins le lendemain → +30 % de charge
MEETING_H = 0.75        # durée moyenne d'une réunion
MAX_MEETING_H = 11


def day_factor(d: date, team: dict, rng: random.Random) -> float:
    rng_range = {5: team["sat"], 6: team["sun"]}.get(d.weekday(), WEEKDAY_RANGE)
    return 0.0 if rng_range is None else max(0.0, rng.uniform(*rng_range))


def simulate(rows: list[dict], team: str = "finance", seed: int = 42) -> list[dict]:
    p, rng = TEAMS[team], random.Random(seed)
    rec = [r["recovery"] for r in rows if r.get("recovery") is not None]
    mean, sd = st.mean(rec), (st.stdev(rec) if len(rec) > 1 else 1) or 1
    jitter = lambda v: v * rng.uniform(1 - p["delta"], 1 + p["delta"])  # noqa: E731
    out = []
    for i, r in enumerate(rows):
        nxt = rows[i + 1].get("recovery") if i + 1 < len(rows) else None
        z = 0.0 if nxt is None else max(-2.5, min(2.5, (nxt - mean) / sd))
        load = day_factor(date.fromisoformat(r["date"]), p, rng) * (1 + RECOVERY_WEIGHT * -z)
        n_meet = round(jitter(p["meetings"] * load))
        received = round(jitter(p["emails_received"] * load))
        sent = round(jitter(received * p["sent_ratio"]))
        night = min(0.6, p["night"] * load)
        out.append({**{k: v for k, v in r.items() if k not in DROP}, "team_id": team,
                    "n_meetings": n_meet,
                    "meeting_hours": round(min(MAX_MEETING_H, jitter(n_meet * MEETING_H)) * 4) / 4,
                    "emails_received": received,
                    "emails_sent": sent,
                    "emails_received_night": min(received, round(jitter(received * night))),
                    "emails_sent_night": min(sent, round(jitter(sent * night))),
                    "last_minute_meetings": min(n_meet, round(jitter(n_meet * min(0.8, p["last_minute"] * load))))})
    return out


def _stats(rows: list[dict], k: str) -> tuple[float, float]:
    v = [r[k] for r in rows if r.get(k) is not None]
    return st.mean(v), (st.stdev(v) if len(v) > 1 else 1.0) or 1.0


def _bed_hour(b: str, d: str) -> float:
    """Heure de coucher en heures depuis minuit la veille (23:30 → 23.5, 01:00 → 25)."""
    return (datetime.fromisoformat(b) - datetime.fromisoformat(d) + timedelta(days=1)).total_seconds() / 3600


def simulate_health(base: list[dict], user_id: str, team: str, rng: random.Random) -> list[dict]:
    """Santé d'une personne fictive sur les mêmes dates qu'Ichane, calée sur ses moyennes."""
    p = TEAMS[team]
    stat = {k: _stats(base, k) for k in METRICS}
    beds = [_bed_hour(r["bedtime"], r["date"]) for r in base if r.get("bedtime")]
    rec_mu = stat["recovery"][0] + p["recovery"] + rng.uniform(-6, 6)
    rec_sd = stat["recovery"][1] * rng.uniform(0.8, 1.2)
    mu = {"hrv": stat["hrv"][0] * rng.uniform(0.7, 1.3), "rhr": stat["rhr"][0] + rng.uniform(-6, 6),
          "sleep_h": stat["sleep_h"][0] + rng.uniform(-0.7, 0.5),
          "sleep_consistency": stat["sleep_consistency"][0] + rng.uniform(-10, 10),
          "strain": stat["strain"][0] + rng.uniform(-2, 2),
          "bed": (st.mean(beds) if beds else 24) + rng.uniform(-1, 1)}
    noise = lambda k, f=0.4: rng.gauss(0, stat[k][1] * f)  # noqa: E731
    clip = lambda v, lo, hi: max(lo, min(hi, v))  # noqa: E731
    out, z = [], 0.0
    for r in base:
        z = 0.5 * z + 0.87 * rng.gauss(0, 1)  # une mauvaise nuit pèse un peu sur la suivante
        bed = mu["bed"] - 0.3 * z + rng.gauss(0, 0.5)
        out.append({"user_id": user_id, "team_id": team, "date": r["date"],
                    "recovery": round(clip(rec_mu + rec_sd * z, 1, 99)),
                    "hrv": round(clip(mu["hrv"] + 0.7 * stat["hrv"][1] * z + noise("hrv"), 5, 250), 1),
                    "rhr": round(clip(mu["rhr"] - 0.6 * stat["rhr"][1] * z + noise("rhr"), 35, 100)),
                    "sleep_h": round(clip(mu["sleep_h"] + 0.5 * stat["sleep_h"][1] * z + noise("sleep_h"), 3, 11), 2),
                    "sleep_consistency": round(clip(mu["sleep_consistency"] + 0.4 * stat["sleep_consistency"][1] * z
                                                    + noise("sleep_consistency"), 0, 100)),
                    "strain": round(clip(mu["strain"] + noise("strain", 1), 0, 21), 1),
                    "bedtime": (datetime.fromisoformat(r["date"]) - timedelta(days=1)
                                + timedelta(hours=bed)).isoformat(timespec="minutes")})
    return out


def simulate_cohort(ichane: list[dict], seed: int = 42) -> list[dict]:
    """Ichane (Finance, vraie santé) + les autres salariés des 5 équipes, même période."""
    rng, rows = random.Random(seed), []
    for team, p in TEAMS.items():
        n_fake = p["size"] - (team == "finance")  # Ichane compte dans Finance
        if team == "finance":
            rows += simulate(ichane, team, seed)
        for k in range(1, n_fake + 1):
            uid = f"{team}_{k:02d}"
            rows += simulate(simulate_health(ichane, uid, team, rng), team, rng.randrange(10**9))
    return rows


def team_summary(rows: list[dict]) -> list[str]:
    lines = [f"{'équipe':15s} {'n':>3s} {'récup':>6s} {'h réu':>6s} {'mails':>6s} {'nuit':>5s} "
             f"{'der.min':>7s} {'WE off':>7s}   (moyennes en semaine)"]
    for team in TEAMS:
        rs = [r for r in rows if r["team_id"] == team]
        wk = [r for r in rs if date.fromisoformat(r["date"]).weekday() < 5]
        we = [r for r in rs if date.fromisoformat(r["date"]).weekday() >= 5]
        n = len({r["user_id"] for r in rs})
        m = lambda k: st.mean(r[k] for r in wk)  # noqa: E731
        off = sum(r["n_meetings"] == 0 and r["emails_received"] == 0 for r in we) / max(1, len(we))
        lines.append(f"{team:15s} {n:3d} {st.mean(r['recovery'] for r in rs):6.0f} {m('meeting_hours'):6.1f} "
                     f"{m('emails_received'):6.0f} {m('emails_received_night'):5.1f} "
                     f"{m('last_minute_meetings'):7.1f} {off:6.0%}" + ("  ← masquée (n < 8)" if n < MIN_GROUP else ""))
    return lines


def summary(rows: list[dict]) -> list[str]:
    week = [r for r in rows if date.fromisoformat(r["date"]).weekday() < 5]
    wkend = [r for r in rows if date.fromisoformat(r["date"]).weekday() >= 5]
    avg = lambda rs, k: st.mean(r[k] for r in rs) if rs else 0  # noqa: E731
    lines = [f"{len(rows)} jours ({len(week)} en semaine, {len(wkend)} de week-end, "
             f"dont {sum(r['n_meetings'] == 0 and r['emails_received'] == 0 for r in wkend)} off)",
             "Moyenne en semaine :"]
    for k in ["n_meetings", "meeting_hours", "emails_received", "emails_sent",
              "emails_received_night", "emails_sent_night", "last_minute_meetings"]:
        lines.append(f"  {k:22s} {avg(week, k):6.1f}   (week-end {avg(wkend, k):5.1f})")
    pairs = [(rows[i]["meeting_hours"], rows[i + 1]["recovery"]) for i in range(len(rows) - 1)
             if rows[i + 1].get("recovery") is not None]
    if len(pairs) > 2:
        lines.append(f"Lien heures de réunion (J) ↔ récup (J+1) : corrélation "
                     f"{st.correlation(*zip(*pairs)):+.2f} (négatif attendu)")
    return lines


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="finance", choices=TEAMS)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    base = sorted(json.loads((RAW / "whoop_daily_clean.json").read_text()), key=lambda r: r["date"])
    rows = simulate(base, a.team, a.seed)
    (RAW / "ichane_daily.json").write_text(json.dumps(rows, indent=1))
    write_csv(rows, RAW / "ichane_daily.csv", drop=DROP)
    print("\n".join(summary(rows)))
    cohort = simulate_cohort(base, a.seed)
    (RAW / "team_daily.json").write_text(json.dumps(cohort, indent=1))
    write_csv(cohort, RAW / "team_daily.csv", drop=DROP)
    print("\nÉquipes :\n" + "\n".join(team_summary(cohort)))
    print("\n→ data/raw/ichane_daily.csv (toi seul) et data/raw/team_daily.csv (40 salariés), à ouvrir dans Excel")
