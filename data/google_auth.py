"""Connexion OAuth Google (Calendar + Gmail) pour un compte de démo.

Flux « application de bureau » : la première fois, un onglet s'ouvre, on se
connecte avec un compte ajouté comme utilisateur test, et le jeton est gardé
dans `.secrets/google_token.json` (ignoré par git). Les fois suivantes, le jeton
est rechargé et rafraîchi tout seul.

Identifiants lus dans `.env` : GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET
(ou, à défaut, un fichier `.secrets/credentials.json` téléchargé de la console).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = ROOT / ".secrets"
TOKEN_FILE = SECRETS_DIR / "google_token.json"
CREDENTIALS_FILE = SECRETS_DIR / "credentials.json"

# Scopes les plus restreints possibles :
# - calendar.readonly : lire les événements (heures, invités), rien modifier ;
# - gmail.metadata : en-têtes et libellés uniquement, Google refuse l'accès au corps.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.metadata",
]
# Ajouté seulement si on veut que l'agent crée des blocs « Occupé » dans l'agenda.
CALENDAR_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def scopes() -> list[str]:
    if os.getenv("GOOGLE_CALENDAR_WRITE", "0") == "1":
        return SCOPES + [CALENDAR_WRITE_SCOPE]
    return list(SCOPES)


def get_credentials():
    """Renvoie des identifiants Google valides (ouvre le navigateur si besoin)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    wanted = scopes()
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), wanted)
    if creds and creds.valid and creds.has_scopes(wanted):
        return creds
    if creds and creds.expired and creds.refresh_token and creds.has_scopes(wanted):
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_config(_client_config(), wanted)
        creds = flow.run_local_server(port=0, prompt="consent")
    SECRETS_DIR.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def build_service(name: str, version: str):
    from googleapiclient.discovery import build

    return build(name, version, credentials=get_credentials(), cache_discovery=False)


def _client_config() -> dict:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        return {"installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }}
    if CREDENTIALS_FILE.exists():
        import json
        return json.loads(CREDENTIALS_FILE.read_text())
    raise RuntimeError(
        "Identifiants Google manquants : remplir GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET "
        "dans .env (ou poser .secrets/credentials.json). Voir data/GOOGLE_SETUP.md."
    )
