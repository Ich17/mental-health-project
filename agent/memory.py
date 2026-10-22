"""Mémoire long terme des agents (PostgreSQL), avec un repli en mémoire vive.

- `PostgresMemory` : utilisée dès que DATABASE_URL est défini (Aiven).
- `InMemoryMemory` : même interface, pour coder et tester sans base.

Les deux sont pré-remplies (`seed`) avec une expérience terminée et une règle
d'équipe mesurée, pour montrer la boucle d'apprentissage en démo (CLAUDE.md §7).
"""
from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("postgres.sql")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(row: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in row.items()}


# Données de démo pré-remplies -------------------------------------------------

def _seed_rows(user_id: str, team_id: str) -> dict:
    today = date.today()
    return {
        "hypotheses": [dict(
            factor="last_minute_meetings", effect_text="-25 min de sommeil par call ajouté le jour même",
            effect_size=-0.42, confidence="moyenne", status="active")],
        "experiments": [dict(
            rule_text="Pas de réunion après 19h le mardi et le jeudi",
            start_date=(today - timedelta(days=35)).isoformat(),
            end_date=(today - timedelta(days=21)).isoformat(),
            baseline_recovery=48.0, result_recovery=53.8, verdict="garder (+12 % de récupération)")],
        "team_rules": [dict(
            team_id=team_id, rule_text="Pas d'ajout de réunion le jour même après 17h",
            start_date=(today - timedelta(days=28)).isoformat(),
            measured_effect="+6 points de récupération moyenne en 4 semaines", status="applied")],
    }


class InMemoryMemory:
    def __init__(self):
        self._lock = threading.Lock()
        self.data: dict[str, list[dict]] = {k: [] for k in (
            "users", "hypotheses", "experiments", "actions", "feedback", "team_rules",
            "agent_runs", "agent_messages")}

    def _insert(self, table: str, row: dict) -> int:
        with self._lock:
            row = {"id": len(self.data[table]) + 1, "created_at": _now(), **row}
            self.data[table].append(row)
            return row["id"]

    # --- utilisateurs
    def ensure_user(self, user_id: str, team_id: str | None = None):
        if not any(u["id"] == user_id for u in self.data["users"]):
            self.data["users"].append({"id": user_id, "name": user_id, "team_id": team_id})

    def seed(self, user_id: str, team_id: str = "ma"):
        self.ensure_user(user_id, team_id)
        if self.data["experiments"]:
            return
        rows = _seed_rows(user_id, team_id)
        for h in rows["hypotheses"]:
            self._insert("hypotheses", {"user_id": user_id, **h})
        for e in rows["experiments"]:
            self._insert("experiments", {"user_id": user_id, **e})
        self.seed_team(team_id)

    def seed_team(self, team_id: str):
        """Règle d'équipe passée avec effet mesuré (démo de la boucle d'apprentissage RH)."""
        if self.team_rules(team_id):
            return
        for r in _seed_rows("", team_id)["team_rules"]:
            self._insert("team_rules", r)

    # --- lecture pour les agents
    def get_memory(self, user_id: str) -> dict:
        mine = lambda t: [r for r in self.data[t] if r.get("user_id") == user_id]  # noqa: E731
        return {"hypotheses": mine("hypotheses"), "experiments": mine("experiments"),
                "feedback": mine("feedback")[-10:], "recent_actions": mine("actions")[-10:]}

    def get_experiment(self, user_id: str, experiment_id: int) -> dict | None:
        return next((e for e in self.data["experiments"]
                     if e["id"] == experiment_id and e["user_id"] == user_id), None)

    def team_rules(self, team_id: str) -> list[dict]:
        return [r for r in self.data["team_rules"] if r["team_id"] == team_id]

    # --- écriture
    def save_hypothesis(self, user_id: str, **h) -> int:
        return self._insert("hypotheses", {"user_id": user_id, "status": "active", **h})

    def start_experiment(self, user_id: str, rule_text: str, start: str, end: str,
                         baseline_recovery: float | None) -> int:
        return self._insert("experiments", dict(
            user_id=user_id, rule_text=rule_text, start_date=start, end_date=end,
            baseline_recovery=baseline_recovery, result_recovery=None, verdict=None))

    def add_action(self, user_id: str, kind: str, payload: dict, status: str = "proposed") -> int:
        return self._insert("actions", dict(user_id=user_id, kind=kind, payload=payload, status=status))

    def get_action(self, action_id: int) -> dict | None:
        return next((a for a in self.data["actions"] if a["id"] == action_id), None)

    def list_actions(self, user_id: str, status: str | None = None) -> list[dict]:
        return [a for a in self.data["actions"] if a["user_id"] == user_id
                and (status is None or a["status"] == status)]

    def set_action_status(self, action_id: int, status: str):
        a = self.get_action(action_id)
        if a:
            a["status"] = status

    def suggest_team_rule(self, team_id: str, rule_text: str) -> int:
        return self._insert("team_rules", dict(team_id=team_id, rule_text=rule_text, start_date=None,
                                               measured_effect=None, status="suggested"))

    # --- journal des délibérations
    def create_run(self, run_kind: str, subject: str) -> int:
        return self._insert("agent_runs", dict(run_kind=run_kind, subject=subject, status="running",
                                               final_message=None))

    def append_message(self, run_id: int, msg: dict):
        # "to" est un mot réservé en SQL : stocké sous le nom "recipient"
        self._insert("agent_messages", dict(
            run_id=run_id, author=msg["author"], recipient=msg["to"], kind=msg["kind"],
            content=msg["content"], data=msg.get("data") or {}, ts=msg["ts"]))

    def finish_run(self, run_id: int, status: str, final_message: str | None):
        run = next(r for r in self.data["agent_runs"] if r["id"] == run_id)
        run.update(status=status, final_message=final_message)

    def get_run(self, run_id: int) -> dict | None:
        run = next((r for r in self.data["agent_runs"] if r["id"] == run_id), None)
        if run is None:
            return None
        msgs = [m for m in self.data["agent_messages"] if m["run_id"] == run_id]
        return {**run, "messages": msgs}

    def list_runs(self, limit: int = 20) -> list[dict]:
        return list(reversed(self.data["agent_runs"]))[:limit]


class PostgresMemory(InMemoryMemory):
    """Même interface, persistée dans Postgres. Une connexion courte par appel :
    simple et robuste pour un PoC (pas de pool à gérer)."""

    JSON_COLS = {"payload", "data"}

    def __init__(self, url: str):
        self.url = url
        with self._conn() as c:
            c.execute(SCHEMA.read_text(encoding="utf-8"))

    def _conn(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def _q(self, sql: str, params: tuple = (), one: bool = False):
        with self._conn() as c:
            cur = c.execute(sql, params)
            if cur.description is None:
                return None
            rows = [_jsonable(r) for r in cur.fetchall()]
            return (rows[0] if rows else None) if one else rows

    def _insert(self, table: str, row: dict) -> int:
        cols = list(row)
        from psycopg.types.json import Jsonb

        vals = tuple(Jsonb(v) if k in self.JSON_COLS else v for k, v in row.items())
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
               f"({', '.join(['%s'] * len(cols))}) RETURNING id")
        return self._q(sql, vals, one=True)["id"]

    def ensure_user(self, user_id, team_id=None):
        self._q("INSERT INTO users (id, name, team_id) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (user_id, user_id, team_id))

    def seed(self, user_id, team_id="ma"):
        self.ensure_user(user_id, team_id)
        if self._q("SELECT 1 FROM experiments WHERE user_id = %s LIMIT 1", (user_id,)):
            return
        rows = _seed_rows(user_id, team_id)
        for h in rows["hypotheses"]:
            self._insert("hypotheses", {"user_id": user_id, **h})
        for e in rows["experiments"]:
            self._insert("experiments", {"user_id": user_id, **e})
        self.seed_team(team_id)

    def get_memory(self, user_id):
        q = lambda sql: self._q(sql, (user_id,))  # noqa: E731
        return {
            "hypotheses": q("SELECT * FROM hypotheses WHERE user_id = %s ORDER BY id"),
            "experiments": q("SELECT * FROM experiments WHERE user_id = %s ORDER BY id"),
            "feedback": q("SELECT * FROM feedback WHERE user_id = %s ORDER BY id DESC LIMIT 10"),
            "recent_actions": q("SELECT * FROM actions WHERE user_id = %s ORDER BY id DESC LIMIT 10"),
        }

    def get_experiment(self, user_id, experiment_id):
        return self._q("SELECT * FROM experiments WHERE id = %s AND user_id = %s",
                       (experiment_id, user_id), one=True)

    def team_rules(self, team_id):
        return self._q("SELECT * FROM team_rules WHERE team_id = %s ORDER BY id", (team_id,))

    def get_action(self, action_id):
        return self._q("SELECT * FROM actions WHERE id = %s", (action_id,), one=True)

    def list_actions(self, user_id, status=None):
        if status:
            return self._q("SELECT * FROM actions WHERE user_id = %s AND status = %s ORDER BY id",
                           (user_id, status))
        return self._q("SELECT * FROM actions WHERE user_id = %s ORDER BY id", (user_id,))

    def set_action_status(self, action_id, status):
        self._q("UPDATE actions SET status = %s WHERE id = %s", (status, action_id))

    def finish_run(self, run_id, status, final_message):
        self._q("UPDATE agent_runs SET status = %s, final_message = %s, finished_at = now() WHERE id = %s",
                (status, final_message, run_id))

    def get_run(self, run_id):
        run = self._q("SELECT * FROM agent_runs WHERE id = %s", (run_id,), one=True)
        if run is None:
            return None
        run["messages"] = self._q("SELECT * FROM agent_messages WHERE run_id = %s ORDER BY id", (run_id,))
        return run

    def list_runs(self, limit=20):
        return self._q("SELECT * FROM agent_runs ORDER BY id DESC LIMIT %s", (limit,))


_store = None
_store_lock = threading.Lock()


def get_store():
    """Singleton : Postgres si DATABASE_URL, sinon mémoire vive."""
    global _store
    with _store_lock:
        if _store is None:
            url = os.getenv("DATABASE_URL")
            _store = PostgresMemory(url) if url else InMemoryMemory()
        return _store
