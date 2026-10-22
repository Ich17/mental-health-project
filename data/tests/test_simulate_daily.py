import random
from datetime import date, timedelta

from data.check_whoop import WORK_COLUMNS
from data.simulate_daily import simulate, summary


def _rows(n=60):
    rng = random.Random(0)
    d0 = date(2026, 8, 24)
    return [{"user_id": "u", "team_id": "t", "date": (d0 + timedelta(i)).isoformat(),
             "recovery": rng.uniform(20, 90), "source": "whoop"} for i in range(n)]


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
