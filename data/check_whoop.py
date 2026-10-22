"""Contrôle qualité et nettoyage des données WHOOP (Python seul, sans pandas).

    python -m data.check_whoop        # lit data/raw/, affiche un bilan, écrit whoop_daily_clean.json

Le bilan n'affiche que des comptes et des fourchettes : tu peux le copier dans le chat sans
partager tes données jour par jour.
"""
import json
import statistics as st
from datetime import date, timedelta
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw"

# Bornes physiologiques plausibles : en dehors = erreur de capteur, la valeur est retirée.
BOUNDS = {"recovery": (0, 100), "hrv": (5, 250), "rhr": (30, 110), "sleep_h": (1.5, 14),
          "sleep_consistency": (0, 100), "strain": (0, 21)}


def _load(name):
    f = RAW / f"whoop_{name}.json"
    return json.loads(f.read_text()) if f.exists() else []


def raw_report() -> list[str]:
    """Ce qui est écarté avant même la table journalière (siestes, non scorés, calibrage)."""
    rec, sleep, cyc = _load("recovery"), _load("sleep"), _load("cycle")
    states = lambda xs: {s: sum(x.get("score_state") == s for x in xs) for s in {x.get("score_state") for x in xs}}  # noqa: E731
    calib = sum(bool((r.get("score") or {}).get("user_calibrating")) for r in rec)
    tz = sorted({s.get("timezone_offset") for s in sleep if s.get("timezone_offset")})
    return [
        f"Exports bruts : {len(rec)} recovery, {len(sleep)} sleep, {len(cyc)} cycle",
        f"  recovery par état : {states(rec)} ; en calibrage : {calib}",
        f"  sleep : {sum(bool(s.get('nap')) for s in sleep)} siestes écartées ; états : {states(sleep)}",
        f"  fuseaux horaires vus : {', '.join(tz) or 'aucun'}"
        + ("  ← voyage ? les heures sont converties en heure locale" if len(tz) > 1 else ""),
    ]


def clean(rows: list[dict]) -> tuple[list[dict], list[str]]:
    notes, out = [], []
    seen = set()
    for r in sorted(rows, key=lambda r: r["date"]):
        if r["date"] in seen:
            notes.append(f"doublon retiré : {r['date']}")
            continue
        seen.add(r["date"])
        r = dict(r)
        for k, (lo, hi) in BOUNDS.items():
            v = r.get(k)
            if v is not None and not lo <= v <= hi:
                notes.append(f"{k} hors bornes ({v}) le {r['date']} → retiré")
                r[k] = None
        if r.get("strain") == 0:
            r["strain"] = None  # cycle manquant, pas un vrai 0
        out.append(r)
    return out, notes


def summary(rows: list[dict]) -> list[str]:
    if not rows:
        return ["Aucun jour : vérifie que `python -m data.whoop fetch` a bien tourné."]
    days = [date.fromisoformat(r["date"]) for r in rows]
    span = (days[-1] - days[0]).days + 1
    have = set(days)
    missing = [days[0] + timedelta(i) for i in range(span) if days[0] + timedelta(i) not in have]
    gaps, run = 0, 0  # plus long trou consécutif
    for i in range(span):
        run = run + 1 if days[0] + timedelta(i) not in have else 0
        gaps = max(gaps, run)
    lines = [f"Jours : {len(rows)} sur {span} ({len(missing)} manquants, plus long trou : {gaps} j)"]
    for k in BOUNDS:
        v = [r[k] for r in rows if r.get(k) is not None]
        if len(v) > 2:
            m, sd = st.mean(v), st.stdev(v)
            out = sum(abs(x - m) > 3 * sd for x in v)
            lines.append(f"  {k:17s} moy {m:6.1f}  écart-type {sd:5.1f}  min {min(v):6.1f}  max {max(v):6.1f}"
                         f"  vides {len(rows) - len(v):2d}  atypiques {out}")
    beds = [r["bedtime"][11:16] for r in rows if r.get("bedtime")]
    if beds:
        lines.append(f"  coucher : le plus tôt {min(beds, key=lambda b: (b < '12', b))}, "
                     f"le plus tard {max(beds, key=lambda b: (b < '12', b))}")
    return lines


if __name__ == "__main__":
    from data.whoop import to_daily

    rows = to_daily(_load("recovery"), _load("sleep"), _load("cycle"))
    cleaned, notes = clean(rows)
    (RAW / "whoop_daily_clean.json").write_text(json.dumps(cleaned, indent=1))
    print("\n".join(raw_report() + [""] + summary(cleaned)))
    print("\nCorrections :" if notes else "\nAucune correction nécessaire.")
    for n in notes:
        print("  " + n)
    print("\n→ data/raw/whoop_daily_clean.json")
