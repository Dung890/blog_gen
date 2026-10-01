# Phase 1 — Production Foundation (completed 2026-09-20)

Phase 1 turns the working app from Phase 0 into a **resilient, observable,
tested, deployable** service. Built in "teaching mode" as six lessons; this doc
records what each added and why.

---

## Summary

| Lesson | What | Files |
|--------|------|-------|
| 1 | Retries + timeouts on LLM calls | `src/nodes/blog_node.py`, `src/llms/groqllm.py`, `src/config/settings.py` |
| 2 | Structured logging + request IDs; retries logged | `src/config/logging.py` (new), `app.py`, `src/nodes/blog_node.py` |
| 3 | Automated tests (LLM mocked) | `tests/` (new), `pyproject.toml` |
| 4 | Typed response model + structured errors | `app.py` |
| 5 | Docker (image + compose) | `Dockerfile`, `.dockerignore`, `docker-compose.yml` (new) |
| 6 | Lint + type-check (ruff + mypy) | `pyproject.toml`, small fixes across files |

---

## Lesson 1 — Resilient LLM calls (`tenacity`)

**Why:** Groq's free tier caps tokens/minute; a 413 (or a network blip) used to
crash the whole request.

- `_is_retryable(exc)` — returns True only for transient errors (413/429/5xx,
  timeouts, connection errors), never for a 400 (which would never succeed).
- `_invoke()` — a wrapper method on `BlogNode` decorated with
  `@retry(wait=wait_exponential(...), stop=stop_after_attempt(5), reraise=True)`.
  All four node LLM calls go through it, so every call gets automatic
  backoff-and-retry with no `try/except` cluttering the logic.
- `groq_timeout` setting → `timeout=` on `ChatGroq` so a hung call gives up.

**Concept:** a decorator wraps a function to add behaviour; retry-with-backoff is
the standard pattern for any flaky external call; only retry what's retryable.

## Lesson 2 — Structured logging + request IDs (`structlog`)

**Why:** debugging by reading stack traces was painful; we needed searchable,
traceable logs.

- `src/config/logging.py` — `configure_logging()` sets up a structlog processor
  pipeline (contextvars → level → timestamp → console renderer); `get_logger()`
  returns a logger.
- `app.py` — logs `blog_request_started` / `finished` / `failed` with topic,
  language, and duration. Each request binds a `request_id` via
  `structlog.contextvars.bind_contextvars`, so **every** log line during that
  request carries it automatically; `clear_contextvars()` in `finally` prevents
  leaking it to the next request.
- `blog_node.py` — `before_sleep=_log_retry` on the `@retry` logs each retry
  (attempt, wait, error) — so backoff is now visible in the logs.

**Concept:** a log call becomes a dict that flows through the processor pipeline;
contextvars carry per-request data (the id) without passing it around. Logs go to
**stdout** (12-factor style) — the environment (Docker, etc.) decides storage.

## Lesson 3 — Automated tests (`pytest`)

**Why:** replace slow manual "fire a request and eyeball it" with instant checks.

- `tests/test_state.py` — reducer tests (pure logic); guards the Phase 0
  reducer fix from regressing.
- `tests/test_blog.py` — a `FakeLLM` (mock) with an `.invoke()` returning canned
  text, used to test both nodes and both compiled graph paths; guards the
  translation flow.
- `pyproject.toml` — `[tool.pytest.ini_options]` with `pythonpath=["."]` and
  `testpaths=["tests"]`.

**Concept:** mocking swaps the real LLM for a deterministic fake, so tests are
fast, free, and repeatable — they test *our* logic, not the model.

## Lesson 4 — Typed response + structured errors

**Why:** the output was an untyped `{"data": <raw state>}` blob and errors were
bare strings.

- `BlogResponse` model → `@app.post("/blogs", response_model=BlogResponse)`.
  Returns a flat, documented `{topic, language, title, content, request_id}`.
- `except` block logs the real error server-side and returns a structured JSON
  500 (`error`, generic `message`, `request_id`) — never leaking internals.
  Uses `raise ... from exc` to preserve the cause.

**Concept:** log full detail server-side, return a generic message + trace id to
the client. This pattern let us debug the `NameError` we hit here purely from the
logs (matched by request_id).

## Lesson 5 — Docker

**Why:** run identically anywhere; the standard way to deploy.

- `Dockerfile` — `python:3.13-slim`, install deps in their own cached layer, copy
  code, run uvicorn. `PYTHONUNBUFFERED=1` so logs stream to stdout.
- `.dockerignore` — keeps `.venv`, caches, and especially `.env` out of the image.
- `docker-compose.yml` — `build .`, map port 8000, `env_file: .env` (secrets
  injected at runtime, never baked into the image).

**Commands:** `docker compose up --build [-d]`, `docker compose ps`,
`docker compose logs -f`, `docker compose down`.

**Concept:** the image is a portable snapshot; secrets stay external; layer
caching makes rebuilds fast.

## Lesson 6 — ruff + mypy

**Why:** consistent style and type safety, catching bugs before runtime.

- `ruff` — linter + formatter. Caught the duplicate `import structlog` (F811),
  import ordering (I001), whitespace, and flagged `B904` (raise-from in except,
  fixed in Lesson 4's style). Config: `select = ["E","W","F","I","UP","B"]`.
- `mypy` — type checker. Caught two real issues:
  - `settings.py` — false positive on `Settings()` (fields load from env);
    resolved with a targeted `# type: ignore[call-arg]`.
  - `blog_node.py` — `_is_retryable` had to accept `BaseException` (not
    `Exception`) to match tenacity's expected callback type (contravariance).
- Config in `pyproject.toml` (`[tool.ruff]`, `[tool.ruff.lint]`, `[tool.mypy]`
  with `ignore_missing_imports = true`).

**Concept:** `# type: ignore[code]` is a targeted escape hatch for false
positives; function-argument types are contravariant (a callback must accept at
least as wide a type as the caller may pass).

---

## Deferred

- **GitHub Actions CI** — waiting until the project is a git repo pushed to
  GitHub. Will run `pytest`, `ruff check`, and `mypy` on every push.
- **LangGraph checkpointer / Postgres** — moved to Phase 2.5 where persistence
  and memory are added.

## How to verify the whole thing

```bash
.venv/Scripts/python.exe -m pytest -q          # tests green
.venv/Scripts/python.exe -m ruff check .       # All checks passed!
.venv/Scripts/python.exe -m mypy src app.py    # Success: no issues found
docker compose up --build                       # runs in a container on :8000
```
