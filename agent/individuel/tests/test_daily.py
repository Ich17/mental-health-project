"""data/daily.py : events + récupération → indicateurs par jour (format de contracts.get_daily_metrics)."""
import csv

import pytest

import contracts
from data import daily

WORK_COLS = ["user_id", "team_id", "ts", "end_ts", "kind", "created_ts", "status", "duration_min"]
REC_COLS = ["user_id", "team_id", "date", "recovery", "hrv", "sleep_h"]


@pytest.fixture
def sim_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_DATA", "sim")
    monkeypatch.setattr(daily, "SIM_DIRS", (tmp_path,))
    events = [
        # lundi 19/10 : une réunion prévue de longue date, une ajoutée le jour même à 21h, une annulée, un mail
        ["persona_demo", "ma", "2026-10-19 10:00:00", "2026-10-19 11:30:00", "meeting", "2026-10-01 09:00:00", "confirmed", 90],
        ["persona_demo", "ma", "2026-10-19 21:00:00", "2026-10-19 22:00:00", "meeting", "2026-10-19 15:00:00", "confirmed", 60],
        ["persona_demo", "ma", "2026-10-19 14:00:00", "2026-10-19 15:00:00", "meeting", "2026-10-18 09:00:00", "cancelled", 60],
        ["persona_demo", "ma", "2026-10-19 08:00:00", "", "email_in", "", "confirmed", 0],
        ["autre", "ma", "2026-10-19 10:00:00", "2026-10-19 18:00:00", "meeting", "", "confirmed", 480],
    ]
    recovery = [
        ["persona_demo", "ma", "2026-10-20", 41, 45.2, 6.3],   # nuit du 19 au 20 → charge du 19
        ["persona_demo", "ma", "2026-10-21", 63, 55.0, 7.4],   # charge du 20 : journée vide
    ]
    for name, cols, rows in (("work_events.csv", WORK_COLS, events), ("recovery_daily.csv", REC_COLS, recovery)):
        with (tmp_path / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
    return tmp_path


def test_daily_metrics_from_simulator(sim_dir):
    rows = daily.daily_metrics("ichane")                  # inconnu du simulateur → persona_demo
    assert [r["date"] for r in rows] == ["2026-10-19", "2026-10-20"]
    monday, tuesday = rows
    assert monday["meeting_hours"] == 2.5                 # la réunion annulée ne compte pas
    assert monday["last_minute_meetings"] == 1
    assert monday["meetings_after_20h"] == 1
    assert monday["emails_in"] == 1
    assert (monday["recovery"], monday["hrv"], monday["sleep_h"]) == (41, 45, 6.3)   # récupération de J+1
    assert tuesday["meeting_hours"] == 0 and tuesday["recovery"] == 63
    assert monday["source"] == "sim"


def test_contracts_falls_back_to_mock_without_data(monkeypatch):
    monkeypatch.setenv("DAILY_DATA", "mock")
    assert daily.source() is None
    rows = contracts.get_daily_metrics("ichane")
    assert len(rows) == 42 and "source" not in rows[0]


def test_contracts_uses_daily_when_available(sim_dir):
    assert contracts.get_daily_metrics("ichane")[0]["source"] == "sim"
