"""Connecteur WHOOP (API v2) : connexion OAuth, export JSON de secours, lignes `recovery_daily`.

Usage (en local, depuis la racine du repo, avec WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET dans .env) :

    python -m data.whoop login           # ouvre le navigateur, tu te connectes à Whoop
    python -m data.whoop fetch --days 90 # télécharge recovery / sleep / cycle → data/raw/
                                         # (relançable : garde ce qui est déjà téléchargé)
    python -m data.whoop daily           # reconstruit data/raw/whoop_daily.json depuis les exports

Tout ce qui est écrit va dans data/raw/ (ignoré par git) : jeton, exports bruts, table journalière.
Champs : developer.whoop.com/api (v2).
"""
import argparse
import json
import os
import secrets
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API = "https://api.prod.whoop.com/developer"
# `offline` = WHOOP renvoie un refresh token (sinon il faut se reconnecter toutes les heures).
SCOPES = "read:recovery read:sleep read:cycles read:profile offline"

RAW = Path(__file__).resolve().parent / "raw"
TOKEN_FILE = RAW / "whoop_token.json"
ENDPOINTS = {"recovery": "/v2/recovery", "sleep": "/v2/activity/sleep", "cycle": "/v2/cycle"}


def _client() -> tuple[str, str, str]:
    cid, secret = os.getenv("WHOOP_CLIENT_ID"), os.getenv("WHOOP_CLIENT_SECRET")
    if not cid or not secret:
        raise SystemExit("WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET manquants dans .env")
    redirect = os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8000/oauth/whoop/callback")
    return cid, secret, redirect


def _save_token(tok: dict) -> dict:
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    RAW.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok))
    return tok


# --- OAuth -----------------------------------------------------------------

def login() -> None:
    """Flux OAuth complet en local : petit serveur sur le port de WHOOP_REDIRECT_URI."""
    cid, secret, redirect = _client()
    state = secrets.token_hex(4)  # WHOOP exige 8 caractères
    url = AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": cid,
                                      "redirect_uri": redirect, "scope": SCOPES, "state": state})
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>C'est bon, tu peux fermer cet onglet.</h2>".encode())

        def log_message(self, *args):
            pass

    port = urlparse(redirect).port or 80
    server = HTTPServer(("localhost", port), Handler)
    print("Ouverture du navigateur… Si rien ne s'ouvre, colle ce lien :\n" + url)
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        server.handle_request()
    server.server_close()

    if "error" in got:
        raise SystemExit(f"WHOOP a refusé : {got.get('error')} {got.get('error_description', '')}")
    if got.get("state") != state:
        raise SystemExit("state incohérent, recommence `login`")
    r = httpx.post(TOKEN_URL, data={"grant_type": "authorization_code", "code": got["code"],
                                    "client_id": cid, "client_secret": secret, "redirect_uri": redirect})
    r.raise_for_status()
    _save_token(r.json())
    print(f"Connecté. Jeton enregistré dans {TOKEN_FILE.relative_to(RAW.parent.parent)} (ignoré par git).")


def access_token() -> str:
    if not TOKEN_FILE.exists():
        raise SystemExit("Pas encore connecté : lance `python -m data.whoop login`")
    tok = json.loads(TOKEN_FILE.read_text())
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise SystemExit("Jeton expiré et pas de refresh token : relance `login`")
    cid, secret, _ = _client()
    r = httpx.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                    "client_id": cid, "client_secret": secret, "scope": "offline"})
    r.raise_for_status()
    return _save_token(r.json())["access_token"]


# --- Export ----------------------------------------------------------------

def _get(c: httpx.Client, path: str, params: dict) -> httpx.Response:
    """GET avec patience : wifi lent (timeouts) et limite de débit WHOOP (429)."""
    for attempt in range(6):
        try:
            r = c.get(path, params=params)
        except httpx.TransportError as e:  # timeout, coupure réseau…
            wait = 2 ** attempt
            print(f"  réseau lent ({type(e).__name__}), nouvel essai dans {wait}s…")
            time.sleep(wait)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r
    raise SystemExit("WHOOP ne répond pas après plusieurs essais : relance la même commande "
                     "(ce qui est déjà téléchargé est gardé).")


def fetch_collection(path: str, start: datetime, end: datetime | None = None) -> list[dict]:
    """Toutes les pages d'une collection v2 (limit max 25, pagination nextToken)."""
    headers = {"Authorization": f"Bearer {access_token()}"}
    params = {"limit": 25, "start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    if end:
        params["end"] = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    records = []
    timeout = httpx.Timeout(60, connect=30)
    with httpx.Client(base_url=API, headers=headers, timeout=timeout) as c:
        while True:
            body = _get(c, path, params).json()
            records += body.get("records", [])
            if not body.get("next_token"):
                return records
            params["nextToken"] = body["next_token"]


def fetch(days: int = 90, only: list[str] | None = None, force: bool = False) -> None:
    """Télécharge recovery / sleep / cycle et sauvegarde les exports bruts (plan B).

    Une collection déjà sauvegardée n'est pas retéléchargée (sauf --force) : si le réseau
    coupe au milieu, il suffit de relancer la commande.
    """
    start = datetime.now(timezone.utc) - timedelta(days=days)
    for name in only or ENDPOINTS:
        f = RAW / f"whoop_{name}.json"
        if f.exists() and not force and not only:
            print(f"{name:9s} déjà là, on passe (--force pour retélécharger)")
            continue
        records = fetch_collection(ENDPOINTS[name], start)
        f.write_text(json.dumps(records, indent=1))
        print(f"{name:9s} {len(records):4d} enregistrements → data/raw/whoop_{name}.json")


# --- Transformation → recovery_daily (CLAUDE.md §7) --------------------------

def _local(ts: str, offset: str | None) -> datetime:
    """Horodatage WHOOP (UTC) → heure locale naïve, via timezone_offset (« +02:00 »)."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if offset:
        sign = -1 if offset.startswith("-") else 1
        h, m = offset.lstrip("+-").split(":")
        dt = dt + sign * timedelta(hours=int(h), minutes=int(m))
    return dt.replace(tzinfo=None)


def to_daily(recovery: list[dict], sleep: list[dict], cycle: list[dict],
             user_id: str = "ichane", team_id: str = "demo") -> list[dict]:
    """Une ligne par jour. `date` = jour du réveil (la récupération WHOOP est celle du matin)."""
    sleeps = {s["id"]: s for s in sleep if not s.get("nap") and s.get("score_state") == "SCORED"}
    cycles = {c["id"]: c for c in cycle}
    rows = {}
    for rec in recovery:
        sc = rec.get("score") or {}
        if rec.get("score_state") != "SCORED" or sc.get("user_calibrating"):
            continue
        sl = sleeps.get(rec.get("sleep_id"))
        if not sl:
            continue
        ss = sl["score"]["stage_summary"]
        asleep_ms = (ss["total_light_sleep_time_milli"] + ss["total_slow_wave_sleep_time_milli"]
                     + ss["total_rem_sleep_time_milli"])
        cy = cycles.get(rec.get("cycle_id")) or {}
        day = _local(sl["end"], sl.get("timezone_offset")).date().isoformat()
        if day in rows and rows[day]["sleep_h"] >= asleep_ms / 3_600_000:
            continue  # deux nuits le même jour (réveil nocturne coupé en 2) : on garde la plus longue
        rows[day] = {
            "user_id": user_id, "team_id": team_id, "date": day,
            "recovery": float(sc["recovery_score"]),
            "hrv": round(float(sc["hrv_rmssd_milli"]), 1),
            "rhr": float(sc["resting_heart_rate"]),
            "sleep_h": round(asleep_ms / 3_600_000, 2),
            "sleep_consistency": float(sl["score"].get("sleep_consistency_percentage") or 0),
            "bedtime": _local(sl["start"], sl.get("timezone_offset")).isoformat(timespec="minutes"),
            "strain": round(float((cy.get("score") or {}).get("strain") or 0), 1),
            "source": "whoop",
        }
    return [rows[d] for d in sorted(rows)]


def daily_from_raw(user_id: str = "ichane") -> list[dict]:
    """Reconstruit la table journalière depuis les exports JSON de data/raw/ (marche hors ligne)."""
    def load(n):  # cycle manquant → strain à 0, le reste marche quand même
        f = RAW / f"whoop_{n}.json"
        return json.loads(f.read_text()) if f.exists() or n != "cycle" else []
    rows = to_daily(load("recovery"), load("sleep"), load("cycle"), user_id=user_id)
    (RAW / "whoop_daily.json").write_text(json.dumps(rows, indent=1))
    print(f"{len(rows)} jours → data/raw/whoop_daily.json")
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Connecteur WHOOP")
    p.add_argument("cmd", choices=["login", "fetch", "daily"])
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--only", nargs="+", choices=list(ENDPOINTS), help="ne télécharger que ces collections")
    p.add_argument("--force", action="store_true", help="retélécharger même si déjà sauvegardé")
    a = p.parse_args()
    if a.cmd == "login":
        login()
    elif a.cmd == "fetch":
        fetch(a.days, a.only, a.force)
        daily_from_raw(os.getenv("USER_ID", "ichane"))
    else:
        daily_from_raw(os.getenv("USER_ID", "ichane"))
