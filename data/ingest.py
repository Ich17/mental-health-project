"""Point d'entrée de l'ingestion : Google (réel) ou mock (synthétique), même format.

Exemples (depuis la racine du repo) :
    python -m data.ingest mock                 # génère/relit les données synthétiques
    python -m data.ingest google --days 90     # vrai compte Google (OAuth)
    python -m data.ingest google --only calendar
    python -m data.ingest mock --clickhouse    # + insertion dans ClickHouse (CLICKHOUSE_URL)
    python -m data.ingest viva                 # échantillon Microsoft Viva (hebdo, 300 pers.)
    python -m data.ingest radoslaw             # vrais mails d'une entreprise industrielle (2010)

Dans le code (agent, API) : `load_events()` lit le mode dans DATA_MODE (mock par défaut).
"""
from __future__ import annotations

import argparse
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from data.events import WorkEvent, read_jsonl, write_jsonl

RAW = Path(__file__).resolve().parent / "raw"
MOCK_FILE = RAW / "work_events_sim.jsonl"
MOCK_TRUTH = RAW / "work_events_sim_truth.json"
GOOGLE_FILE = RAW / "work_events_google.jsonl"
RADOSLAW_FILE = RAW / "work_events_radoslaw.jsonl"

CLICKHOUSE_COLUMNS = ["user_id", "team_id", "ts", "end_ts", "kind", "created_ts",
                      "n_attendees", "is_external", "status", "source",
                      "duration_min", "is_after_hours", "is_weekend"]


def load_events(mode: str | None = None) -> list[WorkEvent]:
    """Événements de travail normalisés, quel que soit le mode."""
    mode = mode or os.getenv("DATA_MODE", "mock")
    if mode == "mock":
        if not MOCK_FILE.exists():
            simulate()
        return list(read_jsonl(MOCK_FILE))
    if mode == "google":
        if not GOOGLE_FILE.exists():
            raise FileNotFoundError("Lancer d'abord : python -m data.ingest google")
        return list(read_jsonl(GOOGLE_FILE))
    if mode == "radoslaw":
        if not RADOSLAW_FILE.exists():
            from data import radoslaw
            write_jsonl(radoslaw.load_events(), RADOSLAW_FILE)
        return list(read_jsonl(RADOSLAW_FILE))
    raise ValueError(f"DATA_MODE inconnu : {mode} (mock | google | radoslaw)")


def simulate(**kwargs) -> list[WorkEvent]:
    from data.simulate_work import generate, write_truth

    events, truth = generate(**kwargs)
    write_jsonl(events, MOCK_FILE)
    write_truth(truth, MOCK_TRUTH)
    return events


def fetch_google(days: int, only: str | None) -> list[WorkEvent]:
    from data import gcal, gmail

    team_id = os.getenv("TEAM_ID", "demo")
    events: list[WorkEvent] = []
    if only in (None, "calendar"):
        events += gcal.fetch(days_back=days, team_id=team_id)
    if only in (None, "gmail"):
        events += gmail.fetch(days_back=days, team_id=team_id)
    events.sort(key=lambda e: e.ts)
    write_jsonl(events, GOOGLE_FILE)  # sauvegarde de secours (plan B), ignorée par git
    return events


def to_clickhouse(events: list[WorkEvent]) -> None:
    import clickhouse_connect

    url = os.getenv("CLICKHOUSE_URL")
    if not url:
        raise RuntimeError("CLICKHOUSE_URL absent du .env")
    client = clickhouse_connect.get_client(dsn=url)
    rows = []
    for e in events:
        d = e.to_dict()
        for col in ("ts", "end_ts", "created_ts"):
            d[col] = datetime.fromisoformat(d[col]) if d[col] else None
        rows.append([d[c] for c in CLICKHOUSE_COLUMNS])
    client.insert("work_events", rows, column_names=CLICKHOUSE_COLUMNS)


def viva_to_clickhouse(rows: list[dict]) -> None:
    import clickhouse_connect
    from data.viva import COLUMNS

    cols = ["user_id", "team_id", "level", "week", "source"] + list(COLUMNS.values())
    client = clickhouse_connect.get_client(dsn=os.environ["CLICKHOUSE_URL"])
    data = [[date.fromisoformat(r[c]) if c == "week" else r[c] for c in cols] for r in rows]
    client.insert("work_weekly", data, column_names=cols)


def summary(events: list[WorkEvent]) -> str:
    kinds = Counter(e.kind for e in events)
    people = len({e.user_id for e in events})
    late = sum(e.is_after_hours for e in events)
    weekend = sum(e.is_weekend for e in events)
    span = f"{min(e.ts for e in events)[:10]} → {max(e.ts for e in events)[:10]}" if events else "vide"
    return (f"{len(events)} événements, {people} personne(s), {span}\n"
            f"  par type : {dict(kinds)}\n"
            f"  hors horaires : {late}  |  week-end : {weekend}")


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="Ingestion des métadonnées de travail")
    p.add_argument("mode", choices=["mock", "google", "viva", "radoslaw"])
    p.add_argument("--days", type=int, default=90, help="historique à récupérer (jours)")
    p.add_argument("--only", choices=["calendar", "gmail"], help="une seule source Google")
    p.add_argument("--regenerate", action="store_true", help="mock : recréer les données")
    p.add_argument("--clickhouse", action="store_true", help="insérer dans ClickHouse")
    args = p.parse_args()

    if args.mode == "viva":
        from data import viva

        rows = viva.load_weekly()
        path = viva.write_jsonl(rows)
        print(f"Viva : {path.relative_to(RAW.parent.parent)}")
        print(viva.summary(rows))
        if args.clickhouse:
            viva_to_clickhouse(rows)
            print("Inséré dans ClickHouse (table work_weekly).")
        return

    if args.mode == "radoslaw":
        from data import radoslaw

        events = radoslaw.load_events()
        write_jsonl(events, RADOSLAW_FILE)
        print(f"Radoslaw : {RADOSLAW_FILE.relative_to(RAW.parent.parent)}")
    elif args.mode == "mock":
        events = simulate() if args.regenerate or not MOCK_FILE.exists() else load_events("mock")
        print(f"Mock : {MOCK_FILE.relative_to(RAW.parent.parent)} (vérité : {MOCK_TRUTH.name})")
    else:
        events = fetch_google(args.days, args.only)
        print(f"Google : sauvegardé dans {GOOGLE_FILE.relative_to(RAW.parent.parent)}")
    print(summary(events))
    if args.clickhouse:
        to_clickhouse(events)
        print("Inséré dans ClickHouse (table work_events).")


if __name__ == "__main__":
    main()
