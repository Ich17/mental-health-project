"""Indicateurs par jour pour l'agent individuel : events de travail + récupération → daily_metrics.

C'est la vue `daily_metrics` du CLAUDE.md §7, en Python (sans pandas) en attendant ClickHouse :
une ligne par jour J avec la charge de J et la récupération de J+1 (la ligne Whoop du jour
J+1 = nuit de J à J+1, cf. data/README.md).

Sources, choisies par DAILY_DATA (défaut `auto` : la première disponible) :
- `real` : vraies données exportées en local (jamais dans git)
    data/raw/work_events_google.jsonl  (python -m data.ingest google)
    data/raw/whoop_daily_clean.json ou whoop_daily.json  (python -m data.whoop fetch / data.check_whoop)
- `sim`  : sortie du simulateur (python -m data.simulate), data/sim_out/ ou data/raw/sim_out/
    work_events.csv + recovery_daily.csv ; l'utilisateur de démo est `persona_demo`.
- `mock` : aucune source (tests) → NoDailyData.
Si aucune n'est disponible, daily_metrics() lève NoDailyData et contracts.py garde son mock.

Privacy : on ne lit que des horaires et des comptes (aucun titre, aucun contenu).
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent
RAW = DATA / "raw"
GOOGLE_EVENTS = RAW / "work_events_google.jsonl"
WHOOP_FILES = (RAW / "whoop_daily_clean.json", RAW / "whoop_daily.json")
SIM_DIRS = (DATA / "sim_out", RAW / "sim_out")
SIM_DEMO_USER = "persona_demo"
IGNORED_STATUS = {"cancelled", "declined"}


class NoDailyData(Exception):
    """Aucune source de données disponible pour cet utilisateur."""


# --- Lecture des sources --------------------------------------------------------

def _whoop_file() -> Path | None:
    return next((p for p in WHOOP_FILES if p.exists()), None)


def _sim_dir() -> Path | None:
    return next((d for d in SIM_DIRS if (d / "work_events.csv").exists() and (d / "recovery_daily.csv").exists()), None)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_real() -> tuple[list[dict], list[dict]]:
    """Un seul compte (celui de la démo) : tous les events et toutes les lignes Whoop."""
    with GOOGLE_EVENTS.open(encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    recovery = json.loads(_whoop_file().read_text(encoding="utf-8"))
    return events, recovery


def _load_sim(user_id: str) -> tuple[list[dict], list[dict]]:
    d = _sim_dir()
    events, recovery = _read_csv(d / "work_events.csv"), _read_csv(d / "recovery_daily.csv")
    users = {r["user_id"] for r in recovery}
    uid = user_id if user_id in users else SIM_DEMO_USER
    return [e for e in events if e["user_id"] == uid], [r for r in recovery if r["user_id"] == uid]


def source() -> str | None:
    """La source qui sera utilisée : real, sim ou None."""
    wanted = os.getenv("DAILY_DATA", "auto")
    if wanted in ("auto", "real") and GOOGLE_EVENTS.exists() and _whoop_file():
        return "real"
    if wanted in ("auto", "sim") and _sim_dir():
        return "sim"
    return None


# --- Calcul -----------------------------------------------------------------------

def _dt(value) -> datetime | None:
    return datetime.fromisoformat(str(value)[:19]) if value not in (None, "", "None", "nan") else None


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_day() -> dict:
    return {"meeting_min": 0.0, "n_meetings": 0, "last_minute_meetings": 0, "meetings_after_20h": 0,
            "emails_in": 0, "emails_out": 0, "green_min": 0.0}


def _work_by_day(events: list[dict]) -> dict[str, dict]:
    days: dict[str, dict] = defaultdict(_empty_day)
    for e in events:
        start = _dt(e.get("ts"))
        if start is None or e.get("status") in IGNORED_STATUS:
            continue
        d = days[start.date().isoformat()]
        kind = e.get("kind")
        if kind == "meeting":
            end = _dt(e.get("end_ts"))
            d["meeting_min"] += _num(e.get("duration_min")) or ((end - start).total_seconds() / 60 if end else 0)
            d["n_meetings"] += 1
            created = _dt(e.get("created_ts"))
            if created and timedelta(0) <= start - created < timedelta(hours=24):
                d["last_minute_meetings"] += 1
            if start.hour >= 20:
                d["meetings_after_20h"] += 1
        elif kind == "email_in":
            d["emails_in"] += 1
        elif kind == "email_out":
            d["emails_out"] += 1
        elif kind == "presence_green":
            d["green_min"] += _num(e.get("duration_min")) or 0
    return days


def daily_metrics(user_id: str, days: int = 42) -> list[dict]:
    """Même format que contracts.get_daily_metrics : une ligne par jour J, charge de J + récupération de J+1."""
    src = source()
    if src is None:
        raise NoDailyData("ni export réel (data/raw/) ni sortie du simulateur (data/sim_out/)")
    events, recovery = _load_real() if src == "real" else _load_sim(user_id)
    if not recovery:
        raise NoDailyData(f"aucune donnée de récupération pour {user_id}")

    work = _work_by_day(events)
    rec_by_date = {str(r["date"])[:10]: r for r in recovery}
    rows = []
    for day_iso in sorted(rec_by_date):
        day = date.fromisoformat(day_iso) - timedelta(days=1)   # la récupération du jour = nuit de la veille
        w = work.get(day.isoformat(), _empty_day())
        r = rec_by_date[day_iso]
        if _num(r.get("recovery")) is None:
            continue
        rows.append({
            "date": day.isoformat(),
            "meeting_hours": round(w["meeting_min"] / 60, 1),
            "n_meetings": w["n_meetings"],
            "last_minute_meetings": w["last_minute_meetings"],
            "meetings_after_20h": w["meetings_after_20h"],
            "emails_in": w["emails_in"],
            "green_hours": round(w["green_min"] / 60, 1),
            "recovery": round(_num(r["recovery"])),
            "hrv": round(_num(r.get("hrv")) or 0),
            "sleep_h": round(_num(r.get("sleep_h")) or 0, 1),
            "context": None,   # TODO data : remplir depuis l'agenda (ex. « cloture_trimestrielle »)
            "source": src,
        })
    return rows[-days:]
