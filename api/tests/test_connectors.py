"""Tests des connecteurs data (sans compte Google ni réseau)."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from data import gcal, gmail
from data.events import WorkEvent, make_event, pseudonymize
from data.simulate_work import generate

OWNER = "ichane@acme.com"


def test_make_event_flags():
    late = make_event("u", "t", "meeting", "gcal", datetime(2026, 10, 20, 18, 30),
                      end=datetime(2026, 10, 20, 19, 30))
    assert late.duration_min == 60 and late.is_after_hours == 1 and late.is_weekend == 0
    day = make_event("u", "t", "email_out", "gmail", datetime(2026, 10, 24, 10, 0))
    assert day.is_after_hours == 0 and day.is_weekend == 1  # samedi


def test_pseudonymize_is_stable_and_hides_email():
    assert pseudonymize("Ichane@Acme.com") == pseudonymize("ichane@acme.com")
    assert "ichane" not in pseudonymize("ichane@acme.com")


def test_gcal_normalize_keeps_metadata_only():
    items = [
        {"status": "confirmed", "summary": "Rachat secret de Globex",
         "description": "confidentiel", "created": "2026-10-20T08:00:00.000Z",
         "start": {"dateTime": "2026-10-20T20:00:00+02:00"},
         "end": {"dateTime": "2026-10-20T21:00:00+02:00"},
         "attendees": [{"email": OWNER, "self": True, "responseStatus": "accepted"},
                       {"email": "bob@acme.com"}, {"email": "x@globex.com"},
                       {"email": "salle@resource.calendar.google.com", "resource": True}]},
        {"status": "confirmed", "start": {"date": "2026-10-21"}, "end": {"date": "2026-10-22"}},
        {"eventType": "outOfOffice", "start": {"dateTime": "2026-10-22T09:00:00Z"}},
    ]
    events = list(gcal.normalize(items, OWNER, "ma"))
    assert len(events) == 1  # journée entière et absence ignorées
    e = events[0]
    assert (e.ts, e.end_ts, e.created_ts) == ("2026-10-20T20:00:00", "2026-10-20T21:00:00",
                                              "2026-10-20T10:00:00")
    assert e.n_attendees == 3 and e.is_external == 1 and e.is_after_hours == 1
    dumped = json.dumps(e.to_dict())
    assert "Globex" not in dumped and "confidentiel" not in dumped and OWNER not in dumped


def test_gcal_declined_status():
    items = [{"start": {"dateTime": "2026-10-20T10:00:00Z"}, "end": {"dateTime": "2026-10-20T10:30:00Z"},
              "attendees": [{"email": OWNER, "self": True, "responseStatus": "declined"}]}]
    assert next(gcal.normalize(items, OWNER, "ma")).status == "declined"


def test_gmail_normalize_counts_recipients_and_drops_addresses():
    ts_ms = str(int(datetime(2026, 10, 20, 22, 15, tzinfo=ZoneInfo("Europe/Paris")).timestamp() * 1000))
    msgs = [
        {"id": "1", "labelIds": ["SENT"], "internalDate": ts_ms, "payload": {"headers": [
            {"name": "To", "value": "Bob <bob@acme.com>, alice@client.fr"},
            {"name": "Cc", "value": "carol@acme.com"},
            {"name": "Subject", "value": "Licenciements prévus"}]}},
        {"id": "2", "labelIds": ["INBOX"], "internalDate": ts_ms, "payload": {"headers": [
            {"name": "From", "value": "boss@acme.com"}, {"name": "To", "value": OWNER}]}},
        {"id": "3", "labelIds": ["DRAFT"], "internalDate": ts_ms, "payload": {"headers": []}},
    ]
    out, inn = list(gmail.normalize(msgs, OWNER, "ma"))
    assert out.kind == "email_out" and out.n_attendees == 3 and out.is_external == 1
    assert inn.kind == "email_in" and inn.n_attendees == 1 and inn.is_external == 0
    assert out.ts == "2026-10-20T22:15:00" and out.is_after_hours == 1
    dumped = json.dumps([out.to_dict(), inn.to_dict()])
    assert "Licenciements" not in dumped and "@" not in dumped


def test_workevent_has_no_content_field():
    forbidden = {"title", "summary", "subject", "body", "description", "content", "email"}
    assert not forbidden & set(WorkEvent.__dataclass_fields__)


def test_simulation_is_deterministic_and_labelled():
    events, truth = generate(n_people=10, days=30, seed=1)
    events2, _ = generate(n_people=10, days=30, seed=1)
    assert [e.to_dict() for e in events] == [e.to_dict() for e in events2]
    profiles = [e["profile"] for e in truth["employees"]]
    assert profiles.count("drift") == 3 and profiles.count("spike") == 1
    assert {e.kind for e in events} == {"meeting", "email_in", "email_out"}
