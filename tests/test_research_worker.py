"""Tests for the research worker (mocked search + LLM)."""

import asyncio
from types import SimpleNamespace

from src.nodes.research_node import research_one
from src.states.research import EvidenceRecord, ResearchAssignment


async def _fake_search(query, max_results=5):
    return "[1] Example\n    URL: https://example.com\n    A snippet."


class _FakeStructured:
    def __init__(self, result):
        self.result = result

    def invoke(self, prompt):
        return self.result


class FakeLLM:
    def __init__(self, records):
        self._records = records

    def with_structured_output(self, schema):
        return _FakeStructured(SimpleNamespace(records=self._records))


def test_research_one_returns_evidence(monkeypatch):
    monkeypatch.setattr("src.nodes.research_node.search_web", _fake_search)
    records = [
        EvidenceRecord(id="E01", claim="c", source_url="https://example.com",
                       source_title="Example", supporting_passage="p")
    ]
    assignment = ResearchAssignment(question="q", out_of_scope="x", evidence_to_find="stats")
    result = asyncio.run(research_one(FakeLLM(records), assignment))
    assert len(result) == 1
    assert result[0].id == "E01"
    assert result[0].source_url == "https://example.com"
