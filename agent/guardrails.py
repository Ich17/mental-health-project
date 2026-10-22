"""Contrôles déterministes (CLAUDE.md §3), appliqués par le code.

Le Gardien est un agent LLM, mais ces règles-là ne dépendent pas de son
jugement : si l'une échoue, la proposition est refusée quoi que dise le LLM.
"""
from __future__ import annotations

import re
import unicodedata

# Vocabulaire interdit : on parle de récupération, de charge, de fatigue.
# Jamais d'émotion ni d'état psychique (AI Act), jamais de diagnostic.
FORBIDDEN = {
    r"\bstress(e|é|ée|és)?\b": "« stress » : parler de charge ou de récupération",
    r"\bemotion": "« émotion » : interdit (AI Act)",
    r"\bhumeur": "« humeur » : interdit (AI Act)",
    r"\banxi": "« anxiété » : vocabulaire médical ou émotionnel",
    r"\bdepress": "« dépression » : vocabulaire médical",
    r"\bdiagnosti": "« diagnostic » : l'agent ne pose aucun diagnostic",
    r"\b(tu es|vous etes|tu fais|vous faites) (en )?(un )?burn.?out": "affirmer un burn-out = diagnostic",
    r"\bmoral\b": "« moral » : état émotionnel",
}

# Orientation obligatoire quand la charge est durablement rouge.
ORIENTATION = re.compile(r"medecin du travail|psy|cellule d.ecoute|mutuelle", re.I)
RED_DAYS_FOR_ORIENTATION = 3

# Un message RH ne doit jamais citer un petit effectif ni un identifiant.
SMALL_COUNT = re.compile(r"\b([1-7])\s+(personnes?|salari[ée]s?|collaborat|membres?)", re.I)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def check_text(text: str) -> list[str]:
    t = _norm(text)
    return [why for pattern, why in FORBIDDEN.items() if re.search(pattern, t)]


def check_plan(actions: list[dict], message: str = "") -> list[str]:
    """Plan du Coach : actions proposées + texte éventuel."""
    issues = check_text(message)
    for a in actions:
        p = a["payload"]
        if a["kind"] == "calendar_block":
            if p.get("title") != "Occupé" or p.get("visibility") != "private":
                issues.append("bloc d'agenda : titre « Occupé » et visibilité privée obligatoires")
            if p.get("start", "") >= p.get("end", ""):
                issues.append(f"bloc d'agenda incohérent : {p.get('start')} → {p.get('end')}")
        if a["kind"] == "draft_message":
            issues += [f"brouillon : {i}" for i in check_text(p.get("text", ""))]
        for field in ("purpose", "rule_text", "text"):
            if field in p:
                issues += check_text(str(p[field]))
    return sorted(set(issues))


def check_orientation(red_days: int, message: str) -> list[str]:
    if red_days >= RED_DAYS_FOR_ORIENTATION and not ORIENTATION.search(_norm(message)):
        return [f"{red_days} jours rouges prévus : le message doit orienter "
                "(médecin du travail, psy pris en charge par la mutuelle)"]
    return []


def check_hr_text(text: str, known_user_ids: list[str] = ()) -> list[str]:
    issues = check_text(text)
    if SMALL_COUNT.search(text):
        issues.append("effectif de moins de 8 personnes cité : risque de ré-identification")
    for uid in known_user_ids:
        if uid and re.search(rf"\b{re.escape(uid)}\b", text, re.I):
            issues.append("identifiant individuel dans un message RH")
    return issues
