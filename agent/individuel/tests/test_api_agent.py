from fastapi.testclient import TestClient

import agent.memory as memory
from api.main import app


def test_run_then_accept_block(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENT_MODE", "scripted")
    monkeypatch.setattr(memory, "_store", None)
    client = TestClient(app)

    r = client.post("/api/agent/runs", json={"kind": "semaine", "wait": True}).json()
    assert r["status"] == "done"
    assert client.get(f"/api/agent/runs/{r['run_id']}").json()["status"] == "done"

    proposed = client.get("/api/actions").json()
    block = next(a for a in proposed if a["kind"] == "calendar_block")
    res = client.post(f"/api/actions/{block['id']}/accept").json()
    assert res["result"]["title"] == "Occupé" and res["result"]["visibility"] == "private"
    assert client.post(f"/api/actions/{block['id']}/accept").status_code == 409   # pas deux fois

    other = next(a for a in proposed if a["id"] != block["id"])
    assert client.post(f"/api/actions/{other['id']}/reject").json()["status"] == "rejected"


def test_background_run_returns_id(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENT_MODE", "scripted")
    monkeypatch.setattr(memory, "_store", None)
    client = TestClient(app)
    r = client.post("/api/agent/runs", json={"kind": "jour"}).json()
    assert r["status"] == "running" and r["run_id"]
