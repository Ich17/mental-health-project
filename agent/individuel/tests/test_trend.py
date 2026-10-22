"""Dérive de fond vs pic ponctuel (faux positif de clôture)."""
from datetime import date, timedelta

import contracts
from agent import guardrails
from agent.individuel import council, personas
from agent.individuel.scripted import ScriptedLLM
from agent.individuel.trend import assess_trend
from agent.memory import InMemoryMemory


def rows(*weekly_recovery, context_week=None):
    """6 semaines de 7 jours, une récupération constante par semaine (de la plus ancienne à la plus récente)."""
    start = date(2026, 9, 1)
    out = []
    for w, rec in enumerate(weekly_recovery):
        for d in range(7):
            out.append({"date": (start + timedelta(days=7 * w + d)).isoformat(), "recovery": rec,
                        "meeting_hours": 5.0, "context": "cloture_trimestrielle" if w == context_week else None})
    return out


def test_patterns():
    assert assess_trend(rows(60, 60, 60, 60, 60, 60))["tendance"] == "stable"
    assert assess_trend(rows(60, 60, 60, 60, 40, 42))["tendance"] == "derive"
    assert assess_trend(rows(60, 60, 60, 60, 38, 61))["tendance"] == "pic_passe"
    assert assess_trend(rows(60, 60, 60, 60, 60, 40))["tendance"] == "baisse_recente"
    assert assess_trend(rows(60, 60, 60, 60, 60, 40, context_week=5))["tendance"] == "pic_attendu"
    assert assess_trend(rows(60, 60))["tendance"] == "inconnue"


def test_past_peak_explanation_mentions_context():
    t = assess_trend(rows(60, 60, 60, 60, 38, 61, context_week=4))
    assert t["base_recuperation"] == 60
    assert "clôture trimestrielle" in t["explication"]
    assert guardrails.check_text(t["explication"]) == []


def test_default_persona_is_a_drift():
    r = council.run("ichane", "semaine", llm=ScriptedLLM(), store=InMemoryMemory())
    signal = next(m for m in r["messages"] if m["kind"] == "signal")
    assert signal["data"]["tendance"] == "derive" and signal["data"]["niveau"] == "rouge"


def test_closing_week_is_not_an_alert(monkeypatch):
    for name, fn in personas.PERSONAS["closing"].items():
        monkeypatch.setattr(contracts, name, fn)
    store = InMemoryMemory()
    r = council.run("ichane", "semaine", llm=ScriptedLLM(), store=store)

    signal = next(m for m in r["messages"] if m["kind"] == "signal")
    assert signal["data"]["tendance"] == "pic_passe" and signal["data"]["niveau"] == "vert"
    assert ("analyse", "question") not in [(m["author"], m["kind"]) for m in r["messages"]]
    assert store.list_actions("ichane", "proposed") == []     # ni bloc ni expérience proposés
    assert "pas de dérive" in r["final_message"]
    assert guardrails.check_text(r["final_message"]) == []
