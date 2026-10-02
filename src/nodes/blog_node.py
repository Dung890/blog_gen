"""Graph nodes that build a blog post step by step.

Each method is a *node*: it receives the current :class:`BlogState`, does one
job (make a title, write content, translate) and returns a partial update.
Thanks to the ``merge_blog`` reducer on the state, a node only needs to return
the field it actually changed.
"""

import groq
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.config.logging import get_logger
from src.states.blogstate import BlogState, Critique
from src.tools.search import search_web

log = get_logger("blog_node")


def _is_retryable(exc: BaseException) -> bool:
    """Return True only for errors that are worth retrying.

    Rate limits (413/429), transient server errors (5xx), timeouts and
    connection blips are temporary - retrying after a wait usually works. A 400
    (bad request) is our fault and will never succeed, so we don't retry it.
    """
    if isinstance(
        exc,
        (
            groq.APIConnectionError,
            groq.APITimeoutError,
            groq.RateLimitError,
            groq.InternalServerError,
        ),
    ):
        return True
    if isinstance(exc, groq.APIStatusError):
        if exc.status_code in (413, 429, 500, 502, 503):
            return True
        # A tool_use_failed 400 is the MODEL intermittently botching structured
        # output (not a bad request from us) - retrying usually succeeds.
        if "tool_use_failed" in str(exc):
            return True
    return False


def _log_retry(retry_state) -> None:
    """Called by tenacity before it sleeps between attempts - logs the retry."""
    log.warning(
        "llm_call_retry",
        attempt=retry_state.attempt_number,
        wait_seconds=round(getattr(retry_state.next_action, "sleep", 0), 1),
        error=str(retry_state.outcome.exception()),
    )


def with_retry(func):
    """Our own decorator: apply the standard retry+backoff policy to a call.

    Wrapping tenacity's `retry` in a plain decorator (instead of unpacking a
    dict of kwargs) keeps the type information intact and reads cleanly.
    """
    return retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry,
        reraise=True,
    )(func)


# Safety cap: never revise more than this many times, no matter what.
MAX_REVISIONS = 2
log = get_logger("blog_node")

_LENGTH_WORDS = {
    "short": "about 500 words",
    "medium": "about 900 words",
    "long": "about 1400 words",
}

class BlogNode:
    """A collection of blog-building steps sharing one LLM."""

    def __init__(self, llm, llm_strong=None, memory=None):
        self.llm = llm
        self.llm_strong = llm_strong or llm  # fall back to the same model if not given
        self.memory = memory  # a MemoryStore, or None if memory is unavailable

    def recall_memory(self, state: BlogState) -> dict:
        """Pull related past articles from long-term memory (safe if memory is off)."""
        if not self.memory:
            return {"memory_notes": ""}
        try:
            hits = self.memory.recall(state["topic"], k=3)
            notes = "\n".join(f"- {h['text']}" for h in hits)
        except Exception as exc:  # noqa: BLE001 - memory must never break generation
            log.warning("recall_failed", error=str(exc)[:120])
            notes = ""
        return {"memory_notes": notes}

    def store_memory(self, state: BlogState) -> dict:
        """Save this finished post to long-term memory (safe if memory is off)."""
        if self.memory:
            blog = state.get("blog", {})
            title = (blog.get("title") or "").strip()
            if title:
                try:
                    self.memory.remember(title, kind="episodic", metadata={"topic": state["topic"]})
                except Exception as exc:  # noqa: BLE001
                    log.warning("store_failed", error=str(exc)[:120])
        return {}

    @with_retry
    def _invoke(self, prompt):
        """Call the LLM, retrying transient failures with backoff."""
        return self.llm.invoke(prompt)

    @with_retry
    def _invoke_strong(self, prompt):
        """Like _invoke, but routed to the stronger model (for the main draft)."""
        return self.llm_strong.invoke(prompt)

    @with_retry
    def _invoke_structured(self, schema, prompt):
        """Like _invoke, but the model must return an object matching `schema`."""
        return self.llm.with_structured_output(schema).invoke(prompt)

    def title_creation(self, state: BlogState) -> dict:
        """Create an SEO-friendly title for the requested topic."""
        prompt = (
            "You are an expert blog content writer. Use Markdown formatting. "
            "Generate a single creative, SEO-friendly blog title for the topic: "
            "{topic}. Return only the title."
        )
        message = prompt.format(topic=state["topic"])
        response = self._invoke(message)
        # Return only the title; the reducer preserves anything else in `blog`.
        return {"blog": {"title": response.content}}

    def content_generation(self, state: BlogState) -> dict:
        """Write the Markdown body, grounded in the research with citations."""
        research = state.get("research", "") or "(no research available)"
        memory_notes = (state.get("memory_notes") or "").strip()
        tone = state.get("tone") or "professional"
        audience = state.get("audience") or "a general audience"
        length = _LENGTH_WORDS.get(state.get("length") or "medium", "about 900 words")
        memory_block = (
            f"\n\nRELATED PAST ARTICLES you've written (for continuity; don't repeat them):\n"
            f"{memory_notes}"
            if memory_notes
            else ""
        )
        prompt = (
            "You are an expert blog writer. Use Markdown formatting. Write "
            f"detailed, well-structured content for the topic: {state['topic']}.\n\n"
            f"Write in a {tone} tone and target {audience}. "
            f"The content should be approximately {length}.\n\n"
            "Ground your writing in the SEARCH RESULTS below. Cite sources inline "
            "with their URLs where relevant, and finish with a '## Sources' section "
            "listing the URLs you used.\n\n"
            f"SEARCH RESULTS:\n{research}{memory_block}"
        )
        response = self._invoke_strong(prompt)
        return {"blog": {"content": response.content}}

    def translation(self, state: BlogState) -> dict:
        """Translate the finished post into ``state['current_language']``.

        Translates the title and the content as PLAIN TEXT (two calls) rather
        than forcing the whole post into a single JSON object. Structured output
        breaks on long blogs: the JSON gets truncated at the token limit and
        fails to parse ("tool_use_failed"). Plain Markdown avoids that entirely.
        """
        language = state["current_language"]
        current = state["blog"]

        title_prompt = (
            f"Translate this blog title into {language}. "
            f"Return ONLY the translated title with no quotes or extra text:\n\n"
            f"{current.get('title', '')}"
        )
        translated_title = self._invoke(title_prompt).content.strip()

        content_prompt = (
            f"Translate the following blog post into {language}.\n"
            f"- Preserve the Markdown formatting exactly.\n"
            f"- Keep the tone and style; adapt idioms naturally for {language}.\n"
            f"- Return ONLY the translated Markdown, with no preamble.\n\n"
            f"{current.get('content', '')}"
        )
        translated_content = self._invoke(content_prompt).content

        return {"blog": {"title": translated_title, "content": translated_content}}

    def critique(self, state: BlogState) -> dict:
        """Score the current draft and produce actionable feedback."""
        content = state["blog"].get("content", "")
        prompt = (
            "You are a strict blog editor. Evaluate the draft below on accuracy, "
            "structure, clarity, and SEO. Give a score from 1-10, decide if it "
            "passes (a pass needs score >= 8), and give specific, actionable "
            "feedback for improvement.\n\n"
            f"DRAFT:\n{content}"
        )
        result = self._invoke_structured(Critique, prompt)
        return {"critique": result}

    def revise(self, state: BlogState) -> dict:
        """Improve the draft using the critique's feedback."""
        content = state["blog"].get("content", "")
        critique = state.get("critique")
        feedback = critique.feedback if critique else ""
        prompt = (
            "Improve the blog draft using the editor's feedback. Preserve Markdown "
            "formatting. Return ONLY the improved Markdown, with no preamble.\n\n"
            f"FEEDBACK:\n{feedback}\n\nDRAFT:\n{content}"
        )
        improved = self._invoke(prompt).content
        iterations = state.get("iterations", 0) + 1
        return {"blog": {"content": improved}, "iterations": iterations}

    def route_after_critique(self, state: BlogState) -> str:
        """Decide whether to revise again or finish (the loop's brain)."""
        critique = state.get("critique")
        iterations = state.get("iterations", 0)
        # Stop if: no critique somehow, OR it passed, OR we've hit the cap.
        if critique is None or critique.passes or iterations >= MAX_REVISIONS:
            return "end"
        return "revise"

    async def research(self, state: BlogState) -> dict:
        """Search the web for the topic and store the results for grounding."""
        results = await search_web(state["topic"], max_results=5)
        return {"research": results}
