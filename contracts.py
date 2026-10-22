"""Interface entre la partie data et la partie agent / API.

Pour l'instant chaque fonction renvoie un mock (exemples du CLAUDE.md §8),
ce qui permet de coder l'agent et le front sans attendre les vraies données.
On remplacera le corps des fonctions par les requêtes ClickHouse ; garder les
signatures stables évite de casser l'autre côté.
"""
import random
from datetime import date, timedelta


def _persona_demo(days: int = 42) -> list[dict]:
    """Profil fictif « persona_demo » : 4 semaines stables, puis 2 semaines de
    charge en hausse (calls ajoutés le jour même, réunions tardives)."""
    rng = random.Random(42)
    today = date.today()
    rows = []
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        heavy = i <= 14                       # les 2 dernières semaines
        weekend = d.weekday() >= 5
        mh = 0.5 if weekend else max(0.5, rng.gauss(6.8 if heavy else 4.2, 1.0))
        lm = 0 if weekend else rng.choice([2, 3, 3, 4] if heavy else [0, 0, 1, 1])
        late = 0 if weekend else rng.choice([1, 2, 2, 3] if heavy else [0, 0, 0, 1])
        rec = 70 - 2.2 * mh - 3.5 * lm - 4.5 * late + rng.gauss(0, 4)
        rows.append({
            "date": d.isoformat(),
            "meeting_hours": round(mh, 1),
            "last_minute_meetings": lm,
            "meetings_after_20h": late,
            "emails_in": int(rng.gauss(30 if weekend else (85 if heavy else 60), 8)),
            "green_hours": round(1.0 if weekend else rng.gauss(10.5 if heavy else 9.0, 0.6), 1),
            "recovery": int(max(15, min(95, rec))),
            "hrv": int(max(25, rec * 0.55 + rng.gauss(18, 3))),
            "sleep_h": round(max(4.5, 8.1 - 0.12 * mh - 0.25 * late + rng.gauss(0, 0.3)), 1),
        })
    return rows


def get_daily_metrics(user_id: str, days: int = 42) -> list[dict]:
    """Indicateurs de charge du jour J + récupération à J+1, un dict par jour."""
    return _persona_demo(42)[-days:]


def get_drivers(user_id: str) -> list[dict]:
    """Top 3 des facteurs qui pèsent sur la récupération de cette personne (hypothèses)."""
    return [
        {"factor": "last_minute_meetings", "label": "Calls ajoutés le jour même",
         "effect": "-25 min de sommeil par call", "effect_size": -0.42, "confidence": "moyenne"},
        {"factor": "meetings_after_20h", "label": "Réunions après 20h",
         "effect": "-6 points de récupération le lendemain", "effect_size": -0.35, "confidence": "moyenne"},
        {"factor": "emails_in", "label": "Volume de mails reçus",
         "effect": "-2 points de récupération par tranche de 20 mails", "effect_size": -0.18, "confidence": "faible"},
    ]


def forecast_week(user_id: str) -> list[dict]:
    """Récupération prévue pour les jours à venir, à partir de l'agenda futur."""
    weekdays = [  # (récupération prévue, raison), dans l'ordre des jours ouvrés à venir
        (47, "6h de réunions"), (28, "4 calls après 20h"), (44, "2 calls ajoutés la veille"),
        (31, "closing : 8h de réunions"), (58, "journée légère"),
    ]
    out, k = [], 0
    for i in range(1, 8):
        d = date.today() + timedelta(days=i)
        if d.weekday() >= 5:
            rec, reason = 68, "week-end"
        else:
            rec, reason = weekdays[k % len(weekdays)]
            k += 1
        risk = "rouge" if rec < 35 else "orange" if rec < 50 else "vert"
        out.append({"date": d.isoformat(), "predicted_recovery": rec, "risk": risk, "reason": reason})
    return out


def get_free_slots(user_id: str, date: str) -> list[dict]:
    """Créneaux libres d'une journée (ISO 8601, heure locale)."""
    return [
        {"start": f"{date}T12:30:00", "end": f"{date}T13:30:00"},
        {"start": f"{date}T18:00:00", "end": f"{date}T19:00:00"},
        {"start": f"{date}T07:30:00", "end": f"{date}T08:30:00"},
    ]


def team_trends(team_id: str) -> dict:
    """Tendances anonymes d'une équipe (ou d'un département).

    Privacy : le seuil n >= 8 est appliqué dans la couche data (data/cohort.py,
    puis la requête ClickHouse), pas ici ni dans l'agent.
    Si le groupe est trop petit, renvoie {"insufficient_group": True, "unit_id": <département>}.
    Exemple : {"unit_id": "ma", "team": "M&A", "scope": "équipe", "n_bucket": "10-15",
    "share_in_debt": "majorité", "top_cause": "réunions ajoutées après 18h", "cause_change": "+150 %",
    "recovery_change": -10, "trend": [{"week": "2026-W40", "avg_recovery": 52}, ...]}
    """
    from data import cohort

    return cohort.team_trends(team_id)


def company_overview() -> list[dict]:
    """Toutes les unités affichables (équipes ≥ 8, sinon département en bloc),
    de la plus en dérive à la plus stable. Mêmes champs que team_trends, sans `trend`."""
    from data import cohort

    return cohort.company_overview()


def measure_rule_effect(unit_id: str, start_date: str) -> dict:
    """Récupération moyenne de l'unité avant / depuis l'application d'une règle.
    Exemple : {"recovery_before": 56, "recovery_after": 60, "recovery_change": 4,
    "cause_change": "-50 %", "verdict": "efficace", "weeks_since": 4}"""
    from data import cohort

    return cohort.rule_effect(unit_id, start_date)


def create_calendar_block(user_id: str, start: str, end: str) -> dict:
    """Crée un bloc dans l'agenda de la personne (Google Calendar).

    Privacy (CLAUDE.md §3) : titre « Occupé » et visibilité privée imposés ici,
    pas par l'appelant. N'est appelé que sur une action acceptée par la personne.
    Mock : à remplacer par l'appel events.insert de Google Calendar.
    """
    return {"event_id": f"mock-{start}", "title": "Occupé", "visibility": "private",
            "start": start, "end": end}
