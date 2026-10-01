"""Integration tests for the deep-research graph (mocked search + LLM)."""

import asyncio
from types import SimpleNamespace

from src.graphs.research_graph import DeepResearchGraphBuilder
from src.states.research import (
    DeepCritique,
    EvidenceRecord,
    GapAssessment,
    OutlineSection,
    ResearchAssignment,
)


async def _fake_search(query, max_results=5):
    return "[1] Example\n    URL: https://example.com\n    snippet"


class _FakeStructured:
    def __init__(self, result):
        self.result = result

    def invoke(self, prompt):
        return self.result


class FakeLLM:
    """Canned outputs for planner, workers, gap check, outline, and the draft."""

    def __init__(self, assignments, records, gap=None, outline=None, content="draft",
                 deep_critique=None):
        self.assignments = assignments
        self.records = records
        self.gap = gap
        self.outline = outline or []
        self.content = content
        self.deep_critique = deep_critique or DeepCritique(
            evidence_ok=True, editorial_ok=True, passes=True, feedback=""
        )

    def invoke(self, prompt):
        return SimpleNamespace(content=self.content)

    def with_structured_output(self, schema):
        name = schema.__name__
        if "Assignment" in name:
            return _FakeStructured(SimpleNamespace(assignments=self.assignments))
        if "Gap" in name:
            return _FakeStructured(self.gap)
        if "Outline" in name:
            return _FakeStructured(SimpleNamespace(sections=self.outline))
        if "Critique" in name:
            return _FakeStructured(self.deep_critique)
        return _FakeStructured(SimpleNamespace(records=self.records))


def _record(id_: str = "E01") -> EvidenceRecord:
    return EvidenceRecord(
        id=id_, claim="c", source_url="u", source_title="t", supporting_passage="p"
    )


def test_fan_out_gathers_evidence_from_all_workers(monkeypatch):
    monkeypatch.setattr("src.nodes.research_node.search_web", _fake_search)
    assignments = [
        ResearchAssignment(question=f"q{i}", out_of_scope="", evidence_to_find="e")
        for i in range(3)
    ]
    llm = FakeLLM(assignments, [_record()], gap=GapAssessment(sufficient=True))
    state = asyncio.run(DeepResearchGraphBuilder(llm).build().ainvoke({"topic": "Docker"}))
    # 3 workers each returned 1 record -> reducer gathered all 3
    assert len(state["evidence"]) == 3


def test_gap_loop_stops_at_max_rounds(monkeypatch):
    from src.nodes.research_node import MAX_ROUNDS

    monkeypatch.setattr("src.nodes.research_node.search_web", _fake_search)
    assignments = [ResearchAssignment(question="q1", out_of_scope="", evidence_to_find="e")]
    # Always "insufficient" with a follow-up -> loop should stop at MAX_ROUNDS.
    always_gap = GapAssessment(sufficient=False, missing=assignments)
    llm = FakeLLM(assignments, [_record()], gap=always_gap)
    state = asyncio.run(DeepResearchGraphBuilder(llm).build().ainvoke({"topic": "Docker"}))
    assert state["rounds"] == MAX_ROUNDS


def test_deep_graph_produces_blog_and_reids_evidence(monkeypatch):
    monkeypatch.setattr("src.nodes.research_node.search_web", _fake_search)
    assignments = [
        ResearchAssignment(question=f"q{i}", out_of_scope="", evidence_to_find="e")
        for i in range(2)
    ]
    outline = [OutlineSection(heading="H", claims=["c1"], evidence_ids=["E01"])]
    llm = FakeLLM(
        assignments,
        [_record("Exx")],
        gap=GapAssessment(sufficient=True),
        outline=outline,
        content="# My Title\n\nBody [E01].\n\n## Sources\n- u",
    )
    state = asyncio.run(DeepResearchGraphBuilder(llm).build().ainvoke({"topic": "Docker"}))
    assert state["blog"]["title"] == "My Title"
    # 2 workers x 1 record, re-numbered globally -> E01, E02
    assert [e.id for e in state["final_evidence"]] == ["E01", "E02"]


def test_deep_critic_loop_revises_then_stops(monkeypatch):
    from src.nodes.blog_node import MAX_REVISIONS

    monkeypatch.setattr("src.nodes.research_node.search_web", _fake_search)
    assignments = [ResearchAssignment(question="q", out_of_scope="", evidence_to_find="e")]
    failing = DeepCritique(evidence_ok=False, editorial_ok=False, passes=False, feedback="fix")
    llm = FakeLLM(assignments, [_record()], gap=GapAssessment(sufficient=True),
                  deep_critique=failing)
    state = asyncio.run(DeepResearchGraphBuilder(llm).build().ainvoke({"topic": "Docker"}))
    assert state["iterations"] == MAX_REVISIONS
