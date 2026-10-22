"""Remplit les 7 colonnes de travail de la base Whoop propre, en cohérence avec la santé.

    python -m data.simulate_daily     # lit data/raw/whoop_daily_clean.json → data/raw/ichane_daily.json/.csv

Formules (validées avec Boss le 2026-10-22) :
- facteur du jour, tiré uniformément : semaine U(0,8 ; 1,2), samedi U(−0,3 ; 0,2), dimanche U(−0,35 ; 0,15) ;
  sous 0 = journée off (≈ 60 % des samedis, ≈ 70 % des dimanches) ;
- charge = facteur × (1 + 0,3 × écart de récup du lendemain), écart = −z-score de la récupération D+1 ;
- colonnes = valeurs habituelles de l'équipe × charge, puis chaque colonne × U(1 − δ ; 1 + δ).
Les mails et réunions de nuit (19h → 6h) et les réunions de dernière minute sont une part du jour
qui grimpe avec la charge.
"""
import argparse
import json
import random
import statistics as st
from datetime import date

from data.check_whoop import RAW, write_csv

# Jour de semaine « normal » de chaque équipe. delta = variance (± en proportion).
TEAMS = {
    "finance":   {"meetings": 6, "emails_received": 110, "night": 0.15, "last_minute": 0.25, "delta": 0.35},
    "conseil":   {"meetings": 5, "emails_received": 80, "night": 0.10, "last_minute": 0.20, "delta": 0.25},
    "juridique": {"meetings": 3, "emails_received": 60, "night": 0.06, "last_minute": 0.10, "delta": 0.15},
    "ops":       {"meetings": 2, "emails_received": 40, "night": 0.03, "last_minute": 0.08, "delta": 0.10},
}
DAY_RANGE = {5: (-0.3, 0.2), 6: (-0.35, 0.15)}  # samedi, dimanche ; sinon semaine
WEEKDAY_RANGE = (0.8, 1.2)
DROP = ("source", "imputed")  # inutiles dans la base finale (gardés dans whoop_daily_clean)
RECOVERY_WEIGHT = 0.3   # 1 écart-type de récup en moins le lendemain → +30 % de charge
SENT_RATIO = 0.4        # mails envoyés ≈ 40 % des reçus
MEETING_H = 0.75        # durée moyenne d'une réunion
MAX_MEETING_H = 11


def day_factor(d: date, rng: random.Random) -> float:
    lo, hi = DAY_RANGE.get(d.weekday(), WEEKDAY_RANGE)
    return max(0.0, rng.uniform(lo, hi))


def simulate(rows: list[dict], team: str = "finance", seed: int = 42) -> list[dict]:
    p, rng = TEAMS[team], random.Random(seed)
    rec = [r["recovery"] for r in rows if r.get("recovery") is not None]
    mean, sd = st.mean(rec), (st.stdev(rec) if len(rec) > 1 else 1) or 1
    jitter = lambda v: v * rng.uniform(1 - p["delta"], 1 + p["delta"])  # noqa: E731
    out = []
    for i, r in enumerate(rows):
        nxt = rows[i + 1].get("recovery") if i + 1 < len(rows) else None
        z = 0.0 if nxt is None else max(-2.5, min(2.5, (nxt - mean) / sd))
        load = day_factor(date.fromisoformat(r["date"]), rng) * (1 + RECOVERY_WEIGHT * -z)
        n_meet = round(jitter(p["meetings"] * load))
        received = round(jitter(p["emails_received"] * load))
        sent = round(jitter(received * SENT_RATIO))
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
    rows = json.loads((RAW / "whoop_daily_clean.json").read_text())
    rows = simulate(sorted(rows, key=lambda r: r["date"]), a.team, a.seed)
    (RAW / "ichane_daily.json").write_text(json.dumps(rows, indent=1))
    write_csv(rows, RAW / "ichane_daily.csv", drop=DROP)
    print("\n".join(summary(rows)))
    print("\n→ data/raw/ichane_daily.csv (ouvre-le dans Excel) et .json")
