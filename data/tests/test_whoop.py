from data.whoop import to_daily

STAGES = {"total_light_sleep_time_milli": 4 * 3_600_000, "total_slow_wave_sleep_time_milli": 3_600_000,
          "total_rem_sleep_time_milli": 2 * 3_600_000}
SLEEP = {"id": "s1", "cycle_id": 1, "nap": False, "score_state": "SCORED",
         "start": "2026-10-20T22:30:00.000Z", "end": "2026-10-21T05:45:00.000Z", "timezone_offset": "+02:00",
         "score": {"stage_summary": STAGES, "sleep_consistency_percentage": 81}}
RECOVERY = {"cycle_id": 1, "sleep_id": "s1", "score_state": "SCORED",
            "score": {"user_calibrating": False, "recovery_score": 44, "resting_heart_rate": 58,
                      "hrv_rmssd_milli": 47.36}}
CYCLE = {"id": 1, "end": "2026-10-21T22:00:00.000Z", "score": {"strain": 12.34}}


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


def test_clean_fills_gaps_and_flags_imputed():
    from data.check_whoop import clean

    base = {"user_id": "u", "team_id": "t", "rhr": 55, "sleep_consistency": 60, "source": "whoop"}
    rows = [
        {**base, "date": "2026-10-01", "recovery": 40, "hrv": 80, "sleep_h": 6, "strain": 10,
         "bedtime": "2026-10-01T00:30"},
        {**base, "date": "2026-10-01", "recovery": 99, "hrv": 99, "sleep_h": 9, "strain": 9,
         "bedtime": "2026-10-01T00:00"},  # doublon
        {**base, "date": "2026-10-03", "recovery": 60, "hrv": 900, "sleep_h": 2, "strain": 0.1,
         "bedtime": "2026-10-03T01:30"},  # HRV impossible, nuit de 2h, montre pas portée
        {**base, "date": "2026-10-04", "recovery": 50, "hrv": 90, "sleep_h": 7, "strain": 14,
         "bedtime": "2026-10-03T23:30"},
    ]
    out, notes = clean(rows)
    assert [r["date"] for r in out] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    gap = out[1]
    assert gap["recovery"] == 50 and gap["strain"] == 12 and "recovery" in gap["imputed"]
    assert gap["bedtime"] == "2026-10-02T01:00"  # nuit du 1er au 2
    bad = out[2]
    assert bad["imputed"] == "hrv,strain" and bad["hrv"] == 85 and bad["strain"] == 12
    assert bad["recovery"] == 60 and bad["sleep_h"] == 2  # vraies mesures gardées
    assert out[0]["imputed"] == "" and len(notes) >= 4


def test_clean_adds_empty_work_columns(tmp_path):
    from data.check_whoop import WORK_COLUMNS, clean, write_csv

    row = {"user_id": "u", "team_id": "t", "date": "2026-10-01", "recovery": 40, "hrv": 80, "rhr": 55,
           "sleep_h": 7, "sleep_consistency": 60, "strain": 10, "bedtime": "2026-10-01T00:30",
           "source": "whoop"}
    out, _ = clean([row])
    assert len(WORK_COLUMNS) == 7 and all(out[0][k] is None for k in WORK_COLUMNS)
    write_csv(out, tmp_path / "x.csv")
    header = (tmp_path / "x.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(";")
    assert header[-7:] == WORK_COLUMNS


def test_ongoing_cycle_has_no_strain():
    ongoing = {"id": 1, "end": None, "score": {"strain": 3.1}}
    [row] = to_daily([RECOVERY], [SLEEP], [ongoing])
    assert row["strain"] is None
