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


MIN_BLOCK_DAYS = 2      # en dessous : trop tôt pour conclure
EFFECT_POINTS = 5       # écart de récupération (points) à partir duquel on parle d'effet


def evaluate_blocks(ctx: RunContext):
    """Effet des blocs d'agenda acceptés : récupération après les jours protégés vs les autres jours ouvrés.

    La ligne du jour J contient la récupération de la nuit suivante (contracts.get_daily_metrics),
    donc un bloc posé le jour J se lit directement sur la ligne J.
    """
    rows = {r["date"]: r for r in contracts.get_daily_metrics(ctx.user_id, 42) if r.get("recovery") is not None}
    blocks = [a for a in ctx.store.list_actions(ctx.user_id)
              if a["kind"] == "calendar_block" and a["status"] in ("accepted", "done")]
    by_purpose: dict[str, set[str]] = {}
    for b in blocks:
        day = b["payload"]["start"][:10]
        if day in rows:
            by_purpose.setdefault(b["payload"].get("purpose", "autre"), set()).add(day)
    all_block_days = set().union(*by_purpose.values()) if by_purpose else set()
    others = [r for d, r in rows.items() if d not in all_block_days and date.fromisoformat(d).weekday() < 5]

    results = []
    for purpose, days in sorted(by_purpose.items()):
        with_block = [rows[d] for d in sorted(days)]
        res = {"bloc": purpose, "jours_avec_bloc": len(with_block), "jours_comparables": len(others)}
        if len(with_block) < MIN_BLOCK_DAYS or len(others) < MIN_BLOCK_DAYS:
            results.append({**res, "verdict": "trop tôt", "note": f"au moins {MIN_BLOCK_DAYS} jours avec bloc nécessaires"})
            continue
        rec_with, rec_other = mean(r["recovery"] for r in with_block), mean(r["recovery"] for r in others)
        mh_with, mh_other = mean(r["meeting_hours"] for r in with_block), mean(r["meeting_hours"] for r in others)
        diff = round(rec_with - rec_other)
        res.update(recuperation_avec_bloc=round(rec_with), recuperation_sans_bloc=round(rec_other),
                   ecart_points=diff, heures_reunion_avec=round(mh_with, 1), heures_reunion_sans=round(mh_other, 1),
                   verdict="efficace" if diff >= EFFECT_POINTS else "sans effet net")
        if mh_other - mh_with > 1:   # journées protégées plus légères : l'effet peut venir de la charge
            res["note"] = "les jours protégés étaient aussi moins chargés : effet à confirmer"
        results.append(res)
    return {"blocs": results, "note": None if results else "aucun bloc accepté sur les 6 dernières semaines"}


def record_evaluation(ctx: RunContext, subject: str, verdict: str, effect_text: str, confidence: str):
    """Garde un verdict en mémoire (table hypotheses, facteur « evaluation:<sujet> ») : l'Analyse le relira."""
    if ctx.hypotheses_saved >= 3:
        raise ToolError("3 enregistrements maximum par run")
    factor = f"evaluation:{subject}"
    text = f"{verdict} : {effect_text}"
    known = ctx.store.get_memory(ctx.user_id)["hypotheses"]
    if any(h["factor"] == factor and h["effect_text"] == text for h in known):
        return {"deja_enregistre": True}
    ctx.hypotheses_saved += 1
    hid = ctx.store.save_hypothesis(ctx.user_id, factor=factor, effect_text=text,
                                    effect_size=0.0, confidence=confidence)
    return {"hypothesis_id": hid}


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
    Tool("evaluate_blocks", "Mesure l'effet des blocs d'agenda acceptés (déjeuner, sport…) : récupération après les "
         "jours protégés vs les autres jours ouvrés, avec la charge de réunions pour comparer à charge égale.",
         _obj(), evaluate_blocks),
    Tool("record_evaluation", "Garde en mémoire le verdict d'une action ou d'une expérience (3 max par run).",
         _obj({"subject": {"type": "string", "description": "ex. bloc_dejeuner, experience_3"},
               "verdict": {"type": "string", "enum": ["efficace", "sans effet net", "trop tôt"]},
               "effect_text": {"type": "string", "description": "effet chiffré en une phrase"},
               "confidence": {"type": "string", "enum": ["faible", "moyenne", "forte"]}},
              ["subject", "verdict", "effect_text", "confidence"]), record_evaluation),
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
    "evaluateur": ["get_memory", "evaluate_experiment", "evaluate_blocks", "record_evaluation"],
    "analyse": ["get_drivers", "get_memory", "save_hypothesis"],
    "action": ["get_free_slots", "propose_block", "start_experiment", "draft_message"],
}

