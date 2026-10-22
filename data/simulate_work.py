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

# Rythmes réels calibrés sur Radoslaw (167 salariés, 58 000 mails) : la FORME de la journée
# et le nombre de destinataires. Les volumes et la dérive restent ceux de la cible (juniors
# banque / conseil), car une usine de 2010 envoie bien moins de mails.
# Recalcul : python -m data.radoslaw
RADOSLAW_HOUR_PROFILE = [  # quarts d'heure du début à la fin de la journée de travail
    0.0025, 0.0032, 0.0068, 0.0124, 0.0131, 0.0144, 0.0208, 0.0302, 0.0317, 0.0334, 0.0372, 0.0372,
    0.0336, 0.0361, 0.0353, 0.0329, 0.0277, 0.0305, 0.0298, 0.0313, 0.0317, 0.0326, 0.0353, 0.034,
    0.0339, 0.0305, 0.032, 0.0325, 0.0316, 0.0322, 0.0313, 0.0301, 0.0301, 0.0317, 0.03, 0.0206]
RADOSLAW_RECIPIENTS_OUT = [  # part des mails envoyés à 1, 2, … 10+ destinataires
    0.8642, 0.0598, 0.031, 0.0163, 0.0077, 0.0035, 0.0024, 0.002, 0.0021, 0.011]
RADOSLAW_RECIPIENTS_IN = [0.6115, 0.0846, 0.0657, 0.046, 0.0274, 0.0148, 0.0121, 0.0114, 0.0134, 0.1129]


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
    # Deux événements strictement identiques (même minute, même type…) n'en font qu'un.
    unique: dict[tuple, WorkEvent] = {}
    for e in events:
        unique.setdefault(tuple(e.to_dict().values()), e)
    return list(unique.values()), truth


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

        # Réunions (jamais deux en même temps pour une même personne)
        busy: list[tuple[datetime, datetime]] = []
        for _ in range(_poisson(rng, scale * (self.base_meetings + 3.5 * x))):
            late = rng.random() < 0.03 + 0.30 * x
            start_h = rng.uniform(19, 21.5) if late else rng.uniform(self.day_start_h, 18)
            start = _at(day, start_h, step=15)
            end = start + timedelta(minutes=rng.choice([30, 30, 45, 60, 60, 90]))
            lead_h = rng.uniform(1, 20) if rng.random() < 0.08 + 0.45 * x else rng.uniform(26, 24 * 14)
            n, external = rng.choice([2, 2, 3, 4, 5, 6, 8, 12]), rng.random() < 0.2
            if any(start < b_end and b_start < end for b_start, b_end in busy):
                continue
            busy.append((start, end))
            out.append(self._ev("meeting", start, end, created=self._created(start, lead_h),
                                n=n, external=external))

        # Mails envoyés : la part du soir augmente avec la dérive
        late_share = self.base_late_share + 0.35 * x
        for _ in range(_poisson(rng, scale * self.base_mails_out * (1 + 0.8 * x))):
            h = rng.uniform(19, 23.9) if rng.random() < late_share else self._work_hour(self.day_start_h)
            out.append(self._ev("email_out", _at(day, h), n=_recipients(rng, RADOSLAW_RECIPIENTS_OUT),
                                external=rng.random() < 0.25))

        # Mails reçus
        for _ in range(_poisson(rng, scale * self.base_mails_in * (1 + 0.5 * x))):
            h = rng.uniform(19, 23.9) if rng.random() < 0.1 + 0.2 * x else self._work_hour(7.5)
            out.append(self._ev("email_in", _at(day, h), n=_recipients(rng, RADOSLAW_RECIPIENTS_IN),
                                external=rng.random() < 0.35))
        return out

    def _work_hour(self, start_h: float, end_h: float = 19) -> float:
        """Heure dans la journée de travail, selon le rythme réel observé dans Radoslaw."""
        b = self.rng.choices(range(len(RADOSLAW_HOUR_PROFILE)), weights=RADOSLAW_HOUR_PROFILE)[0]
        rel = (b + self.rng.random()) / len(RADOSLAW_HOUR_PROFILE)
        return start_h + rel * (end_h - start_h)

    def _created(self, start: datetime, lead_h: float) -> datetime:
        """Date de création d'une réunion, placée en journée (on planifie rarement à 3h du matin)."""
        created = start - timedelta(hours=lead_h)
        if not 8 <= created.hour < 19:
            created = created.replace(hour=self.rng.randint(8, 18), minute=self.rng.randint(0, 59))
        if created >= start:
            created = start - timedelta(minutes=self.rng.randint(30, 120))
        return created.replace(second=0)

    def _ev(self, kind, start, end=None, created=None, n=1, external=False) -> WorkEvent:
        return make_event(self.user_id, self.team_id, kind, "sim", start, end=end,
                          created=created, n_attendees=n, is_external=external)


def _at(day: date, hour: float, step: int = 1) -> datetime:
    minutes = int(hour * 60) // step * step
    return datetime.combine(day, time()) + timedelta(minutes=minutes)


def _recipients(rng: random.Random, shares: list[float]) -> int:
    """Nombre de destinataires tiré selon la répartition réelle (10 = « 10 et plus »)."""
    n = rng.choices(range(1, len(shares) + 1), weights=shares)[0]
    return n if n < len(shares) else rng.randint(10, 25)


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
