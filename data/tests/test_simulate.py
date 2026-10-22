from datetime import date, timedelta

import pytest

from data.simulate import simulate

TODAY = date(2026, 10, 22)


@pytest.fixture(scope="module")
def sim():
    return simulate(weeks=8, today=TODAY, seed=1)


def test_cohort_shape(sim):
    sizes = sim["users"].groupby("team_id").size()
    assert 45 <= len(sim["users"]) <= 55
    assert (sizes >= 8).sum() >= 4 and (sizes < 8).any()  # 4 équipes visibles + 1 trop petite
    assert sim["recovery_daily"]["date"].max() == TODAY  # pas de récupération future
    assert sim["work_events"]["ts"].max().date() > TODAY  # mais l'agenda futur existe (forecast)


def test_no_content_columns(sim):
    assert set(sim["work_events"].columns) == {"user_id", "team_id", "ts", "end_ts", "kind", "created_ts",
                                               "n_attendees", "is_external", "status", "source"}


def test_plausible_whoop_ranges(sim):
    r = sim["recovery_daily"]
    assert r.recovery.between(1, 99).all() and 45 < r.recovery.mean() < 65
    assert r.hrv.between(10, 250).all() and r.rhr.between(35, 90).all()
    assert r.sleep_h.between(3, 11).all() and 6 < r.sleep_h.mean() < 7.6


def test_demo_stories(sim):
    r = sim["recovery_daily"]
    recent = r.date > TODAY - timedelta(days=21)
    ma = r[r.team_id == "ma"]
    assert ma[recent].recovery.mean() < ma[~recent].recovery.mean() - 2  # M&A se dégrade
    co = r[r.team_id == "conseil"]
    rule = r.date > TODAY - timedelta(days=27)
    assert co[rule].recovery.mean() > co[~rule].recovery.mean() + 2  # la règle d'équipe aide
