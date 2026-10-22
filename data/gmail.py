"""Connecteur Gmail → WorkEvent (métadonnées des mails envoyés / reçus).

Scope `gmail.metadata` : Google ne renvoie jamais le corps du message avec ce
scope. En plus, on ne demande que les en-têtes From/To/Cc/Bcc (pas le sujet),
on en tire un nombre de destinataires et un booléen externe, puis on jette les
adresses.

Limite connue du scope metadata : la recherche `q` (ex. « after:2026/07/01 »)
est interdite. On parcourt donc la boîte du plus récent au plus ancien et on
s'arrête à la date limite.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from email.utils import getaddresses
from typing import Iterator, Optional
from zoneinfo import ZoneInfo

from data.events import LOCAL_TZ, WorkEvent, domain_of, make_event, pseudonymize

HEADERS = ["From", "To", "Cc", "Bcc"]
MESSAGE_FIELDS = "id,labelIds,internalDate,payload/headers"
BATCH_SIZE = 50  # Gmail limite le débit des requêtes groupées


def fetch(days_back: int = 90, team_id: str = "demo", max_messages: int = 5000,
          service=None) -> list[WorkEvent]:
    from data.google_auth import build_service

    service = service or build_service("gmail", "v1")
    owner_email = service.users().getProfile(userId="me").execute()["emailAddress"]
    cutoff_ms = int((datetime.now() - timedelta(days=days_back)).timestamp() * 1000)

    messages: list[dict] = []
    page_token = None
    while len(messages) < max_messages:
        resp = service.users().messages().list(
            userId="me", maxResults=500, pageToken=page_token, includeSpamTrash=False,
        ).execute()
        ids = [m["id"] for m in resp.get("messages", [])]
        page = _get_metadata(service, ids)
        messages.extend(m for m in page if int(m.get("internalDate", 0)) >= cutoff_ms)
        page_token = resp.get("nextPageToken")
        oldest = min((int(m.get("internalDate", 0)) for m in page), default=0)
        if not page_token or oldest < cutoff_ms:
            break
    return list(normalize(messages[:max_messages], owner_email, team_id))


def _get_metadata(service, ids: list[str]) -> list[dict]:
    """Récupère les métadonnées de plusieurs messages par lots (bien plus rapide)."""
    results: list[dict] = []

    def on_response(_request_id, response, exception):
        if exception is None:
            results.append(response)

    for i in range(0, len(ids), BATCH_SIZE):
        batch = service.new_batch_http_request(callback=on_response)
        for msg_id in ids[i:i + BATCH_SIZE]:
            batch.add(service.users().messages().get(
                userId="me", id=msg_id, format="metadata",
                metadataHeaders=HEADERS, fields=MESSAGE_FIELDS,
            ))
        batch.execute()
    return results


def normalize(messages: list[dict], owner_email: str, team_id: str) -> Iterator[WorkEvent]:
    user_id = pseudonymize(owner_email)
    owner_domain = domain_of(owner_email)
    for msg in messages:
        labels = set(msg.get("labelIds", []))
        if "DRAFT" in labels or not msg.get("internalDate"):
            continue
        headers = _headers(msg)
        recipients = _addresses(headers, "To", "Cc", "Bcc")
        if "SENT" in labels:
            kind, others = "email_out", recipients
        else:
            kind, others = "email_in", _addresses(headers, "From")
        yield make_event(
            user_id=user_id, team_id=team_id, kind=kind, source="gmail",
            start=_local_from_ms(msg["internalDate"]),
            n_attendees=len(recipients),
            is_external=any(domain_of(a) not in ("", owner_domain) for a in others),
        )


def _headers(msg: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name") in HEADERS:  # tout autre en-tête (Subject…) est ignoré
            out.setdefault(h["name"], []).append(h.get("value", ""))
    return out


def _addresses(headers: dict[str, list[str]], *names: str) -> list[str]:
    values = [v for n in names for v in headers.get(n, [])]
    return [addr for _, addr in getaddresses(values) if "@" in addr]


def _local_from_ms(ms: Optional[str]) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, ZoneInfo(LOCAL_TZ)).replace(tzinfo=None)
