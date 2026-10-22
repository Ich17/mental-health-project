"""Vraies données d'entreprise : mails internes d'une entreprise industrielle (Radoslaw).

Source : KONECT, « Manufacturing emails » (Michalski, Palus, Kazienko, 2011).
167 vrais salariés d'une entreprise polonaise de taille moyenne, 82 927 lignes
(une par destinataire) du 2 janvier au 30 septembre 2010. Uniquement qui écrit
à qui et quand : aucun contenu, aucun nom. Pas d'agenda, pas d'équipe.

On reconstitue chaque mail (même expéditeur, même seconde = un mail à plusieurs
destinataires) et on produit des WorkEvent email_out / email_in.

    python -m data.ingest radoslaw
"""
from __future__ import annotations

import tarfile
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data.events import WorkEvent, make_event, pseudonymize

RAW = Path(__file__).resolve().parent / "raw" / "radoslaw"
ARCHIVE = RAW / "radoslaw.tar.bz2"
EDGES = RAW / "radoslaw_email" / "out.radoslaw_email_email"
URL = "http://konect.cc/files/download.tsv.radoslaw_email.tar.bz2"
TZ = ZoneInfo("Europe/Warsaw")
WORKDAY = (7, 16)  # journée observée dans les données (pic 9h-15h)
TEAM_ID = "manufacturing"
# Bords incomplets coupés : on garde des semaines entières (lundi 4 janv. → jeudi 30 sept. 2010).
PERIOD = (datetime(2010, 1, 4), datetime(2010, 10, 1))


def download() -> Path:
    """Télécharge et décompresse l'archive (~0,4 Mo) dans data/raw/ (ignoré par git)."""
    if not EDGES.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        if not ARCHIVE.exists():
            urllib.request.urlretrieve(URL, ARCHIVE)
        with tarfile.open(ARCHIVE, "r:bz2") as tar:
            tar.extractall(RAW, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(RAW)
    return EDGES


def load_events() -> list[WorkEvent]:
    # Nettoyage : un destinataire compte une seule fois par mail, et on retire les mails à soi-même.
    recipients: dict[tuple[int, int], set[int]] = defaultdict(set)
    with download().open() as f:
        for line in f:
            if line.startswith("%"):
                continue
            sender, recipient, _weight, ts = (int(x) for x in line.split())
            if recipient != sender:
                recipients[(sender, ts)].add(recipient)

    events: list[WorkEvent] = []
    for (sender, ts), to in recipients.items():
        when = datetime.fromtimestamp(ts, TZ).replace(tzinfo=None)
        if not (PERIOD[0] <= when < PERIOD[1]):
            continue
        events.append(_event(sender, "email_out", when, len(to)))
        for r in to:
            events.append(_event(r, "email_in", when, len(to)))
    events.sort(key=lambda e: (e.user_id, e.ts))
    return events


BINS = 36  # journée de travail découpée en quarts d'heure (7h → 16h)


def calibration(events: list[WorkEvent] | None = None) -> dict:
    """Rythmes réels à reprendre dans le simulateur (forme, pas volumes).

    - hour_profile : poids de chaque quart d'heure de la journée de travail pour les
      mails envoyés en semaine (position relative : 0 = début, 1 = fin de journée) ;
    - recipients_out / recipients_in : part des mails à 1, 2, … 10+ destinataires.
    """
    events = events if events is not None else load_events()
    start, end = WORKDAY
    bins = [0] * BINS
    out_n, in_n = [0] * 10, [0] * 10
    for e in events:
        n = min(e.n_attendees, 10) - 1
        if e.kind == "email_in":
            in_n[n] += 1
            continue
        out_n[n] += 1
        t = datetime.fromisoformat(e.ts)
        h = t.hour + t.minute / 60
        if not e.is_weekend and start <= h < end:
            bins[int((h - start) / (end - start) * BINS)] += 1
    share = lambda xs: [round(x / sum(xs), 4) for x in xs]  # noqa: E731
    return {"hour_profile": share(bins), "recipients_out": share(out_n), "recipients_in": share(in_n)}


def _event(person: int, kind: str, when: datetime, n: int) -> WorkEvent:
    return make_event(pseudonymize(f"radoslaw-{person}"), TEAM_ID, kind, "radoslaw", when,
                      n_attendees=n, workday=WORKDAY)


if __name__ == "__main__":
    # Recalcule les constantes RADOSLAW_* de data/simulate_work.py.
    import json

    print(json.dumps(calibration()))
