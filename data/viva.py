"""Échantillon de démo Microsoft Viva Insights → indicateurs hebdomadaires normalisés.

Source : `pq_data.csv` du paquet open source microsoft/vivainsights-py (licence MIT).
C'est le format exact de ce que Microsoft 365 (Outlook + Teams) fournit à une
entreprise : une ligne par personne et par semaine, métadonnées uniquement.
Contenu actuel : 300 personnes, 35 semaines (mars → nov. 2024), 7 équipes.

Attention : données de démo générées par Microsoft (pas de vrais salariés).
Parfait pour tester la chaîne et la vue équipe, pas comme preuve scientifique.

Les colonnes d'enquête (wellbeing, workload, work_life_balance, échelle 1-5)
servent UNIQUEMENT à valider nos détections ; elles ne sont jamais exposées
individuellement (CLAUDE.md §3).
"""
from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path

from data.events import pseudonymize

RAW = Path(__file__).resolve().parent / "raw"
CSV_FILE = RAW / "viva_pq_data.csv"
JSONL_FILE = RAW / "viva_weekly.jsonl"
CSV_URL = ("https://raw.githubusercontent.com/microsoft/vivainsights-py/"
           "main/vivainsights/data/pq_data.csv")

# Colonne Viva → notre nom. On ignore le reste (usage de Copilot, réseau…).
COLUMNS = {
    "Collaboration_hours": "collaboration_h",
    # Meeting_hours et Call_hours sont incohérentes dans l'échantillon (jusqu'à 168 h/semaine,
    # supérieures à la collaboration totale dans ~30 % des lignes) : on prend la colonne
    # cohérente qui regroupe réunions et appels.
    "Meeting_and_call_hours": "meeting_h",
    "Meetings": "meetings",
    "Conflicting_meeting_hours": "conflicting_meeting_h",
    "Email_hours": "email_h",
    "Emails_sent": "emails_sent",
    "Chat_hours": "chat_h",
    "After_hours_collaboration_hours": "after_hours_h",
    "Weekend_collaboration_hours": "weekend_h",
    "Multitasking_hours": "multitasking_h",
    "Collaboration_span": "collaboration_span_h",
    "Active_connected_hours": "active_connected_h",
    # Enquête salarié (1-5) : étiquettes de validation
    "Wellbeing": "wellbeing",
    "Workload": "workload",
    "Work_Life_Balance": "work_life_balance",
}


def download(force: bool = False) -> Path:
    """Télécharge le CSV de Microsoft (~6 Mo) dans data/raw/ (ignoré par git)."""
    if force or not CSV_FILE.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(CSV_URL, CSV_FILE)
    return CSV_FILE


def load_weekly() -> list[dict]:
    """Une ligne par personne et par semaine, au format commun."""
    rows = []
    with download().open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            row = {
                "user_id": pseudonymize(r["PersonId"]),
                "team_id": r.get("Organization") or "Unknown",
                "level": r.get("LevelDesignation") or "Unknown",
                "week": r["MetricDate"],
                "source": "viva",
            }
            for viva_col, ours in COLUMNS.items():
                row[ours] = _num(r.get(viva_col))
            # Nettoyage : une sous-partie ne peut pas dépasser le total de collaboration.
            for part in ("after_hours_h", "multitasking_h"):
                if row[part] is not None and row["collaboration_h"] is not None:
                    row[part] = min(row[part], row["collaboration_h"])
            rows.append(row)
    rows.sort(key=lambda x: (x["user_id"], x["week"]))
    return rows


def write_jsonl(rows: list[dict], path: Path = JSONL_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def summary(rows: list[dict]) -> str:
    people = {r["user_id"] for r in rows}
    weeks = sorted({r["week"] for r in rows})
    teams: dict[str, set] = {}
    for r in rows:
        teams.setdefault(r["team_id"], set()).add(r["user_id"])
    team_txt = ", ".join(f"{t} ({len(p)})" for t, p in sorted(teams.items(), key=lambda x: -len(x[1])))
    return (f"{len(rows)} lignes, {len(people)} personnes, {len(weeks)} semaines "
            f"({weeks[0]} → {weeks[-1]})\n  équipes : {team_txt}")


def _num(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return int(x) if x.is_integer() else round(x, 2)
