"""Résumé anonyme de vraies données WHOOP pour caler le simulateur (Python seul, sans pandas).

    python -m data.calibrate   # lit data/raw/whoop_daily.json → data/raw/whoop_calibration.json

Le résultat ne contient que des moyennes et écarts-types : aucune date, aucune ligne journalière.
"""
import json
import statistics as st
from datetime import date, datetime
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw"


def calibrate(path: str | Path = RAW / "whoop_daily.json") -> dict:
    """Agrégats à partir de lignes recovery_daily. Accepte aussi un fichier déjà agrégé."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        return data
    col = lambda k: [float(r[k]) for r in data if r.get(k) is not None]  # noqa: E731
    bed = [datetime.fromisoformat(str(r["bedtime"])) for r in data if r.get("bedtime")]
    bed_h = [b.hour + b.minute / 60 + (24 if b.hour < 12 else 0) for b in bed]
    rec = col("recovery")
    by_wd: dict[int, list[float]] = {}
    for r in data:
        by_wd.setdefault(date.fromisoformat(str(r["date"])[:10]).weekday(), []).append(float(r["recovery"]))
    cal = {
        "recovery_mean": st.mean(rec), "recovery_sd": st.stdev(rec),
        "hrv_median": st.median(col("hrv")), "rhr_mean": st.mean(col("rhr")), "rhr_sd": st.stdev(col("rhr")),
        "sleep_h_mean": st.mean(col("sleep_h")), "sleep_h_sd": st.stdev(col("sleep_h")),
        "sleep_consistency_mean": st.mean(col("sleep_consistency")),
        "strain_mean": st.mean(col("strain")), "bedtime_h": st.mean(bed_h) if bed_h else 23.8,
    }
    cal = {k: round(v, 2) for k, v in cal.items()}
    cal["weekday_recovery"] = [round(st.mean(by_wd[i]) - cal["recovery_mean"], 1) if i in by_wd else 0
                               for i in range(7)]
    cal["n_days"] = len(data)
    return cal


if __name__ == "__main__":
    cal = calibrate()
    (RAW / "whoop_calibration.json").write_text(json.dumps(cal, indent=1))
    print(json.dumps(cal, indent=1))
    print("→ data/raw/whoop_calibration.json")
