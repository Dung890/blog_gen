# Phase 0 — Fixes & Hygiene (completed 2026-09-17)

Phase 0 makes the app **correct** and **safe** before adding features: fix the
broken translation output, stop leaking secrets, and remove fragile assumptions
in the graph. No new features, no new services.

For newcomers: read this top to bottom. Each section says *what* changed, *why*
it mattered, and *what to look at* in the code.

---

## Summary of changes

| # | Change | File(s) |
|---|--------|---------|
| 1 | Ignore `.env` so secrets are never committed | `.gitignore` |
| 2 | Central, validated configuration | `src/config/settings.py`, `src/config/__init__.py` (new) |
| 3 | LLM loader uses config; stops printing the API key | `src/llms/groqllm.py` |
| 4 | State reducer so blog updates merge instead of overwrite | `src/states/blogstate.py` |
| 5 | Fixed the translation bug (was dropping the title) | `src/nodes/blog_node.py` |
| 6 | One dynamic translation node for any language | `src/graphs/graph_builder.py`, `src/nodes/blog_node.py` |
| 7 | Fail-fast on empty key; lazy Studio graph (no import side-effects) | `src/config/settings.py`, `src/graphs/graph_builder.py` |

---

## 1. Protect secrets (`.gitignore`)

`.env` holds API keys. It was **not** ignored by git, so the first commit would
have leaked the keys. Added:

```gitignore
# Secrets / local environment
.env
*.env
!_copy.env
```

`!_copy.env` keeps the placeholder template tracked (it lists which variables are
needed, with no real values).

## 2. Central configuration (`src/config/settings.py`)

**Before:** every file called `os.getenv(...)` on its own, and nothing checked
that keys existed until a request failed mid-flight.

**After:** one `Settings` object (built on `pydantic-settings`) reads `.env`
once, validates it, and exposes typed fields (`settings.groq_api_key`,
`settings.groq_model`, ...). Call `get_settings()` anywhere. Benefits: fail fast
on missing config, one source of truth, no secrets printed.

## 3. LLM loader (`src/llms/groqllm.py`)

**Before:**
```python
print(os.getenv("GROQ_API_KEY"))  # leaked the secret
os.environ["GROQ_API_KEY"] = self.groq_api_key = os.getenv("GROQ_API_KEY")
raise ValueError("Error occurred with exception : {e}")  # not an f-string
```

**After:** pulls the key/model from `get_settings()`, never prints the key, and
raises `ValueError(f"... {exc}") from exc` so the real cause is preserved.

## 4. State reducer (`src/states/blogstate.py`)

In LangGraph, when a node returns `{"blog": {...}}`, the default behaviour is to
**replace** the whole `blog` value. So a node returning only the content would
erase the title.

We added a *reducer* — a function that says how to combine old and new values:

```python
def merge_blog(existing, new):
    return {**(existing or {}), **(new or {})}


class BlogState(TypedDict):
    topic: str
    blog: Annotated[dict, merge_blog]  # <- merge, don't overwrite
    current_language: str
```

Now each node returns only the field it produced, and nothing gets lost.

## 5. Translation bug fix (`src/nodes/blog_node.py`)

**Before:**
```python
transaltion_content = self.llm.with_structured_output(Blog).invoke(messages)
return {"blog": {"content": transaltion_content}}  # a Blog OBJECT stuffed into content; title lost
```

`with_structured_output(Blog)` returns a `Blog` object. The old code put that
whole object into the `content` string field and never set a title, producing
malformed output.

**After:** the prompt translates *both* title and content, and we store them as
plain strings:
```python
translated: Blog = self.llm.with_structured_output(Blog).invoke([message])
return {"blog": {"title": translated.title, "content": translated.content}}
```

Also removed all debug `print()` calls from the nodes.

## 6. One dynamic translation node (`graph_builder.py`)

**Before:** the language graph used a `route` node plus a conditional edge that
branched to hardcoded `hindi_translation` / `french_translation` lambdas. Any
other language crashed the graph.

**After:** a single `translation` node reads `current_language` from the state,
so it works for **any** language:

```
title_creation -> content_generation -> translation -> END
```

The `route` and `route_decision` helpers were deleted.

## 7. Fail-fast key + lazy Studio graph

- **Empty-key validation:** the shipped `.env` has `GROQ_API_KEY=""`. An empty
  string used to pass type checks and only fail deep inside the Groq client. A
  `field_validator` now rejects a blank key with a clear message telling you to
  set it.
- **Lazy graph:** `langgraph.json` points Studio at `graph_builder.py:graph`.
  Building that at import time forced every import to construct an LLM (and need
  a key). We now expose `graph` lazily via module-level `__getattr__`, so
  importing the module for its class or in tests has no side-effects, while
  Studio still gets its graph on access.

---

## How to run it

1. **Add your real Groq API key** to `.env` (get one at https://console.groq.com):
   ```dotenv
   GROQ_API_KEY=your_real_key_here
   # optional, for LangSmith tracing:
   LANGCHAIN_API_KEY=your_langsmith_key
   LANGCHAIN_PROJECT=blog_gen
   ```
2. Start the API:
   ```bash
   .venv/Scripts/python.exe app.py
   ```
3. Call it (topic only, or topic + language):
   ```bash
   curl -X POST http://localhost:8000/blogs -H "Content-Type: application/json" -d "{\"topic\":\"Agentic AI\"}"
   curl -X POST http://localhost:8000/blogs -H "Content-Type: application/json" -d "{\"topic\":\"Agentic AI\",\"language\":\"spanish\"}"
   ```

## Verification performed

A structural check (no network calls) confirmed: empty key fails with the clear
message; the reducer merges partial updates; the Groq client builds; both graphs
compile with the expected nodes; `app.py` imports cleanly; and importing
`graph_builder` no longer constructs an LLM.

## Troubleshooting log

- **404 `model does not exist or you do not have access`** (2026-09-17): the
  original tutorial hardcoded `llama-3.1-8b-instant`, which Groq has retired for
  this account. Fixed by changing the default in `settings.py` to
  `openai/gpt-oss-20b`. To see which models your key can use:
  ```bash
  .venv/Scripts/python.exe -c "from groq import Groq; from src.config import get_settings; [print(m.id) for m in Groq(api_key=get_settings().groq_api_key).models.list().data]"
  ```
  Override the model any time via `.env`: `GROQ_MODEL=openai/gpt-oss-120b`.

- **Translation returned malformed / truncated output** (2026-09-17): the
  original translation used `with_structured_output(Blog)`, forcing the whole
  translated blog into one JSON object. Long blogs exceed the token limit, the
  JSON gets cut off, and Groq raises `tool_use_failed` / "Failed to parse tool
  call arguments as JSON". Fixed by translating title and content as plain text
  (two calls) in `blog_node.py` - no JSON wrapping.

- **HTTP 500 that "wouldn't go away" / stale code** (2026-09-17): running
  `app.py` uses `reload=True`. Repeated restarts left many orphaned uvicorn
  child processes (13 at once), several with old code, all fighting over port
  8000 - so requests hit stale servers at random. Lesson: kill leftovers before
  restarting, or run a single process without the reloader:
  ```bash
  .venv/Scripts/python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
  ```
  Free the port on Windows:
  ```bash
  powershell -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen | Select -Expand OwningProcess -Unique | ForEach { Stop-Process -Id $_ -Force }"
  ```

- **413 `Request too large ... TPM Limit 8000`** (2026-09-17): the Groq FREE
  tier allows only 8000 tokens/minute, and a request costs `input + max_tokens`.
  `max_tokens=8192` alone exceeded the limit. Fixed by defaulting
  `GROQ_MAX_TOKENS` to 1500 so the full generate+translate flow fits.

- **Translation content came back empty** (2026-09-17): `gpt-oss-20b` is a
  *reasoning* model. Measured usage showed ~854 of 1500 output tokens spent on
  hidden reasoning, starving the actual translation. The installed `groq` SDK
  (0.26.0) was too old to accept `reasoning_effort`. Fixed by upgrading
  (`uv pip install --upgrade groq langchain-groq` -> groq 0.37.1,
  langchain_groq 1.1.3) and setting `GROQ_REASONING_EFFORT=low`, which dropped
  reasoning to ~5 tokens. End-to-end generate + translate now works.
