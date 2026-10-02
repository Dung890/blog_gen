"""The shared state that flows through the blog-generation graph.

As the graph runs, each node returns a small partial update (e.g. just the
title, or just the content). LangGraph needs to know how to combine those
partial updates with what's already in the state. By default it *replaces* a
field's value; for ``blog`` we instead *merge*, so a node that only sets the
content does not accidentally erase the title.
"""

from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


class Blog(BaseModel):
    """Structured shape of a finished blog post."""

    title: str = Field(description="The title of the blog post")
    content: str = Field(description="The main content of the blog post")


class Critique(BaseModel):
    passes: bool = Field(description="True if the draft meets the quality bar (score >= 8).")
    score: int = Field(description="Overall quality score from 1 to 10.")
    feedback: str = Field(description="Specific, actionable feedback for improvement.")


def merge_blog(existing: dict | None, new: dict | None) -> dict:
    """Reducer for the ``blog`` field: shallow-merge partial updates.

    LangGraph calls this whenever a node returns a ``blog`` value. Instead of
    overwriting the whole dict, we combine the old and new keys, so returning
    ``{"content": ...}`` keeps a title that was set earlier.
    """
    existing = existing or {}
    new = new or {}
    return {**existing, **new}


class BlogState(TypedDict):
    topic: str
    blog: Annotated[dict, merge_blog]
    current_language: str
    critique: Critique | None  # the latest self-review
    iterations: int  # how many revise cycles we've done (loop guard)
    research: str            # <- raw web-search results to ground the content
    memory_notes: str        # related past articles recalled from long-term memory
