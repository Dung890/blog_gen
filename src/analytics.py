"""Reader analytics: record engaged reading time per post slug (Postgres)."""

from functools import lru_cache

import psycopg

from src.config import get_settings
from src.config.logging import get_logger

log = get_logger("analytics")


class AnalyticsStore:
    def __init__(self):
        self._conn = psycopg.connect(get_settings().database_url, autocommit=True)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS reading_events ("
            "id BIGSERIAL PRIMARY KEY, slug TEXT NOT NULL, seconds INT NOT NULL, "
            "created_at TIMESTAMPTZ DEFAULT now())"
        )

    def record(self, slug: str, seconds: int) -> None:
        self._conn.execute(
            "INSERT INTO reading_events (slug, seconds) VALUES (%s, %s)", (slug, seconds)
        )

    def average(self, slug: str) -> float | None:
        row = self._conn.execute(
            "SELECT AVG(seconds) FROM reading_events WHERE slug = %s", (slug,)
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def stats(self, slug: str) -> dict:
        """Return {average_seconds, count} of recorded reads for a slug."""
        row = self._conn.execute(
            "SELECT AVG(seconds), COUNT(*) FROM reading_events WHERE slug = %s", (slug,)
        ).fetchone()
        avg = float(row[0]) if row and row[0] is not None else None
        count = int(row[1]) if row else 0
        return {"average_seconds": avg, "count": count}


@lru_cache
def get_analytics():
    try:
        return AnalyticsStore()
    except Exception as exc:  # noqa: BLE001 - analytics is optional, never crash
        log.warning("analytics_unavailable", error=str(exc)[:120])
        return None
