"""Outils des agents individuels (Détection, Analyse, Action) et leurs droits.

Principe de confidentialité appliqué par le code :
- l'identité de la personne (user_id) vient du contexte du run,
  jamais d'un argument choisi par le LLM : un agent ne peut pas lire
  les données de quelqu'un d'autre ;
- chaque agent ne reçoit que les outils de sa ligne dans AGENT_TOOLS ;
- aucun outil n'écrit dans l'agenda. Les outils d'action remplissent un
  brouillon de plan, enregistré seulement si la revue du code l'approuve, puis
  exécuté seulement si l'utilisateur clique (route API).
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

import contracts
from agent.individuel import trend
from agent.toolkit import RunContext, Tool, ToolError, obj as _obj


# ---------------------------------------------------------------------------
# Données (lecture seule)
# ---------------------------------------------------------------------------

def get_daily_metrics(ctx: RunContext, days: int = 42):
    return contracts.get_daily_metrics(ctx.user_id, min(int(days), 90))


def get_drivers(ctx: RunContext):
    return contracts.get_drivers(ctx.user_id)


def forecast_week(ctx: RunContext):
    return contracts.forecast_week(ctx.user_id)


def get_free_slots(ctx: RunContext, date: str):
    return contracts.get_free_slots(ctx.user_id, date)


def assess_trend(ctx: RunContext):
    return trend.assess_trend(contracts.get_daily_metrics(ctx.user_id, 42))


# ---------------------------------------------------------------------------
# Mémoire
# ---------------------------------------------------------------------------

def get_memory(ctx: RunContext):
    return ctx.store.get_memory(ctx.user_id)


def evaluate_experiment(ctx: RunContext, experiment_id: int):
    exp = ctx.store.get_experiment(ctx.user_id, int(experiment_id))
    if exp is None:
        raise ToolError(f"expérience {experiment_id} introuvable")
    if exp.get("result_recovery") is not None:
        return exp
    rows = [r for r in contracts.get_daily_metrics(ctx.user_id, 90)
            if exp["start_date"] <= r["date"] <= exp["end_date"] and r.get("recovery") is not None]
    if str(date.today()) <= str(exp["end_date"]) or not rows:
        return {**exp, "verdict": "en cours ou pas assez de données"}
    result = round(mean(r["recovery"] for r in rows), 1)
    base = exp.get("baseline_recovery") or result
    change = round(100 * (result - base) / base, 1) if base else 0
    return {**exp, "result_recovery": result, "change_pct": change,
            "verdict": "garder" if change >= 5 else "abandonner"}


def save_hypothesis(ctx: RunContext, factor: str, effect_text: str, effect_size: float, confidence: str):
    if ctx.hypotheses_saved >= 2:
        raise ToolError("2 hypothèses maximum par run")
    ctx.hypotheses_saved += 1
    hid = ctx.store.save_hypothesis(ctx.user_id, factor=factor, effect_text=effect_text,
                                    effect_size=float(effect_size), confidence=confidence)
    return {"hypothesis_id": hid}


# ---------------------------------------------------------------------------
# Actions (brouillon de plan, rien n'est exécuté ici)
# ---------------------------------------------------------------------------

PURPOSES = ["dejeuner", "sport", "focus", "recuperation", "rendez_vous_sante"]


def _draft(ctx: RunContext, kind: str, payload: dict) -> dict:
    ctx.draft_actions.append({"kind": kind, "payload": payload})
    return {"draft_index": len(ctx.draft_actions) - 1, "kind": kind, "payload": payload,
            "note": "brouillon : sera relu par le Gardien puis proposé à l'utilisateur"}


def propose_block(ctx: RunContext, date: str, start: str, end: str, purpose: str):
    if purpose not in PURPOSES:
        raise ToolError(f"purpose doit être l'un de {PURPOSES}")
    s, e = f"{date}T{start}:00", f"{date}T{end}:00"
    slots = contracts.get_free_slots(ctx.user_id, date)
    if not any(sl["start"] <= s and e <= sl["end"] for sl in slots):
        raise ToolError(f"{start}-{end} n'est pas dans un créneau libre. Créneaux : {slots}")
    # Titre et visibilité imposés par le code (CLAUDE.md §3).
    return _draft(ctx, "calendar_block", {"start": s, "end": e, "purpose": purpose,
                                          "title": "Occupé", "visibility": "private"})


def start_experiment(ctx: RunContext, rule_text: str, days: int = 14):
    recent = [r["recovery"] for r in contracts.get_daily_metrics(ctx.user_id, 14)
              if r.get("recovery") is not None]
    start = date.today() + timedelta(days=1)
    return _draft(ctx, "experiment", {
        "rule_text": rule_text, "start_date": str(start),
        "end_date": str(start + timedelta(days=int(days))),
        "baseline_recovery": round(mean(recent), 1) if recent else None})


def draft_message(ctx: RunContext, recipient: str, text: str):
    if recipient not in ("manager", "medecin_du_travail"):
        raise ToolError("recipient : manager ou medecin_du_travail")
    return _draft(ctx, "draft_message", {"recipient": recipient, "text": text,
                                         "note": "jamais envoyé automatiquement"})



# ---------------------------------------------------------------------------
# Registre et droits
# ---------------------------------------------------------------------------

TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("get_daily_metrics", "Indicateurs de charge du jour J et récupération à J+1, un objet par jour.",
         _obj({"days": {"type": "integer", "description": "nombre de jours (max 90)"}}), get_daily_metrics),
    Tool("get_drivers", "Top 3 des facteurs qui pèsent sur la récupération de la personne (hypothèses chiffrées).",
         _obj(), get_drivers),
    Tool("forecast_week", "Récupération prévue pour les prochains jours à partir de l'agenda (vert/orange/rouge).",
         _obj(), forecast_week),
    Tool("assess_trend", "Dérive de fond ou pic ponctuel ? Compare les 2 dernières semaines à la base personnelle "
         "(calcul déterministe) : derive, pic_passe, pic_attendu, baisse_recente ou stable, avec l'explication.",
         _obj(), assess_trend),
    Tool("get_free_slots", "Créneaux libres d'une journée.",
         _obj({"date": {"type": "string", "description": "AAAA-MM-JJ"}}, ["date"]), get_free_slots),
    Tool("get_memory", "Mémoire : hypothèses, expériences passées et leur effet, feedback, actions récentes.",
         _obj(), get_memory),
    Tool("evaluate_experiment", "Mesure l'effet d'une expérience (récupération pendant vs avant).",
         _obj({"experiment_id": {"type": "integer"}}, ["experiment_id"]), evaluate_experiment),
    Tool("save_hypothesis", "Enregistre une hypothèse en mémoire (2 max par run).",
         _obj({"factor": {"type": "string"}, "effect_text": {"type": "string"},
               "effect_size": {"type": "number"},
               "confidence": {"type": "string", "enum": ["faible", "moyenne", "forte"]}},
              ["factor", "effect_text", "effect_size", "confidence"]), save_hypothesis),
    Tool("propose_block", "Ajoute au plan un bloc d'agenda dans un créneau libre (titre « Occupé » imposé).",
         _obj({"date": {"type": "string", "description": "AAAA-MM-JJ"},
               "start": {"type": "string", "description": "HH:MM"},
               "end": {"type": "string", "description": "HH:MM"},
               "purpose": {"type": "string", "enum": PURPOSES}},
              ["date", "start", "end", "purpose"]), propose_block),
    Tool("start_experiment", "Ajoute au plan une expérience personnelle (règle testée N jours, puis mesurée).",
         _obj({"rule_text": {"type": "string"}, "days": {"type": "integer"}}, ["rule_text"]), start_experiment),
    Tool("draft_message", "Rédige un brouillon factuel pour le manager ou le médecin du travail (jamais envoyé).",
         _obj({"recipient": {"type": "string", "enum": ["manager", "medecin_du_travail"]},
               "text": {"type": "string"}}, ["recipient", "text"]), draft_message),
]}

AGENT_TOOLS: dict[str, list[str]] = {
    "detection": ["get_daily_metrics", "forecast_week", "assess_trend"],
    "analyse": ["get_drivers", "get_memory", "evaluate_experiment", "save_hypothesis"],
    "action": ["get_free_slots", "propose_block", "start_experiment", "draft_message"],
}

