"""Tests for the graph nodes and the compiled graph, using a fake LLM."""

import asyncio

from src.graphs.graph_builder import GraphBuilder
from src.nodes.blog_node import MAX_REVISIONS, BlogNode
from src.states.blogstate import Critique


async def _fake_search(query, max_results=5):
    return "[1] Example Source\n    URL: https://example.com\n    A relevant snippet."


class FakeResponse:
    """Mimics the object the real LLM returns (it has a .content attribute)."""

    def __init__(self, content: str):
        self.content = content


class _FakeStructured:
    """Mimics llm.with_structured_output(Schema): its .invoke returns a canned object."""

    def __init__(self, result):
        self.result = result

    def invoke(self, prompt):
        return self.result


class FakeLLM:
    """Stand-in for ChatGroq: canned text for .invoke, canned object for structured."""

    def __init__(self, reply: str = "fake output", critique: Critique | None = None):
        self.reply = reply
        # Default critique passes, so the loop ends after one review.
        self.critique = critique or Critique(passes=True, score=9, feedback="great")

    def invoke(self, prompt):
        return FakeResponse(self.reply)

    def with_structured_output(self, schema):
        return _FakeStructured(self.critique)


def test_title_creation_returns_title():
    node = BlogNode(FakeLLM("My Title"))
    result = node.title_creation({"topic": "Docker"})
    assert result["blog"]["title"] == "My Title"


def test_content_generation_returns_content():
    node = BlogNode(FakeLLM("Body text"))
    result = node.content_generation({"topic": "Docker"})
    assert result["blog"]["content"] == "Body text"


def test_topic_graph_produces_title_and_content(monkeypatch):
    monkeypatch.setattr("src.nodes.blog_node.search_web", _fake_search)
    state = asyncio.run(GraphBuilder(FakeLLM()).setup_graph("topic").ainvoke({"topic": "Docker"}))
    assert "title" in state["blog"]
    assert "content" in state["blog"]


def test_language_graph_translates():
    graph = GraphBuilder(FakeLLM("translated")).setup_graph("language")
    state = graph.invoke({"topic": "Docker", "current_language": "french"})
    assert state["blog"]["title"] == "translated"
    assert state["blog"]["content"] == "translated"


def test_loop_stops_when_draft_passes(monkeypatch):
    monkeypatch.setattr("src.nodes.blog_node.search_web", _fake_search)
    llm = FakeLLM(reply="draft", critique=Critique(passes=True, score=9, feedback="great"))
    state = asyncio.run(GraphBuilder(llm).setup_graph("topic").ainvoke({"topic": "Docker"}))
    assert state.get("iterations", 0) == 0


def test_loop_revises_then_stops_at_cap(monkeypatch):
    monkeypatch.setattr("src.nodes.blog_node.search_web", _fake_search)
    llm = FakeLLM(reply="draft", critique=Critique(passes=False, score=3, feedback="fix it"))
    state = asyncio.run(GraphBuilder(llm).setup_graph("topic").ainvoke({"topic": "Docker"}))
    assert state["iterations"] == MAX_REVISIONS
