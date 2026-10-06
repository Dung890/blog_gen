# Blog Generator — Enhancement Roadmap

A phased plan to take this project from a tutorial-grade LangGraph app to a
production-ready, agentic, deep-research blog generation platform.

**Goal:** all three of — portfolio showcase, real product/SaaS, and learning
playground. Build toward production while learning and demoing at every phase.

---

## 1. Current State (baseline)

A clean but tutorial-grade app:

- **API:** FastAPI, single `POST /blogs` endpoint.
- **LLM:** Groq (`llama-3.1-8b-instant`).
- **Graph:** LangGraph, two pipelines:
  - *topic:* title → content
  - *language:* title → content → route → translate (hindi/french)
- **State:** Pydantic `Blog` model + `BlogState` TypedDict.

It works, but it is a linear prompt chain (not yet an agent) and lacks
production hygiene.

### Known bugs / issues to fix

- `src/nodes/blog_node.py` — `translation()` stores a whole `Blog` object
  *inside* `blog.content` and **drops the title**. Translated output is malformed.
- `app.py` and `src/llms/groqllm.py` — API keys are `print()`ed to stdout
  (secret leak into logs).
- `BlogState.blog` has **no reducer**, so nodes overwrite the whole dict
  instead of merging — fragile as nodes are added.
- `route_decision` only handles hindi/french; any other language crashes the graph.
- No error handling, timeouts, tests, or auth.

---

## 2. Target Architecture

```
blog_gen/
├── src/
│   ├── config/          # pydantic-settings, typed env, logging setup
│   ├── llms/            # provider abstraction (Groq + fallback), model router
│   ├── states/          # BlogState with reducers, typed I/O schemas
│   ├── nodes/           # research, outline, draft, critique, revise, translate, seo
│   ├── graphs/          # composable graph builder + checkpointer
│   ├── tools/           # web search, RAG retriever (via MCP)
│   ├── eval/            # LLM-judge, rubrics, datasets
│   └── api/             # FastAPI routers, request/response models, SSE streaming
├── frontend/            # Streamlit (fast) or Next.js (polished)
├── tests/
├── Dockerfile · docker-compose.yml · .github/workflows/ci.yml
└── pyproject.toml (ruff, mypy, pytest configured)
```

---

## 3. Backend Stack (decided)

**Python-only backend. No Express / Node on the backend** — the entire agentic
and memory ecosystem is Python-first, and FastAPI already does everything
Express would (async, SSE/WebSocket, routing, middleware, auth, OpenAPI).

### Core

| Layer | Choice | Why |
|---|---|---|
| API framework | **FastAPI** (keep) | Async, SSE streaming, auto OpenAPI, Pydantic built in |
| Agent orchestration | **LangGraph** (keep) | Reflection loop, parallel subagents, checkpointing, human-in-the-loop |
| LLM layer | **Groq** (fast/cheap) + stronger fallback (Claude/GPT) via **model router** | Cheap for outlines, strong for final draft + fact-check; provider fallback |
| Tool/data connectivity | **MCP** via `langchain-mcp-adapters` | Subagents pull search + source material from MCP servers |
| Config/validation | **pydantic-settings + Pydantic v2** | Typed env, request/response schemas |
| Server | **Uvicorn** (dev) → **Gunicorn + Uvicorn workers** (prod) | Standard async serving |

### State, persistence & memory

| Need | Choice | Why |
|---|---|---|
| Graph checkpointing | **LangGraph Postgres checkpointer** (SQLite in dev) | Resumable runs, HITL pauses, inspectable state |
| App database | **Postgres** (+ SQLAlchemy/SQLModel) | Users, blogs, run history, API keys |
| Vector store | **pgvector** (start) → Qdrant if outgrown | RAG grounding + research-note memory |
| Cache / rate limit / queue broker | **Redis** | Response cache, rate limiting, Celery broker |

### Async & long-running work

Deep-research runs take 30s–several minutes → too long for a normal HTTP request.

- **Celery (or ARQ) + Redis** for background jobs: kick off a run, return a
  `job_id`, stream progress via **SSE/WebSocket**, store the result.

### Ops

- **Docker + docker-compose** (api, worker, postgres, redis) — one-command local stack.
- **LangSmith** tracing (already wired) + `structlog` app logs.
- **GitHub Actions** CI: ruff + mypy + pytest.

### Request shape

```
Client ──HTTP──> FastAPI
                   ├─ fast mode:  invoke LangGraph inline, stream via SSE
                   └─ deep mode:  enqueue Celery job → return job_id
                                     worker runs deep-research graph
                                       ├─ subagents call MCP tools (search/docs)
                                       ├─ checkpoints to Postgres
                                       └─ writes result + notes (pgvector)
                   progress/results streamed back via SSE/WebSocket
Redis: cache · rate limit · Celery broker
```

**Frontend note:** Node/JS is only needed if you choose a React/Next.js
frontend (Phase 3), and even then Node just runs the UI, which calls FastAPI
over HTTP/SSE — it never touches the agents. Streamlit (Python) needs no Node.

---

## 4. MCP Integration

MCP is the *hands*; the deep-research graph is the *plan*.

**Direction A — app as MCP *client* (consume tools):** research nodes discover
tools at runtime via `langchain-mcp-adapters`.
- Search/data: Tavily/Brave/SearXNG, Wikipedia, arXiv → grounded, cited content.
- Source material: Notion, Google Drive, GitHub, Postgres → write from *our*
  docs/repo, not generic web fluff (killer use case for on-brand content).
- Payoff: adding/swapping a data source becomes config, not code.

**Direction B — app *as* an MCP server (expose blog generation):** wrap the
pipeline as MCP tools (`research_topic`, `generate_outline`, `draft_blog`,
`translate`, `publish`) so Claude Desktop / Cursor / any MCP client can drive it.
- Payoff: strong showcase; forces a clean tool boundary.

**Direction C — MCP for output/distribution:** Notion / WordPress / Ghost /
Slack MCP servers to publish or share — gated behind human approval (outward-facing).

**Order:** A first (biggest quality lift) → B as the portfolio flourish.

---

## 5. Deep-Research Agentic Workflow

Turn the linear chain into an **orchestrator–worker (supervisor) multi-agent system**:

```
Planner
  → decomposes topic into STRUCTURED ASSIGNMENTS (not just sub-questions)
  → spawns N research subagents IN PARALLEL (Send API)
       each: search (via MCP) → read → extract STRUCTURED EVIDENCE RECORDS
  → gap check: returns SPECIFIC missing evidence ──no──> targeted re-assignment
       (preserve completed research; obey a stopping rule / budget)
  → synthesizer: outline where each SECTION carries its claims + evidence IDs
  → writer: drafts sections grounded in the cited evidence
  → critic: TWO checks — evidence verification + editorial ──> revise loop
       (missing evidence → back to research; writing issues → back to revision)
  → SEO + translate + (approval) publish
```

**Foundational artifact — define this FIRST** (everything depends on it): the
**Evidence Record**. Research, gap-checking, writing, and verification all read/write it.

```python
class EvidenceRecord(BaseModel):
    id: str  # stable id, e.g. "E07" — referenced by the outline
    claim: str  # what the researcher learned
    source_url: str
    source_title: str
    supporting_passage: str  # the actual text that supports the claim
    date: str | None  # freshness
    location: str | None  # page/section for traceability
    limitations: str | None  # conflicts/conditions the writer MUST preserve
```
Keep the full records available end-to-end — summaries alone lose qualifications
that matter.

**The five design refinements (must implement):**

1. **Structured assignments, not bare questions.** The planner emits, per worker:
   the question, what's *out of scope* (avoid duplicate work), what evidence to
   look for, and a search/time budget. Default 3–5 sub-questions; fewer for narrow topics.
2. **Structured evidence records** (schema above) — the most important choice.
3. **Gap check returns specific missing evidence**, not "enough?". It checks: every
   required sub-question answered? central claims supported? conflicting findings?
   important limitations missing? If lacking, emit a *targeted* assignment (e.g.
   "find independent evidence for this performance claim") and **preserve** completed
   research. Stopping rule: max extra rounds + total budget; if exhausted, narrow/qualify claims.
4. **Outline carries evidence.** Each section = heading + intended claims +
   evidence IDs + any "unresolved" note — so the writer has a concrete basis:
   ```
   Section: Where automated quoting still needs human review
   Claims:  Ambiguous requirements; incomplete specifications
   Evidence: E07, E12
   Unresolved: No reliable estimate of how often these cases occur
   ```
5. **Split critic into two checks.** *Evidence:* does the cited passage support the
   sentence? did the draft exaggerate or drop a limitation? → missing evidence goes
   back to research (or the claim is removed). *Writing:* clear, coherent, useful,
   on-audience? → goes back to revision. **Recheck any claim introduced/changed
   during revision.**

**Not everything needs to be an autonomous agent.** Planner, gap-checker, and
synthesizer start as *structured model calls* (one LLM call returning a Pydantic
object). Only the **research workers** need the real search/read *tool loop*.

Other techniques that make it credible:
- **Parallel subagents** with isolated context windows (one angle each) — faster, higher recall.
- **Citation tracking** — every claim links to an evidence id; critic rejects uncited claims.
- **Contradiction/quality scoring** — flag conflicting findings for follow-up.
- **Research memory** — cache evidence in a vector store for reuse across runs.

**Build order:** (1) `EvidenceRecord` + assignment/outline schemas → (2) a single
research worker (search→evidence) → (3) planner fan-out (`Send`) + notes reducer →
(4) gap check + stopping rule → (5) synthesizer → (6) writer → (7) two-part critic loop.

**Caveat:** parallel multi-agent research burns far more tokens/latency (hard on
the 8000 TPM free tier). Keep a fast single-pass mode too; let users choose depth.

---

## 6. Memory Design

Two horizons, distinct stores and write rules. LangGraph gives two primitives:
the **checkpointer** (short-term, thread-scoped) and the **Store** (long-term,
cross-thread). Don't conflate them.

### Short-term (working memory, one run — `thread_id`)

| Concern | Mechanism | Store |
|---|---|---|
| Evolving blog state | LangGraph `BlogState` node→node | in-memory during run |
| Resumability / HITL / crash recovery | LangGraph checkpointer keyed by `thread_id` | Postgres (SQLite dev) |
| Subagent message history | trace in state, with reducers | checkpointed |

**Context-overflow handling (the hard part):**
- Each subagent runs in its **own isolated context** (parallel) — no cross-pollution.
- Subagents return **compressed cited notes** ("finding + source URL"), *not*
  raw pages. Only notes flow up. Note-taking as memory keeps token budget sane.
- **Summarize-and-prune** long subagent histories into a running summary.
- **Redis** caches search results / fetched pages so retries don't re-fetch.
- Keep completed threads for inspection; expire on TTL.

### Long-term (across runs) — LangGraph `Store` + pgvector

| Type | Question it answers | Store | Retrieval |
|---|---|---|---|
| **Semantic** (facts & research notes) | "What do we already know about X?" | pgvector (namespaced notes) | vector similarity on sub-questions |
| **Episodic** (past blogs & good examples) | "What did we write before / a good example?" | Postgres + pgvector | similarity + metadata filter |
| **Procedural** (user/brand style) | "How should this user's blogs look?" | Postgres (structured) | direct lookup by `user_id` |

- **Semantic:** reusable cited findings; dedup + timestamp so stale facts get re-verified.
- **Episodic:** finished posts + quality scores; used for few-shot and to avoid repeats.
- **Procedural:** tone, audience, banned words, house style, SEO rules; injected
  into every prompt — this is what makes output on-brand instead of generic.

### How the layers connect in a run

```
new run (thread_id, user_id)
  ├─ load PROCEDURAL memory (user style) ──> into every prompt
  ├─ query SEMANTIC memory (prior notes on topic) ──> seed research, skip known
  ├─ query EPISODIC memory (similar past posts) ──> few-shot the writer
  ├─ deep-research runs on SHORT-TERM state (checkpointed to Postgres)
  │     subagents → compressed cited notes → synthesizer → draft → critic
  └─ on completion, WRITE BACK to long-term:
        new cited facts    → semantic (pgvector)
        finished post+score → episodic (Postgres/pgvector)
        learned prefs       → procedural (with user confirmation)
```

### Open decisions

1. **Write policy** — auto-persist vs. human-approved. (Suggest: gate procedural
   on confirmation; auto semantic with dedup.)
2. **Retrieval budget** — how many past notes/examples to inject (recall vs. cost). Start top-3–5.
3. **Forgetting/decay** — TTL + re-verification on semantic facts (avoid stale citations).
4. **Scoping** — per-user isolation vs. shared org knowledge base (namespacing handles both).

**Net:** no new infra beyond the chosen stack — Postgres + pgvector do double duty.

---

## 7. Phased Delivery Plan

Each phase is independently shippable and demoable. Introduce services only as
the phase needs them (don't over-engineer an empty app).

### Phase 0 — Stop the bleeding (½–1 session) ✅ DONE (2026-09-17)
*Goal: nothing broken, nothing leaking.* — see `docs/phase-0-changes.md`
- [x] Fix the translation bug (drops title + nests a Blog in `content`).
- [x] Remove API-key prints; load config via `pydantic-settings` with startup validation.
- [x] Add a `blog` state reducer so nodes merge instead of overwrite.
- [x] Make translation handle any language (killed hindi/french hardcoding + route node).
- [x] Bonus: `.env` git-ignored, fail-fast on empty key, lazy Studio graph (no import side-effects).
- **Deliverable:** correct output, no secret leaks. Demoable baseline. ✅

### Phase 1 — Production foundation ✅ DONE (2026-09-20)
*Goal: deployable, testable, observable.* (guided/teaching build) — see `docs/phase-1-changes.md`
- [x] Typed FastAPI request model (`BlogRequest`); clean OpenAPI docs. *(done in Phase 0)*
- [x] `tenacity` retries + timeouts on LLM calls (`_invoke` wrapper, `_is_retryable`). *(Lesson 1)*
- [x] `structlog` structured logging + request IDs; retries logged via `before_sleep`. *(Lesson 2)*
- [x] `pytest` suite (LLM mocked) — 7 tests, reducer + nodes + both graph paths. *(Lesson 3)*
- [x] Typed response model (`BlogResponse`) + structured JSON errors with request_id. *(Lesson 4)*
- [x] Dockerfile + `.dockerignore` + compose — builds & runs; verified live in a container. *(Lesson 5)*
- [x] `ruff` + `mypy` clean (13 files); config in `pyproject.toml`. *(Lesson 6)*
- [x] GitHub Actions CI — repo at github.com/Dung890/blog_gen; `.github/workflows/ci.yml`
      runs ruff + mypy + pytest on every push/PR. First run green. *(done)*
- **Deliverable:** resilient, observable, tested, containerized service. ✅
- [ ] LangGraph checkpointer (SQLite → Postgres) for resumable, inspectable runs.
- **Stack in play:** FastAPI + Postgres + SQLite checkpointer + Docker.
- **Deliverable:** `docker compose up` runs a tested, logged service.

### Phase 2 — The AI-engineering leap (3–4 sessions) — IN PROGRESS
*Goal: quality that's measurable, not vibes.* (guided/teaching build)
- [x] Reflection loop: `content → critique(rubric) → revise` with `MAX_REVISIONS` guard,
      structured `Critique`, conditional edges + backward loop edge. Verified live. *(Phase 2 Lesson 1)*
- [x] **MCP grounding**: own `web_search` MCP server (`mcp_servers/search_server.py`,
      ddgs) consumed via `langchain-mcp-adapters` (`src/tools/search.py`); async
      `research` node grounds content with real cited Sources. Verified live. *(Phase 2 Lesson 2)*
- [x] Eval harness: LLM-as-judge (`src/eval/`) scoring grounding/structure/clarity/SEO
      across a dataset; scorecard via `python -m src.eval.run_eval`. Retry now also covers
      intermittent `tool_use_failed`; logging is UTF-8/crash-safe. Verified live. *(Phase 2 Lesson 3)*
- [x] Streaming (SSE) — `POST /blogs/stream` emits per-node progress via
      `graph.astream(stream_mode="updates")` + `StreamingResponse`. Verified live. *(Phase 2 Lesson 4)*
- [x] Model routing: `get_llm(tier)` → fast (20b) for most steps, strong (120b) for the
      main content draft; non-breaking (tests use one FakeLLM for both). *(cross-provider
      fallback deferred — needs a second API key.)*
- **Stack added:** Redis + MCP client + SSE streaming.
- **Deliverable:** grounded, self-critiqued blogs with a quality scorecard.

### Phase 2.5 — Deep-research multi-agent (new) — IN PROGRESS
*Goal: the flagship agentic feature.* — see the refined design in §5.
- [x] `EvidenceRecord` + assignment/outline/gap schemas + `DeepResearchState` (evidence reducer). *(2.5 L1)*
- [x] Research worker: assignment → MCP search → structured `EvidenceRecord`s. *(2.5 L2)*
- [x] Planner + parallel fan-out (`Send`) + evidence reducer fan-in. *(2.5 L3)*
- [x] Gap check returns specific missing evidence + stopping rule (`MAX_ROUNDS`); preserves prior research. *(2.5 L4)*
- [x] Synthesizer: re-id evidence globally + outline carrying claims + evidence IDs. *(2.5 L5)*
- [x] Writer: draft grounded in the cited evidence (real academic Sources). Verified live end-to-end. *(2.5 L5)*
- [x] Graceful degradation: workers/planner/gap/synthesizer fall back instead of crashing on empty search or structured-output hiccups. *(2.5 L5)*
- [x] Two-part critic (`DeepCritique`: evidence_ok + editorial_ok) + revise loop with `MAX_REVISIONS`. *(2.5 L6a)*
- [x] `POST /blogs/deep` streaming endpoint + `src/eval/compare.py` (deep vs single-pass, judged). *(2.5 L6b)*
  - First run favored single-pass (8 vs 7) — honest finding: single-pass is already grounded+reflected,
    and deep was handicapped by ddgs rate-limiting (thin evidence). Deep shines on complex topics + a real
    search API; use the harness to tune. The point: measured, not assumed.
- [x] Semantic memory store: `src/memory/store.py` (Neon Postgres + pgvector + local fastembed).
- [x] Memory wired into the fast graph: `recall_memory` before writing (injects related past
      posts into the prompt) + `store_memory` after; `get_memory()` singleton degrades gracefully.
      Verified live (related topic recalls the right prior post). *(deep pipeline wiring: later.)*
- [ ] Optional: expose the pipeline **as an MCP server**. *(later)*
- [ ] Keep a fast single-pass mode alongside deep mode.
- **Stack added:** Celery worker + pgvector (async + memory).
- **Deliverable:** deep-research mode with cited, verified, long-form posts.

### Phase 3 — Product & usability (2–3 sessions) — IN PROGRESS
*Goal: real people can use it.*
- [x] Web frontend (`frontend-web/`): Node/Express serving HTML/CSS/vanilla JS; live SSE
      progress for Fast (`/blogs/stream`) and Deep (`/blogs/deep`); rendered Markdown.
      Backend got CORS. Verified live. *(Phase 3 L1)*
- [x] Redesigned as a "minimal writing studio" (warm white / charcoal / purple, Inter + Lora):
      editorial home screen, home↔article view routing, article canvas, recent drafts via
      localStorage, clean titles. Verified live. *(Phase 3 L2)*
- [ ] Section editor + export to HTML/`.docx` (Markdown + copy/download done).
- [x] Tone / length / audience controls: `BlogRequest` fields → `_controls` → graph state →
      content prompt; styled dropdowns in the Writing Studio composer. Verified. *(section
      regeneration: later)*
- [x] SEO pack: `seo_pack` node (meta description, slug, tags via LLM; reading time computed
      from word count) → exposed in API `done` event + `/blogs` response → rendered on the
      article page (reading time + tag pills + meta description). Verified live. *(cover-image prompt: later)*
- [ ] Run history; optional human-in-the-loop approval after outline (`interrupt()`).
- [ ] Auth + rate limiting + API keys if multi-tenant.
- **Deliverable:** a polished app fit for users or a recruiter.

**Run the app (two terminals):**
```
# 1) backend
.venv/Scripts/python.exe -m uvicorn app:app --port 8000
# 2) frontend
cd frontend-web && npm install && npm start   # http://localhost:3000
```

---

## 8. Cross-Cutting Habits (from Phase 0)

- Every prompt in a **versioned prompt module** (not inline strings).
- Every LLM call wrapped with **retry + timeout**.
- Every phase **adds tests**.
- Secrets only via typed config; never logged.

---

## 9. Effort Estimate

~10–13 focused sessions end to end, but **each phase stands alone** — the
project is better after every one.
