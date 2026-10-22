"""Contrôle qualité et nettoyage des données WHOOP (Python seul, sans pandas).

    python -m data.check_whoop        # lit data/raw/, affiche un bilan, écrit whoop_daily_clean.json/.csv

Le bilan n'affiche que des comptes et des fourchettes : tu peux le copier dans le chat sans
partager tes données jour par jour.
"""
import json
import statistics as st
from datetime import date, datetime, timedelta
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw"

# Bornes physiologiques plausibles : en dehors = erreur de capteur, la valeur est retirée.
BOUNDS = {"recovery": (0, 100), "hrv": (5, 250), "rhr": (30, 110), "sleep_h": (1.5, 14),
          "sleep_consistency": (0, 100), "strain": (0, 21)}

# Colonnes de travail du jour D (métadonnées, jamais de contenu). Vides pour l'instant :
# elles seront simulées en cohérence avec les données de santé.
# « nuit » = de 19h le jour D à 6h le jour D+1, rattachée au jour D.
WORK_COLUMNS = [
    "emails_sent",            # nb de mails envoyés dans la journée
    "emails_received",        # nb de mails reçus dans la journée
    "n_meetings",             # nb de réunions dans la journée
    "meeting_hours",          # durée totale des réunions (heures)
    "emails_received_night",  # nb de mails reçus entre 19h et 6h
    "emails_sent_night",      # nb de mails envoyés entre 19h et 6h
    "last_minute_meetings",   # nb de réunions ajoutées moins de 24h avant leur début
]


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


METRICS = ["recovery", "hrv", "rhr", "sleep_h", "sleep_consistency", "strain"]


def _neighbours_mean(rows: list[dict], i: int, k: str):
    """Moyenne du jour valide précédent et du suivant (ou de l'un des deux en bordure)."""
    vals = []
    for step in (-1, 1):
        j = i + step
        while 0 <= j < len(rows) and (rows[j].get(k) is None or k in rows[j]["imputed"]):
            j += step
        if 0 <= j < len(rows):
            vals.append(rows[j][k])
    return round(st.mean(vals), 1 if k != "sleep_h" else 2) if vals else None


def _bed_hours(b: str) -> float:  # 01:30 → 25.5, pour moyenner autour de minuit
    h = int(b[11:13]) + int(b[14:16]) / 60
    return h + 24 if h < 12 else h


def clean(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Retire doublons et erreurs, puis comble les trous par la moyenne des jours voisins.

    Chaque ligne a une colonne `imputed` : la liste des champs estimés (vide = mesure réelle).
    """
    notes, by_day = [], {}
    for r in sorted(rows, key=lambda r: r["date"]):
        if r["date"] in by_day:
            notes.append(f"doublon retiré : {r['date']}")
            continue
        by_day[r["date"]] = {**r, "imputed": []}
    if not by_day:
        return [], notes
    first, last = date.fromisoformat(min(by_day)), date.fromisoformat(max(by_day))
    template = next(iter(by_day.values()))
    out = []
    for i in range((last - first).days + 1):
        d = (first + timedelta(i)).isoformat()
        if d not in by_day:
            notes.append(f"jour manquant {d} → estimé avec les jours voisins")
            by_day[d] = {"user_id": template["user_id"], "team_id": template["team_id"], "date": d,
                         **{k: None for k in METRICS}, "bedtime": None, "source": template["source"],
                         "imputed": METRICS + ["bedtime"]}
        r = by_day[d]
        for k, (lo, hi) in BOUNDS.items():
            v = r.get(k)
            if v is not None and not lo <= v <= hi:
                notes.append(f"{k} hors bornes ({v}) le {d} → estimé")
                r[k] = None
        if r.get("strain") is None or r["strain"] < 1:
            if "strain" not in r["imputed"]:
                notes.append(f"strain {r.get('strain')} le {d} : montre pas portée → estimé")
        if r.get("sleep_h") is not None and r["sleep_h"] < 3 and "hrv" not in r["imputed"]:
            notes.append(f"HRV le {d} mesurée sur {r['sleep_h']} h de sommeil : peu fiable → estimée")
            r["hrv"] = None
        r["imputed"] = sorted(set(r["imputed"]) | {k for k in METRICS if r.get(k) is None}
                              | ({"strain"} if (r.get("strain") or 0) < 1 else set()))
        out.append(r)
    for i, r in enumerate(out):
        for k in r["imputed"]:
            if k in METRICS:
                r[k] = _neighbours_mean(out, i, k)
        if "bedtime" in r["imputed"]:
            beds = [_bed_hours(out[j]["bedtime"]) for j in (i - 1, i + 1)
                    if 0 <= j < len(out) and out[j].get("bedtime") and "bedtime" not in out[j]["imputed"]]
            if beds:
                h = st.mean(beds)
                dt = datetime.fromisoformat(r["date"]) - timedelta(days=1) + timedelta(hours=h)
                r["bedtime"] = dt.isoformat(timespec="minutes")
    for r in out:
        r["imputed"] = ",".join(r["imputed"])
        for k in WORK_COLUMNS:
            r.setdefault(k, None)
    return out, notes


def write_csv(rows: list[dict], path: Path) -> None:
    """CSV lisible dans Excel français (séparateur ; et virgule décimale)."""
    cols = ["user_id", "team_id", "date", *METRICS, "bedtime", "source", "imputed", *WORK_COLUMNS]
    fmt = lambda v: str(v).replace(".", ",") if isinstance(v, float) else ("" if v is None else str(v))  # noqa: E731
    lines = [";".join(cols)] + [";".join(fmt(r.get(c)) for c in cols) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


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
    est = sum(bool(r.get("imputed")) for r in rows)
    lines = [f"Jours : {len(rows)} sur {span} ({len(missing)} manquants, plus long trou : {gaps} j ; "
             f"{est} jours avec au moins une valeur estimée)"]
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
    write_csv(cleaned, RAW / "whoop_daily_clean.csv")
    print("\n".join(raw_report() + [""] + summary(cleaned)))
    print("\nCorrections :" if notes else "\nAucune correction nécessaire.")
    for n in notes:
        print("  " + n)
    print("\n→ data/raw/whoop_daily_clean.json et .csv (colonne `imputed` = champs estimés ; "
          "colonnes de travail vides, à simuler)")
