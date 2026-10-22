import random
from datetime import date, timedelta

from data.check_whoop import WORK_COLUMNS
from data.simulate_daily import MIN_GROUP, TEAMS, simulate, simulate_cohort, summary, team_summary


def _rows(n=60):
    rng = random.Random(0)
    d0 = date(2026, 8, 24)
    return [{"user_id": "u", "team_id": "t", "date": (d0 + timedelta(i)).isoformat(),
             "recovery": rng.uniform(20, 90), "hrv": rng.uniform(40, 90), "rhr": rng.uniform(50, 60),
             "sleep_h": rng.uniform(5, 8), "sleep_consistency": rng.uniform(50, 80), "strain": rng.uniform(5, 15),
             "bedtime": (d0 + timedelta(i)).isoformat() + "T00:30", "source": "whoop", "imputed": ""}
            for i in range(n)]


def test_fills_all_work_columns_consistently():
    out = simulate(_rows())
    for r in out:
        assert all(r[k] is not None and r[k] >= 0 for k in WORK_COLUMNS)
        assert r["emails_received_night"] <= r["emails_received"]
        assert r["last_minute_meetings"] <= r["n_meetings"] and r["meeting_hours"] <= 11
        assert r["team_id"] == "finance" and "source" not in r and "imputed" not in r
    weekend = [r for r in out if date.fromisoformat(r["date"]).weekday() >= 5]
    assert any(r["n_meetings"] == 0 and r["emails_received"] == 0 for r in weekend)
    assert simulate(_rows()) == out  # reproductible (graine fixe)


def test_low_recovery_next_day_means_more_work():
    out = simulate(_rows(300))
    pairs = [(out[i]["emails_received"], out[i + 1]["recovery"]) for i in range(len(out) - 1)
             if date.fromisoformat(out[i]["date"]).weekday() < 5]
    low = [e for e, rec in pairs if rec < 40]
    high = [e for e, rec in pairs if rec > 70]
    assert sum(low) / len(low) > sum(high) / len(high)
    assert summary(out)


def test_cohort_has_5_teams_of_8_with_coherent_trends():
    base = _rows(58)
    out = simulate_cohort(base)
    users = {}
    for r in out:
        users.setdefault(r["team_id"], set()).add(r["user_id"])
    assert set(users) == set(TEAMS) and all(len(u) == MIN_GROUP for u in users.values())
    assert "u" in users["finance"] and len(out) == 40 * 58
    by = lambda t, k: sum(r[k] for r in out if r["team_id"] == t) / sum(r["team_id"] == t for r in out)  # noqa: E731
    assert by("top_management", "meeting_hours") > by("finance", "meeting_hours") > by("it", "meeting_hours")
    assert by("top_management", "recovery") < by("it", "recovery")
    for r in out:
        wkend = date.fromisoformat(r["date"]).weekday() >= 5
        if r["team_id"] in ("sales", "rh", "it") and wkend:
            assert r["n_meetings"] == 0 and r["emails_received"] == 0
        if r["team_id"] in ("rh", "it"):
            assert r["emails_received_night"] == 0 and r["emails_sent_night"] == 0
        assert 1 <= r["recovery"] <= 99 and 3 <= r["sleep_h"] <= 11
    assert len(team_summary(out)) == 6


def test_to_clickhouse_creates_tables_and_inserts(monkeypatch):
    import clickhouse_connect

    from data import simulate_daily

    calls = {"cmd": [], "insert": None}

    class Fake:
        def command(self, sql):
            calls["cmd"].append(sql)

        def insert(self, table, data, column_names):
            calls["insert"] = (table, data, column_names)

        def query(self, sql):
            return type("R", (), {"result_rows": [(len(calls["insert"][1]), 40)]})()

    monkeypatch.setenv("CLICKHOUSE_URL", "https://u:p@h:1")
    monkeypatch.setattr(clickhouse_connect, "get_client", lambda dsn, secure: calls.update(secure=secure) or Fake())
    rows = simulate_cohort(_rows(10))
    simulate_daily.to_clickhouse(rows)
    assert any("CREATE TABLE IF NOT EXISTS daily_base" in c for c in calls["cmd"])
    table, data, cols = calls["insert"]
    assert table == "daily_base" and len(data) == 400 and cols[-1] == "last_minute_meetings"
    assert isinstance(data[0][2], date) and calls["secure"] is True
