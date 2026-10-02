"""FastAPI entry point for the blog generator.

Exposes a single ``POST /blogs`` endpoint. Given a ``topic`` (and optionally a
``language``) it runs the LangGraph pipeline and returns the generated blog.
"""

import json
import os
import time
import uuid

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.config import get_settings
from src.config.logging import configure_logging, get_logger
from src.graphs.graph_builder import GraphBuilder
from src.graphs.research_graph import DeepResearchGraphBuilder
from src.llms.groqllm import GroqLLM
from src.memory import get_memory

# Load and validate configuration once at import time. If GROQ_API_KEY is
# missing, the app fails here with a clear error instead of mid-request.
settings = get_settings()
configure_logging()
log = get_logger("blog_gen")
# Enable LangSmith tracing when a key is configured - without printing it.
if settings.langchain_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langchain_api_key
    if settings.langchain_project:
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project

app = FastAPI(title="Blog Generator", version="0.1.0")

# Allow the browser frontend (served by Node on another port) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev-only; restrict to the frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


class BlogRequest(BaseModel):
    """Body for POST /blogs.

    Declaring this model makes FastAPI show an input box on the /docs page and
    validate incoming requests automatically.
    """

    topic: str = Field(..., description="What the blog should be about.", examples=["Agentic AI"])
    language: str | None = Field(
        default=None,
        description="Optional target language to translate into.",
        examples=["spanish"],
    )
    tone: str | None = Field(default=None, description="Writing tone.", examples=["professional"])
    length: str | None = Field(
        default=None, description="short | medium | long.", examples=["medium"]
    )
    audience: str | None = Field(
        default=None, description="Target audience.", examples=["beginners"]
    )


class BlogResponse(BaseModel):
    """Shape of a successful POST /blogs response."""

    topic: str = Field(..., description="The topic the blog was generated for.")
    language: str | None = Field(default=None, description="Target language, if translated.")
    title: str = Field(..., description="The generated (or translated) blog title.")
    content: str = Field(..., description="The generated (or translated) Markdown body.")
    request_id: str = Field(..., description="Trace id for this request (matches the logs).")


# Friendly labels for each graph node, shown as progress during streaming.
STEP_MESSAGES = {
    # blog graph
    "title_creation": "Created the title",
    "do_research": "Researched the web",
    "content_generation": "Drafted the content",
    "critique_draft": "Reviewed the draft",
    "revise": "Revised the draft",
    "translation": "Translated the post",
    # deep-research graph
    "planner": "Planned research angles",
    "research_worker": "Gathered evidence",
    "gap_check": "Checked coverage",
    "synthesize": "Built the outline",
    "write": "Wrote the draft",
    "critic": "Fact-checked & reviewed",
}


def _sse(data: dict) -> str:
    """Format a dict as one Server-Sent Event line."""
    return f"data: {json.dumps(data)}\n\n"

def _controls(payload: BlogRequest) -> dict:
    return {
        "tone": payload.tone or "professional",
        "length": payload.length or "medium",
        "audience": payload.audience or "a general audience",
    }

@app.post("/blogs", response_model=BlogResponse)
async def create_blogs(payload: BlogRequest):
    """Generate a blog post from a topic, optionally translated to a language."""
    topic = payload.topic.strip()
    language = (payload.language or "").strip()
    controls = _controls(payload)

    if not topic:
        raise HTTPException(status_code=400, detail="Field 'topic' is required.")

    # Give this request a short unique id and bind it so EVERY log line during
    # this request automatically includes it.
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    log.info("blog_request_started", topic=topic, language=language or None)
    start = time.perf_counter()

    try:
        graph_builder = GraphBuilder(
            GroqLLM().get_llm("fast"), GroqLLM().get_llm("strong"), get_memory()
        )

        if language:
            graph = graph_builder.setup_graph(usecase="language")
            state = await graph.ainvoke(
                {"topic": topic, "current_language": language.lower(), **controls}
            )
        else:
            graph = graph_builder.setup_graph(usecase="topic")
            state = await graph.ainvoke({"topic": topic, **controls})

        blog = state["blog"]
        duration = time.perf_counter() - start
        log.info("blog_request_finished", duration_seconds=round(duration, 2))
        return BlogResponse(
            topic=topic,
            language=language or None,
            title=blog.get("title", ""),
            content=blog.get("content", ""),
            request_id=request_id,
        )
    except Exception as exc:
        duration = time.perf_counter() - start
        log.error("blog_request_failed", error=str(exc), duration_seconds=round(duration, 2))
        raise HTTPException(
            status_code=500,
            detail={
                "error": "generation_failed",
                "message": "Blog generation failed. Please try again shortly.",
                "request_id": request_id,
            },
        ) from exc
    finally:
        # Clear the bound id so it doesn't leak into the next request.
        structlog.contextvars.clear_contextvars()


@app.post("/blogs/stream")
async def stream_blogs(payload: BlogRequest):
    """Stream blog-generation progress to the client as Server-Sent Events."""
    topic = payload.topic.strip()
    language = (payload.language or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Field 'topic' is required.")

    controls = _controls(payload)
    graph_builder = GraphBuilder(
        GroqLLM().get_llm("fast"), GroqLLM().get_llm("strong"), get_memory()
    )
    if language:
        graph = graph_builder.setup_graph(usecase="language")
        graph_input = {"topic": topic, "current_language": language.lower(), **controls}
    else:
        graph = graph_builder.setup_graph(usecase="topic")
        graph_input = {"topic": topic, **controls}

    async def event_stream():
        request_id = uuid.uuid4().hex[:8]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        log.info("blog_stream_started", topic=topic, language=language or None)
        blog: dict = {}
        try:
            yield _sse({"event": "start", "request_id": request_id})
            # astream yields {node_name: that_node's_update} as each node finishes.
            async for update in graph.astream(graph_input, stream_mode="updates"):
                for node, node_update in update.items():
                    # Accumulate the blog as title/content updates arrive.
                    if isinstance(node_update, dict) and isinstance(node_update.get("blog"), dict):
                        blog.update(node_update["blog"])
                    yield _sse({"event": "step", "node": node,
                                "message": STEP_MESSAGES.get(node, node)})
            yield _sse({"event": "done", "request_id": request_id, "blog": blog})
            log.info("blog_stream_finished")
        except Exception as exc:
            log.error("blog_stream_failed", error=str(exc))
            yield _sse({"event": "error", "request_id": request_id,
                        "message": "Blog generation failed."})
        finally:
            structlog.contextvars.clear_contextvars()

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/blogs/deep")
async def deep_blog(payload: BlogRequest):
    """Run the deep-research pipeline, streaming progress as Server-Sent Events."""
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Field 'topic' is required.")

    graph = DeepResearchGraphBuilder(GroqLLM().get_llm()).build()

    async def event_stream():
        request_id = uuid.uuid4().hex[:8]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        log.info("deep_blog_started", topic=topic)
        blog: dict = {}
        try:
            yield _sse({"event": "start", "request_id": request_id})
            async for update in graph.astream({"topic": topic}, stream_mode="updates"):
                for node, node_update in update.items():
                    if isinstance(node_update, dict) and isinstance(node_update.get("blog"), dict):
                        blog.update(node_update["blog"])
                    yield _sse({"event": "step", "node": node,
                                "message": STEP_MESSAGES.get(node, node)})
            yield _sse({"event": "done", "request_id": request_id, "blog": blog})
            log.info("deep_blog_finished")
        except Exception as exc:
            log.error("deep_blog_failed", error=str(exc))
            yield _sse({"event": "error", "request_id": request_id,
                        "message": "Deep research failed."})
        finally:
            structlog.contextvars.clear_contextvars()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
