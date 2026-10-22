"""Interface entre la partie data et la partie agent / API.

Pour l'instant chaque fonction renvoie un mock (exemples du CLAUDE.md §8),
ce qui permet de coder l'agent et le front sans attendre les vraies données.
On remplacera le corps des fonctions par les requêtes ClickHouse ; garder les
signatures stables évite de casser l'autre côté.
"""


def get_daily_metrics(user_id: str, days: int = 42) -> list[dict]:
    """Indicateurs de charge du jour J + récupération à J+1, un dict par jour."""
    return [
        {"date": "2026-10-19", "meeting_hours": 4.0, "last_minute_meetings": 1,
         "meetings_after_20h": 0, "emails_in": 62, "green_hours": 9.1,
         "recovery": 58, "hrv": 52, "sleep_h": 7.2},
        {"date": "2026-10-20", "meeting_hours": 6.5, "last_minute_meetings": 3,
         "meetings_after_20h": 2, "emails_in": 87, "green_hours": 10.2,
         "recovery": 34, "hrv": 41, "sleep_h": 6.1},
    ][-days:]


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
    return [
        {"date": "2026-10-27", "predicted_recovery": 61, "risk": "vert", "reason": "journée légère"},
        {"date": "2026-10-28", "predicted_recovery": 47, "risk": "orange", "reason": "6h de réunions"},
        {"date": "2026-10-29", "predicted_recovery": 28, "risk": "rouge", "reason": "4 calls après 20h"},
    ]


def get_free_slots(user_id: str, date: str) -> list[dict]:
    """Créneaux libres d'une journée (ISO 8601, heure locale)."""
    return [
        {"start": f"{date}T12:30:00", "end": f"{date}T13:30:00"},
        {"start": f"{date}T18:00:00", "end": f"{date}T19:00:00"},
    ]


def team_trends(team_id: str) -> dict:
    """Tendances anonymes d'une équipe, calculées sur la cohorte (data/team_view.py).

    Privacy : le seuil n >= 8 est appliqué dans la couche data (puis dans la requête
    ClickHouse), pas ici ni dans l'agent. Si le groupe est trop petit, renvoie
    {"insufficient_group": True}.
    Exemple : {"unit_id": "ma", "team": "M&A", "n_bucket": "12-20", "share_in_debt": "majorité",
    "top_cause": "réunions ajoutées le jour même", "cause_change": "+54 %", "recovery_change": -7,
    "trend": [{"week": "2026-W40", "avg_recovery": 52}, ...]}
    """
    from data import team_view

    return team_view.team_trends(team_id)


def company_overview() -> list[dict]:
    """Toutes les équipes affichables (n >= 8), de la plus en dérive à la plus stable.
    Mêmes champs que team_trends, sans `trend`."""
    from data import team_view

    return team_view.company_overview()


def measure_rule_effect(team_id: str, start_date: str) -> dict:
    """Récupération moyenne de l'équipe avant / depuis l'application d'une règle.
    Exemple : {"recovery_before": 61, "recovery_after": 69, "recovery_change": 8,
    "cause_change": "-69 %", "verdict": "efficace", "weeks_since": 3}"""
    from data import team_view

    return team_view.rule_effect(team_id, start_date)
