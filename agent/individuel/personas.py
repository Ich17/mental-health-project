"""⚠️ PROFILS SIMULÉS pour la démo et les tests, aucune personne réelle.

Le profil par défaut est celui de contracts.py (`persona_demo`) : deux semaines de
charge en hausse qui ne redescendent pas → une vraie dérive.

`closing` : le cas du faux positif. Une semaine de clôture trimestrielle très chargée
il y a deux semaines, puis retour à la normale : les agents ne doivent pas alerter.

    python -m agent.individuel.cli --scripted --persona closing
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import contracts


def closing_metrics(user_id: str, days: int = 42) -> list[dict]:
    rng = random.Random(7)
    today = date.today()
    rows = []
    for i in range(42, 0, -1):
        d = today - timedelta(days=i)
        weekend = d.weekday() >= 5
        closing = 8 <= i <= 14 and not weekend          # la semaine S-2, jours ouvrés
        mh = 0.5 if weekend else max(0.5, rng.gauss(9.0 if closing else 4.2, 0.8))
        lm = 0 if weekend else rng.choice([3, 3, 4] if closing else [0, 0, 1, 1])
        late = 0 if weekend else rng.choice([2, 3, 3] if closing else [0, 0, 0, 1])
        rec = 70 - 2.2 * mh - 3.5 * lm - 4.5 * late + rng.gauss(0, 4)
        rows.append({
            "date": d.isoformat(),
            "meeting_hours": round(mh, 1),
            "last_minute_meetings": lm,
            "meetings_after_20h": late,
            "emails_in": int(rng.gauss(30 if weekend else (110 if closing else 60), 8)),
            "green_hours": round(1.0 if weekend else rng.gauss(12 if closing else 9.0, 0.6), 1),
            "recovery": int(max(15, min(95, rec))),
            "hrv": int(max(25, rec * 0.55 + rng.gauss(18, 3))),
            "sleep_h": round(max(4.5, 8.1 - 0.12 * mh - 0.25 * late + rng.gauss(0, 0.3)), 1),
            "context": "cloture_trimestrielle" if closing else None,
        })
    return rows[-days:]


def closing_forecast(user_id: str) -> list[dict]:
    """Semaine à venir normale : rien de rouge."""
    weekdays = [(62, "journée légère"), (55, "5h de réunions"), (48, "6h de réunions"),
                (58, "4h de réunions"), (64, "journée légère")]
    out, k = [], 0
    for i in range(1, 8):
        d = date.today() + timedelta(days=i)
        if d.weekday() >= 5:
            rec, reason = 70, "week-end"
        else:
            rec, reason = weekdays[k % len(weekdays)]
            k += 1
        risk = "rouge" if rec < 35 else "orange" if rec < 50 else "vert"
        out.append({"date": d.isoformat(), "predicted_recovery": rec, "risk": risk, "reason": reason})
    return out


PERSONAS = {"closing": {"get_daily_metrics": closing_metrics, "forecast_week": closing_forecast}}


def use_persona(name: str) -> None:
    """Remplace les fonctions de contracts.py par celles du profil, pour ce processus (CLI de démo)."""
    for fn_name, fn in PERSONAS[name].items():
        setattr(contracts, fn_name, fn)
