"""Connecteur Google Calendar → WorkEvent (métadonnées uniquement).

On ne demande même pas le titre ni la description à Google : le paramètre
`fields` limite la réponse aux heures, au statut et aux invités.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional
from zoneinfo import ZoneInfo

from data.events import LOCAL_TZ, WorkEvent, domain_of, make_event, pseudonymize

EVENT_FIELDS = ("nextPageToken,items(status,eventType,start,end,created,"
                "attendees(email,self,responseStatus,resource))")
# Types Google qui ne sont pas du travail planifié (lieu de travail, absence…).
SKIPPED_TYPES = {"workingLocation", "outOfOffice", "birthday", "fromGmail"}


def fetch(days_back: int = 90, days_forward: int = 14, team_id: str = "demo",
          service=None) -> list[WorkEvent]:
    """Lit l'agenda principal de -days_back à +days_forward jours."""
    from data.google_auth import build_service

    service = service or build_service("calendar", "v3")
    owner_email = service.calendars().get(calendarId="primary", fields="id").execute()["id"]
    now = datetime.now(timezone.utc)
    params = dict(
        calendarId="primary", singleEvents=True, showDeleted=True, maxResults=2500,
        timeMin=(now - timedelta(days=days_back)).isoformat(),
        timeMax=(now + timedelta(days=days_forward)).isoformat(),
        fields=EVENT_FIELDS,
    )
    events: list[WorkEvent] = []
    page_token = None
    while True:
        resp = service.events().list(pageToken=page_token, **params).execute()
        events.extend(normalize(resp.get("items", []), owner_email, team_id))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return events


def normalize(items: list[dict], owner_email: str, team_id: str) -> Iterator[WorkEvent]:
    """Transforme les événements bruts de l'API en WorkEvent."""
    user_id = pseudonymize(owner_email)
    owner_domain = domain_of(owner_email)
    for item in items:
        if item.get("eventType", "default") in SKIPPED_TYPES:
            continue
        start = _local_dt(item.get("start", {}).get("dateTime"))
        end = _local_dt(item.get("end", {}).get("dateTime"))
        if start is None:  # événement « toute la journée » ou annulé sans horaire
            continue
        people = [a for a in item.get("attendees", []) if not a.get("resource")]
        status = item.get("status", "confirmed")
        if any(a.get("self") and a.get("responseStatus") == "declined" for a in people):
            status = "declined"
        yield make_event(
            user_id=user_id, team_id=team_id, kind="meeting", source="gcal",
            start=start, end=end, created=_local_dt(item.get("created")),
            n_attendees=len(people) or 1,
            is_external=any(domain_of(a.get("email", "")) not in ("", owner_domain)
                            for a in people),
            status=status,
        )


def _local_dt(value: Optional[str]) -> Optional[datetime]:
    """RFC 3339 (« 2026-10-20T09:00:00+02:00 » ou « …000Z ») → heure locale naïve."""
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    if "." in value:  # fromisoformat de Python 3.9 n'aime pas les millisecondes
        head, tail = value.split(".", 1)
        offset = tail[tail.find("+"):] if "+" in tail else tail[tail.find("-"):] if "-" in tail else ""
        value = head + offset
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(ZoneInfo(LOCAL_TZ)).replace(tzinfo=None)
