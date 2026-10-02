"""Long-term memory access.

`get_memory()` returns a shared MemoryStore, or None if memory is unavailable
(no database, no network, etc.) so the rest of the app can degrade gracefully.
"""

from functools import lru_cache

from src.config.logging import get_logger

log = get_logger("memory")


@lru_cache
def get_memory():
    """Return a shared MemoryStore, or None if it can't be created."""
    try:
        from src.memory.store import MemoryStore

        return MemoryStore()
    except Exception as exc:  # noqa: BLE001 - memory is optional; never crash
        log.warning("memory_unavailable", error=str(exc)[:120])
        return None
