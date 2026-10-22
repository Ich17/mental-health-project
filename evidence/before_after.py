"""Preuve « avant / après » pour le dossier du hackathon (isolé : ne touche ni api/, ni agent/, ni data/).

    python -m evidence.before_after          # lit data/raw/team_daily.json (ou .csv), écrit evidence/out/rapport.html
    python -m evidence.before_after --demo   # sans données perso : santé d'Ichane remplacée par une série de démo

Deux parties, à ne pas mélanger :
1. AVANT (jours 1 → 25) — backtest réel. Chaque matin, le modèle ne voit que le passé (récup, HRV, sommeil
   du jour + agenda prévu du jour) et estime le risque que la récup du lendemain soit rouge (< 34, zone rouge
   Whoop). On compare ses alertes aux jours rouges qui sont vraiment arrivés. Aucune donnée future n'est utilisée.
2. APRÈS (jours 26 → 50) — scénario simulé. Mêmes personnes, mêmes jours. Sur chaque jour signalé, l'agent
   propose d'alléger l'agenda (déplacer des réunions jusqu'au niveau habituel de la personne, 2 h max) et de
   bloquer un créneau « Occupé ». Hypothèses écrites dans HYP et dans le rapport.

Vocabulaire : récupération, charge, fatigue. Vue équipes = agrégats seulement, équipes de moins de 8 personnes
masquées (règle n ≥ 8).
"""
import argparse
import json
import math
import random
import statistics as st
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = Path(__file__).resolve().parent / "out"

RED = 34              # zone rouge Whoop (récupération 0-33 %)
RISK_FLAG = 0.35      # alerte si P(récup du lendemain < 34) ≥ 35 %, fixé avant de regarder les résultats
MIN_TRAIN = 10        # jours d'historique perso avant les premières alertes (avant : modèle commun)
PRIOR_W = 8.0         # poids du modèle commun dans le modèle perso (démarrage à froid)
BEFORE, AFTER = (1, 25), (26, 50)
MIN_GROUP = 8
HYP = {"acceptance": 0.6,        # part des propositions acceptées en 1 clic
       "causal_share": 0.5,      # part du lien charge → récup observé qu'on considère causale
       "max_cut_h": 2.0}         # heures de réunion déplacées au plus par jour signalé
SCENARIOS = {"prudent": 0.25, "central": 0.5, "optimiste": 1.0}
BODY = ["recovery", "hrv", "sleep_h"]
AGENDA = ["planned_h", "weekend"]


# ---------- données ----------

def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return v


def load_rows(path: Path | None) -> list[dict]:
    for p in ([path] if path else [RAW / "team_daily.json", RAW / "team_daily.csv"]):
        if p and p.exists():
            if p.suffix == ".json":
                return json.loads(p.read_text(encoding="utf-8"))
            lines = p.read_text(encoding="utf-8-sig").splitlines()
            cols = lines[0].split(";")
            return [{c: (v if c in ("user_id", "team_id", "date", "bedtime") else _num(v))
                     for c, v in zip(cols, ln.split(";"))} for ln in lines[1:] if ln.strip()]
    raise SystemExit("Pas de data/raw/team_daily.json : lance d'abord `python -m data.simulate_daily` "
                     "(ou ce script avec --demo).")


def demo_rows(seed: int = 7) -> list[dict]:
    """Cohorte complète sans données perso : la santé « Ichane » est une série de démonstration."""
    from data.simulate_daily import simulate_cohort, simulate_health
    rng, end = random.Random(seed), date(2026, 10, 21)
    fake = [{"date": (end - timedelta(57 - i)).isoformat(), "recovery": rng.gauss(60, 18),
             "hrv": rng.gauss(55, 12), "rhr": rng.gauss(57, 4), "sleep_h": rng.gauss(6.8, 0.8),
             "sleep_consistency": rng.gauss(70, 10), "strain": rng.gauss(11, 3),
             "bedtime": (end - timedelta(58 - i)).isoformat() + "T23:50"} for i in range(58)]
    return simulate_cohort(simulate_health(fake, "ichane", "finance", rng), seed)


def by_person(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: (r["user_id"], r["date"])):
        mh, nm, lm = (r.get(k) or 0 for k in ("meeting_hours", "n_meetings", "last_minute_meetings"))
        # Agenda connu le matin = réunions déjà posées la veille (on retire les ajouts de dernière minute).
        planned = mh * (1 - lm / nm) if nm else 0.0
        out.setdefault(r["user_id"], []).append(
            {**r, "planned_h": planned, "weekend": float(date.fromisoformat(r["date"]).weekday() >= 5)})
    return out


# ---------- modèle (régression ridge, Python seul) ----------

def solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[c][c]:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] if m[i][i] else 0.0 for i in range(n)]


def fit(xs: list[list[float]], ys: list[float], prior: list[float], lam: float) -> list[float]:
    """min ||y − Xb||² + lam·||b − prior||² (pas de pénalité sur la constante)."""
    k = len(prior)
    xtx = [[sum(x[i] * x[j] for x in xs) + (lam if i == j and i > 0 else 0) for j in range(k)] for i in range(k)]
    xty = [sum(x[i] * y for x, y in zip(xs, ys)) + (lam * prior[i] if i > 0 else 0) for i in range(k)]
    return solve(xtx, xty)


def pairs(days: list[dict], feats: list[str], upto: int) -> tuple[list, list]:
    """(features du jour d, récup de d+1) pour toutes les paires dont le lendemain ≤ upto (index 0-based)."""
    xs, ys = [], []
    for i in range(min(upto, len(days) - 1)):
        if days[i + 1].get("recovery") is None or any(days[i].get(f) is None for f in feats):
            continue
        xs.append([1.0] + [days[i][f] for f in feats])
        ys.append(days[i + 1]["recovery"])
    return xs, ys


def walk_forward(people: dict[str, list[dict]], feats: list[str]) -> dict[str, list[dict]]:
    """Pour chaque matin d : modèle entraîné sur le passé seulement → risque de récup rouge à d+1."""
    n_days = max(len(d) for d in people.values())
    preds = {u: [None] * len(d) for u, d in people.items()}
    coefs = {}
    for i in range(1, n_days - 1):  # matin du jour index i, on prédit i+1
        pool_x, pool_y = [], []
        for d in people.values():
            x, y = pairs(d, feats, i)
            pool_x += x
            pool_y += y
        if len(pool_y) < 2 * (len(feats) + 1):
            continue
        common = fit(pool_x, pool_y, [0.0] * (len(feats) + 1), 1.0)
        for u, d in people.items():
            if i + 1 >= len(d) or any(d[i].get(f) is None for f in feats):
                continue
            x, y = pairs(d, feats, i)
            b = fit(x, y, common, PRIOR_W * max(1, MIN_TRAIN - len(y) + 1)) if x else common
            res = [yy - sum(bb * xx for bb, xx in zip(b, row)) for row, yy in zip(x, y)]
            sd = st.pstdev(res) if len(res) >= MIN_TRAIN else st.pstdev(pool_y) * 0.9
            sd = max(sd, 6.0)
            mu = b[0] + sum(bb * d[i][f] for bb, f in zip(b[1:], feats))
            risk = 0.5 * (1 + math.erf((RED - mu) / (sd * math.sqrt(2))))
            preds[u][i + 1] = {"pred": mu, "risk": risk, "flag": risk >= RISK_FLAG}
            coefs[(u, i)] = b
    return preds, coefs


# ---------- évaluation ----------

def scores(people, preds, lo, hi) -> dict:
    tp = fp = fn = tn = 0
    for u, d in people.items():
        for j in range(lo - 1, min(hi, len(d))):
            p = preds[u][j]
            if p is None or d[j].get("recovery") is None:
                continue
            red = d[j]["recovery"] < RED
            tp += red and p["flag"]
            fn += red and not p["flag"]
            fp += (not red) and p["flag"]
            tn += (not red) and not p["flag"]
    n = tp + fp + fn + tn
    return {"reds": tp + fn, "caught": tp, "flags": tp + fp, "false_alarms": fp, "n": n,
            "recall": tp / (tp + fn) if tp + fn else 0, "precision": tp / (tp + fp) if tp + fp else 0,
            "base_rate": (tp + fn) / n if n else 0}


def load_slopes(people) -> dict[str, float]:
    """Pente perso « 1 h de réunion en plus le jour J → x points de récup à J+1 », jours ouvrés de la période
    AVANT seulement, rapprochée de la pente commune quand la personne a peu de jours (shrinkage)."""
    per, pool = {}, []
    for u, d in people.items():
        xy = [(d[i]["meeting_hours"] or 0, d[i + 1]["recovery"]) for i in range(BEFORE[1] - 1)
              if not d[i]["weekend"] and d[i + 1].get("recovery") is not None]
        mx, my = st.mean(x for x, _ in xy), st.mean(y for _, y in xy)
        dev = [(x - mx, y - my) for x, y in xy]
        pool += dev
        sxx = sum(x * x for x, _ in dev)
        per[u] = (sum(x * y for x, y in dev) / sxx if sxx else 0.0, len(dev))
    b_pool = sum(x * y for x, y in pool) / sum(x * x for x, _ in pool)
    return {u: (n * b + 10 * b_pool) / (n + 10) for u, (b, n) in per.items()}, b_pool


def counterfactual(people, preds, slopes, share, seed=11) -> dict[str, list]:
    """Récup « avec agent » sur la période APRÈS. Sur un jour signalé et accepté, les réunions prévues
    au-delà du niveau habituel de la personne sont déplacées (2 h max) ; gain = pente perso × heures × part causale."""
    rng = random.Random(seed)
    out = {}
    for u, d in people.items():
        wk = [x["planned_h"] for x in d[:BEFORE[1]] if not x["weekend"]]
        usual = st.median(wk) if wk else 0
        cf = [x.get("recovery") for x in d]
        for j in range(AFTER[0] - 1, min(AFTER[1], len(d))):
            p = preds[u][j]
            accepted = rng.random() < HYP["acceptance"]  # un tirage par jour : mêmes tirages dans chaque scénario
            if not (p and p["flag"] and accepted) or cf[j] is None or slopes[u] >= 0:
                continue
            cut = min(HYP["max_cut_h"], d[j - 1]["meeting_hours"] or 0)
            cf[j] = min(99, cf[j] + (-slopes[u]) * cut * share)
        out[u] = cf
    return out


def period_stats(people, series, lo, hi, users=None) -> dict:
    vals = [series[u][j] for u in (users or people) for j in range(lo - 1, min(hi, len(series[u])))
            if series[u][j] is not None]
    return {"avg": st.mean(vals) if vals else 0, "red_share": sum(v < RED for v in vals) / len(vals) if vals else 0,
            "red_days": sum(v < RED for v in vals), "n": len(vals)}


def corr_load_recovery(people) -> float:
    xs, ys = [], []
    for d in people.values():
        for i in range(len(d) - 1):
            if d[i + 1].get("recovery") is not None and not d[i]["weekend"]:
                xs.append(d[i].get("meeting_hours") or 0)
                ys.append(d[i + 1]["recovery"])
    return st.correlation(xs, ys)


# ---------- rapport ----------

def build(rows: list[dict], user: str, demo: bool) -> dict:
    people = by_person(rows)
    if user not in people:
        user = sorted(people)[0]
    full, coefs = walk_forward(people, BODY + AGENDA)
    body, _ = walk_forward(people, BODY)
    real = {u: [x.get("recovery") for x in d] for u, d in people.items()}
    slopes, b_pool = load_slopes(people)
    cfs = {name: counterfactual(people, full, slopes, s) for name, s in SCENARIOS.items()}
    cf = cfs["central"]
    teams = {}
    for u, d in people.items():
        teams.setdefault(d[0]["team_id"], []).append(u)
    first = people[user]
    dates = [x["date"] for x in first]

    team_view = []
    for t, us in sorted(teams.items()):
        if len(us) < MIN_GROUP:
            continue  # règle n ≥ 8
        weeks = []
        for w0 in range(0, AFTER[1], 7):
            lo, hi = w0 + 1, min(w0 + 7, AFTER[1])
            weeks.append({"from": lo, "real": period_stats(people, real, lo, hi, us)["avg"],
                          "agent": period_stats(people, cf, lo, hi, us)["avg"]})
        team_view.append({"team": t, "n_bucket": "8-15" if len(us) < 16 else "16+",
                          "before": period_stats(people, real, *BEFORE, us),
                          "after_real": period_stats(people, real, *AFTER, us),
                          "after_agent": period_stats(people, cf, *AFTER, us),
                          "weeks": weeks})

    me = {"days": [{"i": j + 1, "date": dates[j], "real": real[user][j], "agent": cf[user][j],
                    "risk": (full[user][j] or {}).get("risk"), "flag": bool((full[user][j] or {}).get("flag")),
                    "meeting_h": first[j].get("meeting_hours")} for j in range(min(AFTER[1], len(first)))],
          "before": period_stats(people, real, *BEFORE, [user]),
          "after_real": period_stats(people, real, *AFTER, [user]),
          "after_agent": period_stats(people, cf, *AFTER, [user]),
          "backtest": scores({user: first}, {user: full[user]}, MIN_TRAIN + 2, AFTER[1])}

    return {"demo": demo, "user": user, "n_people": len(people), "n_teams": len(team_view),
            "period": {"start": dates[0], "before_end": dates[BEFORE[1] - 1], "after_end": dates[min(AFTER[1], len(dates)) - 1]},
            "corr": corr_load_recovery(people), "slope": b_pool, "my_slope": slopes[user], "hyp": HYP, "red": RED, "risk_flag": RISK_FLAG,
            "backtest": {"before": scores(people, full, MIN_TRAIN + 2, BEFORE[1]),
                         "all": scores(people, full, MIN_TRAIN + 2, AFTER[1]),
                         "body_only": scores(people, body, MIN_TRAIN + 2, AFTER[1])},
            "cohort": {"before": period_stats(people, real, *BEFORE),
                       "after_real": period_stats(people, real, *AFTER),
                       "scenarios": {k: period_stats(people, v, *AFTER) for k, v in cfs.items()}},
            "teams": team_view, "me": me}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="sans données perso (santé d'Ichane simulée)")
    ap.add_argument("--input", type=Path, help="team_daily.json ou .csv (défaut : data/raw/)")
    ap.add_argument("--user", default="ichane")
    a = ap.parse_args()
    rows = demo_rows() if a.demo else load_rows(a.input)
    rep = build(rows, a.user, a.demo)
    OUT.mkdir(exist_ok=True)
    (OUT / "rapport.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    from evidence.render import render
    (OUT / "rapport.html").write_text(render(rep), encoding="utf-8")
    b, c = rep["backtest"]["all"], rep["cohort"]
    print(f"Backtest (jours {MIN_TRAIN + 2}-{AFTER[1]}) : {b['caught']}/{b['reds']} jours rouges signalés la veille "
          f"({b['recall']:.0%}), précision {b['precision']:.0%} ; corps seul : {rep['backtest']['body_only']['recall']:.0%}")
    print(f"Jours rouges période APRÈS : réel {c['after_real']['red_share']:.1%} → avec agent (scénario central) "
          f"{c['scenarios']['central']['red_share']:.1%}")
    print(f"→ {OUT / 'rapport.html'} (ouvre-le dans ton navigateur)")


if __name__ == "__main__":
    main()
