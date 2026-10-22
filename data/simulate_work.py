"""Données de travail synthétiques (mode mock), au même format que gcal/gmail.

Par défaut : une équipe de 10 personnes sur 13 semaines. On injecte des profils
connus, ce qui permet de mesurer la détection (« alerte X jours après le début
de la dérive, Y % de fausses alertes ») :
- `drift`  : 3 personnes dont la charge dérive progressivement sur ~4 semaines
             (plus de réunions, réunions ajoutées au dernier moment, mails tard
             le soir, week-ends) puis reste haute ;
- `spike`  : 1 personne avec une seule semaine de rush puis retour à la normale
             (ponctuel → ne doit PAS déclencher d'alerte durable) ;
- `normal` : les autres, avec du bruit réaliste.

La vérité terrain est écrite à côté, dans `*_truth.json`.
Déterministe (graine fixe) : tout le monde régénère exactement les mêmes données.
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from data.events import WorkEvent, make_event, pseudonymize

DEFAULT_END = date(2026, 10, 21)

# (profil, jour de début de la dérive / du rush, en jours depuis le début)
DEFAULT_PROFILES = ["normal", "drift", "normal", "spike", "normal",
                    "drift", "normal", "normal", "drift", "normal"]
DRIFT_STARTS = [38, 52, 62]   # les 3 dérives ne commencent pas le même jour
SPIKE_START = 45
RAMP_DAYS = 28                # durée de la montée progressive


def generate(n_people: int = 10, days: int = 91, end: date = DEFAULT_END,
             team_id: str = "produit", seed: int = 42) -> tuple[list[WorkEvent], dict]:
    rng = random.Random(seed)
    start_day = end - timedelta(days=days - 1)
    profiles = (DEFAULT_PROFILES * (n_people // len(DEFAULT_PROFILES) + 1))[:n_people]
    drift_starts = iter(DRIFT_STARTS * n_people)

    events: list[WorkEvent] = []
    truth = {"team_id": team_id, "start": start_day.isoformat(), "end": end.isoformat(),
             "employees": []}
    for i, profile in enumerate(profiles):
        alias = f"emp{i + 1:02d}"
        user_id = pseudonymize(f"{alias}@{team_id}.example")
        onset = next(drift_starts) if profile == "drift" else SPIKE_START if profile == "spike" else None
        person = _Person(rng, user_id, team_id, profile, onset)
        for d in range(days):
            events.extend(person.day(start_day + timedelta(days=d), d))
        truth["employees"].append({
            "alias": alias, "user_id": user_id, "profile": profile,
            "onset_date": (start_day + timedelta(days=onset)).isoformat() if onset is not None else None,
        })
    events.sort(key=lambda e: (e.user_id, e.ts))
    return events, truth


class _Person:
    def __init__(self, rng: random.Random, user_id: str, team_id: str, profile: str,
                 onset: int | None):
        self.rng, self.user_id, self.team_id = rng, user_id, team_id
        self.profile, self.onset = profile, onset
        # Chacun a sa propre « normale » (c'est ce que l'agent doit apprendre).
        self.base_meetings = rng.uniform(2.0, 4.5)
        self.base_mails_out = rng.uniform(8, 20)
        self.base_mails_in = rng.uniform(20, 45)
        self.base_late_share = rng.uniform(0.02, 0.08)
        self.day_start_h = rng.uniform(8.5, 9.5)

    def load(self, d: int) -> float:
        """Intensité de la surcharge, entre 0 (normale) et 1 (dérive installée)."""
        if self.onset is None or d < self.onset:
            return 0.0
        if self.profile == "drift":
            return min(1.0, (d - self.onset) / RAMP_DAYS)
        if self.profile == "spike":
            return 0.9 if d < self.onset + 6 else 0.0
        return 0.0

    def day(self, day: date, d: int) -> list[WorkEvent]:
        rng, x = self.rng, self.load(d)
        weekend = day.weekday() >= 5
        if weekend and rng.random() > 0.05 + 0.55 * x:
            return []
        scale = 0.25 if weekend else 1.0
        out: list[WorkEvent] = []

        # Réunions
        for _ in range(_poisson(rng, scale * (self.base_meetings + 3.5 * x))):
            late = rng.random() < 0.03 + 0.30 * x
            start_h = rng.uniform(19, 21.5) if late else rng.uniform(self.day_start_h, 18)
            start = _at(day, start_h, step=15)
            duration = rng.choice([30, 30, 45, 60, 60, 90])
            lead_h = rng.uniform(1, 20) if rng.random() < 0.08 + 0.45 * x else rng.uniform(26, 24 * 14)
            out.append(self._ev("meeting", start, start + timedelta(minutes=duration),
                                created=start - timedelta(hours=lead_h),
                                n=rng.choice([2, 2, 3, 4, 5, 6, 8, 12]),
                                external=rng.random() < 0.2))

        # Mails envoyés : la part du soir augmente avec la dérive
        late_share = self.base_late_share + 0.35 * x
        for _ in range(_poisson(rng, scale * self.base_mails_out * (1 + 0.8 * x))):
            h = rng.uniform(19, 23.9) if rng.random() < late_share else rng.uniform(self.day_start_h, 19)
            out.append(self._ev("email_out", _at(day, h), n=rng.choice([1, 1, 1, 2, 3, 5]),
                                external=rng.random() < 0.25))

        # Mails reçus
        for _ in range(_poisson(rng, scale * self.base_mails_in * (1 + 0.5 * x))):
            h = rng.uniform(19, 23.9) if rng.random() < 0.1 + 0.2 * x else rng.uniform(7.5, 19)
            out.append(self._ev("email_in", _at(day, h), n=rng.choice([1, 1, 2, 4, 10]),
                                external=rng.random() < 0.35))
        return out

    def _ev(self, kind, start, end=None, created=None, n=1, external=False) -> WorkEvent:
        return make_event(self.user_id, self.team_id, kind, "sim", start, end=end,
                          created=created, n_attendees=n, is_external=external)


def _at(day: date, hour: float, step: int = 1) -> datetime:
    minutes = int(hour * 60) // step * step
    return datetime.combine(day, time()) + timedelta(minutes=minutes)


def _poisson(rng: random.Random, lam: float) -> int:
    """Tirage de Poisson (algorithme de Knuth), sans dépendre de numpy."""
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def write_truth(truth: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(truth, indent=2, ensure_ascii=False))
