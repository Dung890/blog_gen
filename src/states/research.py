"""Data shapes for the deep-research pipeline.

Everything downstream (workers, gap check, synthesizer, writer, critic) reads or
writes these, so they're defined once, here.
"""

from operator import add
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from src.states.blogstate import Critique, merge_blog


class EvidenceRecord(BaseModel):
    """One piece of researched evidence. The core artifact of deep research."""

    id: str = Field(description="Stable id like 'E01', referenced by the outline.")
    claim: str = Field(description="What the researcher learned.")
    source_url: str = Field(description="Where it came from.")
    source_title: str = Field(description="Title of the source.")
    supporting_passage: str = Field(description="The text that actually supports the claim.")
    date: str | None = Field(default=None, description="Publication date, if known (freshness).")
    location: str | None = Field(default=None, description="Page/section for traceability.")
    limitations: str | None = Field(default=None, description="Conflicts/conditions to preserve.")


class ResearchAssignment(BaseModel):
    """A single worker's brief — not just a question."""

    question: str = Field(description="The sub-question this worker must answer.")
    out_of_scope: str = Field(description="What this worker should NOT cover (avoid overlap).")
    evidence_to_find: str = Field(description="What kind of evidence to look for.")
    search_budget: int = Field(default=3, description="Max searches allowed for this assignment.")


class OutlineSection(BaseModel):
    """A planned section carrying its intended claims and their evidence."""

    heading: str = Field(description="Section heading.")
    claims: list[str] = Field(description="Claims this section will make.")
    evidence_ids: list[str] = Field(description="IDs of evidence supporting the claims.")
    unresolved: str | None = Field(default=None, description="Known gaps for this section.")

class GapAssessment(BaseModel):
    """The gap check's verdict on the gathered evidence."""

    sufficient: bool = Field(description="True if the evidence adequately covers the topic.")
    missing: list[ResearchAssignment] = Field(
        default_factory=list,
        description="Targeted follow-up assignments for the gaps (empty if sufficient).",
    )

class DeepCritique(BaseModel):
    """The two-part critic's verdict on the deep-research draft."""

    evidence_ok: bool = Field(
        description="True if every claim is supported by cited evidence "
        "(no exaggeration; limitations kept)."
    )
    editorial_ok: bool = Field(
        description="True if the article is clear, coherent, useful, and well-structured."
    )
    passes: bool = Field(description="True only if BOTH checks pass.")
    feedback: str = Field(description="Specific, actionable feedback for revision.")


class DeepResearchState(TypedDict):
    """State for the deep-research graph."""

    topic: str
    assignments: list[ResearchAssignment]
    # `add` (list concatenation) gathers evidence from parallel workers — the
    # same reducer idea as merge_blog, but for a growing list.
    evidence: Annotated[list[EvidenceRecord], add]
    outline: list[OutlineSection]
    blog: Annotated[dict, merge_blog]
    critique: Critique | None
    iterations: int      # revise-loop guard (like the reflection loop)
    rounds: int          # research-round guard (gap-check loop)
    gap: GapAssessment | None
    final_evidence: list[EvidenceRecord]   # globally re-numbered evidence (E01, E02, ...)
    deep_critique: DeepCritique | None
