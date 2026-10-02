"""Long-term semantic memory backed by Postgres + pgvector.

Embeds text locally with fastembed, stores vectors in Postgres, and recalls the
most semantically similar past memories.
"""

import json

import psycopg
from fastembed import TextEmbedding
from pgvector.psycopg import register_vector

from src.config import get_settings

_EMBED_DIM = 384  # output size of BAAI/bge-small-en-v1.5


class MemoryStore:
    """Stores and recalls memories by meaning (vector similarity)."""

    def __init__(self):
        settings = get_settings()
        self._conn = psycopg.connect(settings.database_url, autocommit=True)
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")  # must exist before register
        register_vector(self._conn)  # teach psycopg how to send/receive vectors
        self._ensure_schema()
        # Only load the embedding model once the DB is confirmed working.
        self._embedder = TextEmbedding(model_name=settings.embed_model)

    def _embed(self, text: str):
        """Turn text into a 384-dim vector (NumPy array, which register_vector
        sends to Postgres as a `vector` rather than a plain `real[]`)."""
        return next(self._embedder.embed([text]))

    def _ensure_schema(self) -> None:
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS memories (
                id BIGSERIAL PRIMARY KEY,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata JSONB DEFAULT '{{}}',
                embedding vector({_EMBED_DIM}),
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )

    def remember(self, text: str, kind: str = "semantic", metadata: dict | None = None) -> None:
        """Store a memory with its embedding."""
        self._conn.execute(
            "INSERT INTO memories (kind, text, metadata, embedding) VALUES (%s, %s, %s, %s)",
            (kind, text, json.dumps(metadata or {}), self._embed(text)),
        )

    def recall(self, query: str, k: int = 3, kind: str | None = None) -> list[dict]:
        """Return the k most semantically similar memories to the query."""
        emb = self._embed(query)
        if kind:
            rows = self._conn.execute(
                "SELECT text, kind, metadata FROM memories WHERE kind = %s "
                "ORDER BY embedding <=> %s LIMIT %s",
                (kind, emb, k),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT text, kind, metadata FROM memories ORDER BY embedding <=> %s LIMIT %s",
                (emb, k),
            ).fetchall()
        return [{"text": r[0], "kind": r[1], "metadata": r[2]} for r in rows]
