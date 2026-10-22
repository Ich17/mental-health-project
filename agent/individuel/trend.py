"""Dérive de fond ou pic ponctuel ? Calcul déterministe (pas de LLM).

Une semaine chargée suivie d'un retour à la normale (closing, clôture trimestrielle)
n'est pas une dérive : alerter à chaque closing ferait désinstaller l'app.
On compare chacune des 2 dernières semaines à la base personnelle (médiane des
4 semaines d'avant) :

| S-2 basse | S-1 basse | Tendance |
|---|---|---|
| oui | oui | `derive` : la récupération reste basse, on alerte |
| oui | non | `pic_passe` : la récupération est revenue, pas d'alerte |
| non | oui | `pic_attendu` si un contexte connu l'explique (ex. clôture), sinon `baisse_recente` |
| non | non | `stable` |

Une semaine est « basse » si sa récupération moyenne est inférieure de plus de 15 % à la base.
Le contexte vient du champ facultatif `context` des métriques journalières.
"""
from __future__ import annotations

from statistics import mean, median

WEEK = 7
DROP = 0.15
BASE_WEEKS = 4
CONTEXT_LABELS = {"cloture_trimestrielle": "clôture trimestrielle", "closing": "closing"}


def _week(rows: list[dict], label: str) -> dict:
    contexts = sorted({r["context"] for r in rows if r.get("context")})
    return {
        "semaine": label,
        "du": rows[0]["date"], "au": rows[-1]["date"],
        "recuperation": round(mean(r["recovery"] for r in rows), 1),
        "heures_reunion": round(mean(r["meeting_hours"] for r in rows), 1),
        "contexte": [CONTEXT_LABELS.get(c, c) for c in contexts],
    }


def assess_trend(rows: list[dict]) -> dict:
    """`rows` : métriques journalières triées par date (au moins 3 semaines)."""
    rows = [r for r in rows if r.get("recovery") is not None]
    if len(rows) < 3 * WEEK:
        return {"tendance": "inconnue", "explication": "Moins de 3 semaines de données : pas de comparaison possible."}

    base_rows = rows[-(2 + BASE_WEEKS) * WEEK:-2 * WEEK]
    base_weeks = [base_rows[i:i + WEEK] for i in range(0, len(base_rows) - WEEK + 1, WEEK)]
    base = round(median(mean(r["recovery"] for r in w) for w in base_weeks), 1)
    s2, s1 = _week(rows[-2 * WEEK:-WEEK], "S-2"), _week(rows[-WEEK:], "S-1")
    low2, low1 = (w["recuperation"] < base * (1 - DROP) for w in (s2, s1))

    def ecart(w):
        return round(100 * (w["recuperation"] - base) / base)

    def ctx(w):
        return f" ({', '.join(w['contexte'])})" if w["contexte"] else ""

    if low2 and low1:
        tendance = "derive"
        explication = (f"Récupération basse deux semaines de suite : {ecart(s2):+d} % puis {ecart(s1):+d} % "
                       f"par rapport à la base ({base}). Ce n'est pas un pic ponctuel.")
    elif low2:
        tendance = "pic_passe"
        explication = (f"Baisse ponctuelle la semaine du {s2['du']}{ctx(s2)} : {ecart(s2):+d} %, puis retour "
                       f"à {s1['recuperation']} cette semaine pour une base à {base} : pas de dérive de fond.")
    elif low1 and s1["contexte"]:
        tendance = "pic_attendu"
        explication = (f"Baisse cette semaine ({ecart(s1):+d} %) pendant un pic de charge attendu{ctx(s1)}. "
                       "À revérifier la semaine prochaine : la récupération doit remonter.")
    elif low1:
        tendance = "baisse_recente"
        explication = (f"Baisse cette semaine ({ecart(s1):+d} % par rapport à la base {base}), "
                       "sans contexte connu. À surveiller : si elle continue, c'est une dérive.")
    else:
        tendance = "stable"
        explication = f"Récupération proche de la base ({base}) les deux dernières semaines."

    return {"tendance": tendance, "base_recuperation": base, "semaines": [s2, s1], "explication": explication}
