from data.whoop import to_daily

STAGES = {"total_light_sleep_time_milli": 4 * 3_600_000, "total_slow_wave_sleep_time_milli": 3_600_000,
          "total_rem_sleep_time_milli": 2 * 3_600_000}
SLEEP = {"id": "s1", "cycle_id": 1, "nap": False, "score_state": "SCORED",
         "start": "2026-10-20T22:30:00.000Z", "end": "2026-10-21T05:45:00.000Z", "timezone_offset": "+02:00",
         "score": {"stage_summary": STAGES, "sleep_consistency_percentage": 81}}
RECOVERY = {"cycle_id": 1, "sleep_id": "s1", "score_state": "SCORED",
            "score": {"user_calibrating": False, "recovery_score": 44, "resting_heart_rate": 58,
                      "hrv_rmssd_milli": 47.36}}
CYCLE = {"id": 1, "score": {"strain": 12.34}}


def test_to_daily_maps_whoop_v2_fields():
    nap = {**SLEEP, "id": "s2", "nap": True}
    [row] = to_daily([RECOVERY], [SLEEP, nap], [CYCLE])
    assert row["date"] == "2026-10-21"  # jour du réveil, heure locale
    assert row["bedtime"] == "2026-10-21T00:30"
    assert (row["recovery"], row["hrv"], row["rhr"], row["sleep_h"], row["strain"]) == (44, 47.4, 58, 7.0, 12.3)
    assert row["source"] == "whoop"


def test_to_daily_skips_unscored_and_calibrating():
    calibrating = {**RECOVERY, "score": {**RECOVERY["score"], "user_calibrating": True}}
    pending = {**RECOVERY, "score_state": "PENDING_SCORE"}
    assert to_daily([calibrating, pending], [SLEEP], [CYCLE]) == []


def test_get_retries_on_slow_network(monkeypatch):
    import httpx

    from data import whoop

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("handshake timed out")
        return httpx.Response(200, json={"records": [], "next_token": None})

    monkeypatch.setattr(whoop.time, "sleep", lambda s: None)
    with httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler)) as c:
        assert whoop._get(c, "/v2/cycle", {}).json() == {"records": [], "next_token": None}
    assert calls["n"] == 3
