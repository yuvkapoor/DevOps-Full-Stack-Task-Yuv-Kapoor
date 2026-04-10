from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

import psycopg2
import psycopg2.extras

from settings import get_settings


def _normalize_database_url(raw_url: str | None) -> str:
    if not raw_url:
        raise RuntimeError(
            "Database URL is missing. Set DATABASE_URL or connection_string in backend/.env."
        )

    cleaned = raw_url.strip().strip("'").strip('"')
    if "://" not in cleaned:
        return cleaned

    scheme, remainder = cleaned.split("://", 1)
    if "/" in remainder:
        netloc, suffix = remainder.split("/", 1)
        suffix = "/" + suffix
    else:
        netloc = remainder
        suffix = ""

    # Handles passwords containing '@' by encoding only the password segment.
    if netloc.count("@") > 1 and ":" in netloc:
        credentials, host = netloc.rsplit("@", 1)
        username, password = credentials.split(":", 1)
        netloc = f"{username}:{quote(password, safe='')}@{host}"

    return f"{scheme}://{netloc}{suffix}"


def _connection_kwargs() -> dict[str, Any]:
    settings = get_settings()
    normalized = _normalize_database_url(settings.database_url)
    kwargs: dict[str, Any] = {
        "dsn": normalized,
        "cursor_factory": psycopg2.extras.RealDictCursor,
    }
    if "sslmode=" not in normalized:
        kwargs["sslmode"] = "require"
    return kwargs


@contextmanager
def get_db():
    conn = psycopg2.connect(**_connection_kwargs())
    try:
        yield conn
    finally:
        conn.close()


def execute_query(sql: str) -> list[dict]:
    """Execute only read-only analytics queries and return at most 500 rows."""
    statement = sql.strip().rstrip(";")
    if not statement.upper().startswith(("SELECT", "WITH")):
        raise ValueError("Only SELECT/CTE queries are allowed.")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(statement)
            rows = cur.fetchmany(500)
            return [dict(row) for row in rows]


def test_connection() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False
