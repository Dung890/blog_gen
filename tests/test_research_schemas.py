"""Tests for the deep-research schemas and the evidence reducer."""

from operator import add

from src.states.research import EvidenceRecord, OutlineSection, ResearchAssignment


def _ev(id_: str) -> EvidenceRecord:
    return EvidenceRecord(
        id=id_, claim="c", source_url="u", source_title="t", supporting_passage="p"
    )


def test_evidence_optional_fields_default_none():
    e = _ev("E01")
    assert e.date is None and e.location is None and e.limitations is None


def test_evidence_reducer_concatenates():
    # This is how parallel workers' evidence gets gathered into one list.
    combined = add([_ev("E01")], [_ev("E02"), _ev("E03")])
    assert [e.id for e in combined] == ["E01", "E02", "E03"]


def test_assignment_has_scope_and_budget():
    a = ResearchAssignment(
        question="q", out_of_scope="x", evidence_to_find="stats", search_budget=2
    )
    assert a.search_budget == 2


def test_outline_section_carries_evidence_ids():
    s = OutlineSection(heading="h", claims=["c1"], evidence_ids=["E01", "E07"])
    assert s.evidence_ids == ["E01", "E07"]
