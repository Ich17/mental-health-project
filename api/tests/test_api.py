from fastapi.testclient import TestClient

import contracts
from api.main import app

client = TestClient(app)


def test_health_without_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_routes_return_contract_mocks():
    assert client.get("/api/metrics").json() == contracts.get_daily_metrics("ichane")
    assert client.get("/api/drivers").json() == contracts.get_drivers("ichane")
    assert client.get("/api/forecast").json() == contracts.forecast_week("ichane")
    assert client.get("/api/slots/2026-10-29").json()[0]["start"] == "2026-10-29T12:30:00"
    assert client.get("/api/team/ma").json()["team"] == "M&A"


def test_contract_shapes():
    day = contracts.get_daily_metrics("ichane")[0]
    assert {"date", "meeting_hours", "last_minute_meetings", "meetings_after_20h",
            "emails_in", "green_hours", "recovery", "hrv", "sleep_h"} <= day.keys()
    assert {"factor", "label", "effect", "effect_size", "confidence"} <= contracts.get_drivers("ichane")[0].keys()
    assert {"date", "predicted_recovery", "risk", "reason"} <= contracts.forecast_week("ichane")[0].keys()
    assert {"start", "end"} <= contracts.get_free_slots("ichane", "2026-10-29")[0].keys()
    assert {"team", "n_bucket", "share_in_debt", "top_cause", "cause_change", "trend"} <= contracts.team_trends("ma").keys()
