import contracts
from agent import guardrails
from agent.memory import InMemoryMemory
from agent.team import council
from agent.team.scripted import ScriptedTeamLLM


def test_team_run_suggests_one_rule():
    store = InMemoryMemory()
    r = council.run("ma", llm=ScriptedTeamLLM(), store=store)
    assert r["status"] == "done"
    assert [m["author"] for m in r["messages"]][:3] == ["orchestrateur", "observateur", "conseiller"]
    assert len(r["rules"]) == 1
    assert any(x["status"] == "suggested" for x in store.team_rules("ma"))
    assert guardrails.check_hr_text(r["final_message"]) == []


def test_small_team_never_reaches_the_agents(monkeypatch):
    monkeypatch.setattr(contracts, "team_trends", lambda team_id: {"insufficient_group": True})
    r = council.run("petite", llm=ScriptedTeamLLM(), store=InMemoryMemory())
    assert [m["author"] for m in r["messages"]] == ["orchestrateur"]
    assert r["rules"] == []


def test_team_route(monkeypatch):
    from fastapi.testclient import TestClient

    import agent.memory as memory
    from api.main import app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENT_MODE", "scripted")
    monkeypatch.setattr(memory, "_store", None)
    r = TestClient(app).post("/api/agent/team-runs/ma").json()
    assert r["status"] == "done" and r["rules"]
