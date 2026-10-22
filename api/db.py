"""Connexion Postgres (mémoire de l'agent) via DATABASE_URL."""
import os

import psycopg


def database_url() -> str | None:
    return os.getenv("DATABASE_URL") or None


def ping() -> bool:
    """True si Postgres répond. Lève une exception sinon."""
    with psycopg.connect(database_url(), connect_timeout=5) as conn:
        return conn.execute("SELECT 1").fetchone()[0] == 1
