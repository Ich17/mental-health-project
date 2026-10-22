"""Format commun des événements de travail (métadonnées uniquement).

Tous les connecteurs (Google Calendar, Gmail, mock) produisent des `WorkEvent`.
Une ligne = une ligne de la table ClickHouse `work_events` (data/clickhouse.sql).

Privacy (CLAUDE.md §3) appliquée ici, dans le code :
- la classe n'a AUCUN champ pour un contenu (titre, sujet, corps, description) ;
- l'identifiant de la personne est pseudonymisé (HMAC-SHA256 + sel secret) ;
- les adresses mail ne sont jamais stockées : on ne garde que leur nombre et
  un booléen interne/externe.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Optional

# Horaires « normaux » (heure locale). En dehors = after hours.
WORKDAY_START_H = int(os.getenv("WORKDAY_START_H", "8"))
WORKDAY_END_H = int(os.getenv("WORKDAY_END_H", "19"))
LOCAL_TZ = os.getenv("LOCAL_TZ", "Europe/Paris")

KINDS = {"meeting", "email_in", "email_out"}


@dataclass
class WorkEvent:
    user_id: str                  # pseudonyme (hash), jamais l'email en clair
    team_id: str
    ts: str                       # début, ISO 8601 heure locale, ex. "2026-10-20T21:14:00"
    kind: str                     # meeting | email_in | email_out
    source: str                   # gcal | gmail | sim
    end_ts: Optional[str] = None  # fin (réunions)
    created_ts: Optional[str] = None  # date de création (réunions) → « ajoutée le jour même »
    n_attendees: int = 0          # invités (réunion) ou destinataires (mail)
    is_external: int = 0          # 1 si au moins un domaine différent de celui de la personne
    status: str = "confirmed"     # confirmed | tentative | cancelled | declined
    duration_min: int = 0
    is_after_hours: int = 0
    is_weekend: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def pseudonymize(identifier: str) -> str:
    """Pseudonyme stable d'une personne (email ou id interne).

    HMAC avec un sel secret (`PSEUDONYM_SALT` dans .env) : sans le sel, impossible
    de retrouver l'email en testant des adresses connues.
    """
    salt = os.getenv("PSEUDONYM_SALT", "dev-salt-change-me").encode()
    digest = hmac.new(salt, identifier.strip().lower().encode(), hashlib.sha256)
    return digest.hexdigest()[:16]


def make_event(user_id: str, team_id: str, kind: str, source: str, start: datetime,
               end: Optional[datetime] = None, created: Optional[datetime] = None,
               n_attendees: int = 0, is_external: bool = False,
               status: str = "confirmed", workday: tuple = None) -> WorkEvent:
    """Construit un WorkEvent et calcule les champs dérivés (durée, soir, week-end).

    `start`, `end`, `created` : datetimes en heure locale, sans fuseau (naïfs).
    `workday` : (début, fin) des horaires normaux si différents du défaut (ex. usine 7h-16h).
    """
    day_start, day_end = workday or (WORKDAY_START_H, WORKDAY_END_H)
    if kind not in KINDS:
        raise ValueError(f"kind inconnu : {kind}")
    duration = int((end - start).total_seconds() // 60) if end else 0
    last = end - timedelta(minutes=1) if end and end > start else start
    after_hours = (start.hour < day_start or start.hour >= day_end
                   or last.hour >= day_end or last.date() != start.date())
    return WorkEvent(
        user_id=user_id, team_id=team_id, kind=kind, source=source,
        ts=_iso(start), end_ts=_iso(end), created_ts=_iso(created),
        n_attendees=int(n_attendees), is_external=int(bool(is_external)), status=status,
        duration_min=max(duration, 0), is_after_hours=int(after_hours),
        is_weekend=int(start.weekday() >= 5),
    )


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.replace(microsecond=0).isoformat() if dt else None


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().lower() if "@" in address else ""


# --- Fichiers JSONL (export de secours / mode mock) -------------------------

def write_jsonl(events: Iterable[WorkEvent], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> Iterator[WorkEvent]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield WorkEvent(**json.loads(line))
