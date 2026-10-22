"""L'Évaluateur : mesure si les blocs acceptés et les expériences ont marché, et l'Action en tient compte."""
from datetime import date, timedelta

import pytest

import contracts
from agent.individuel import council
from agent.individuel.scripted import ScriptedLLM
from agent.individuel.tools import TOOLS
from agent.memory import InMemoryMemory
from agent.toolkit import RunContext, ToolError, run_tool

TUESDAYS_THURSDAYS = {(date.today() - timedelta(days=i)).isoformat()
                      for i in range(25, 9, -1) if (date.today() - timedelta(days=i)).weekday() in (1, 3)}


def metrics(block_bonus: int):
    """42 jours ouvrés identiques, sauf les mardis/jeudis des blocs de démo : +block_bonus de récupération."""
    def get_daily_metrics(user_id, days=42):
        rows = []
        for i in range(42, 0, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            rows.append({"date": d, "meeting_hours": 5.0, "last_minute_meetings": 1, "meetings_after_20h": 0,
                         "emails_in": 60, "green_hours": 9.0, "hrv": 50, "sleep_h": 7.0,
                         "recovery": 50 + (block_bonus if d in TUESDAYS_THURSDAYS else 0)})
        return rows[-days:]
    return get_daily_metrics


def run_week(monkeypatch, block_bonus):
    monkeypatch.setattr(contracts, "get_daily_metrics", metrics(block_bonus))
    store = InMemoryMemory()
    return council.run("ichane", "semaine", llm=ScriptedLLM(), store=store), store


def test_effective_lunch_blocks_are_kept(monkeypatch):
    r, store = run_week(monkeypatch, block_bonus=10)
    evaluation = next(m for m in r["messages"] if m["kind"] == "evaluation")
    assert evaluation["author"] == "evaluateur"
    assert evaluation["data"]["blocs"][0] == {"bloc": "dejeuner", "verdict": "efficace", "ecart_points": 10}
    # Le verdict est gardé en mémoire pour les prochains runs
    assert any(h["factor"] == "evaluation:bloc_dejeuner" for h in store.get_memory("ichane")["hypotheses"])
    proposed = [a["payload"]["purpose"] for a in store.list_actions("ichane", "proposed") if a["kind"] == "calendar_block"]
    assert proposed and set(proposed) == {"dejeuner"}
    assert "ont marché" in r["final_message"]


def test_useless_lunch_blocks_are_replaced(monkeypatch):
    r, store = run_week(monkeypatch, block_bonus=0)
    evaluation = next(m for m in r["messages"] if m["kind"] == "evaluation")
    assert evaluation["data"]["blocs"][0]["verdict"] == "sans effet net"
    proposed = [a["payload"]["purpose"] for a in store.list_actions("ichane", "proposed") if a["kind"] == "calendar_block"]
    assert proposed and set(proposed) == {"sport"}               # l'Action change de type de bloc
    assert "n'ont rien changé" in r["final_message"]


def test_too_few_blocks_is_too_early(monkeypatch):
    monkeypatch.setattr(contracts, "get_daily_metrics", metrics(10))
    store = InMemoryMemory()
    store.seed("ichane")
    day = sorted(TUESDAYS_THURSDAYS)[0]
    store.add_action("ichane", "calendar_block", {"start": f"{day}T12:30:00", "end": f"{day}T13:30:00",
                                                 "purpose": "dejeuner"}, status="done")
    out = run_tool(RunContext(store=store, user_id="ichane"), TOOLS, "evaluate_blocks", {}, ["evaluate_blocks"])
    assert out["blocs"][0]["verdict"] == "trop tôt"


def test_only_the_evaluator_evaluates():
    ctx = RunContext(store=InMemoryMemory(), user_id="ichane")
    with pytest.raises(ToolError):
        run_tool(ctx, TOOLS, "evaluate_experiment", {"experiment_id": 1},
                 allowed=["get_drivers", "get_memory", "save_hypothesis"])   # droits de l'Analyse
