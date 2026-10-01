"""Deep-research worker: turn one assignment into structured evidence."""

from langgraph.types import Send
from pydantic import BaseModel, Field

from src.config.logging import get_logger
from src.nodes.blog_node import MAX_REVISIONS, with_retry
from src.states.research import (
    DeepCritique,
    DeepResearchState,
    EvidenceRecord,
    GapAssessment,
    OutlineSection,
    ResearchAssignment,
)
from src.tools.search import search_web

MAX_ROUNDS = 2  # hard cap on research rounds (gap-check loop guard)

log = get_logger("research")



class _EvidenceList(BaseModel):
    """Wrapper so the model can return several EvidenceRecords via structured output."""

    records: list[EvidenceRecord] = Field(description="Evidence extracted from the sources.")


@with_retry
def _extract(llm, prompt: str) -> _EvidenceList:
    """Structured extraction call, with the same retry armor as everything else."""
    return llm.with_structured_output(_EvidenceList).invoke(prompt)

@with_retry
def _gap_call(llm, prompt: str) -> GapAssessment:
    return llm.with_structured_output(GapAssessment).invoke(prompt)

@with_retry
def _critic_call(llm, prompt: str) -> DeepCritique:
    return llm.with_structured_output(DeepCritique).invoke(prompt)

class _Outline(BaseModel):
    sections: list[OutlineSection] = Field(
        description="Outline sections, each citing evidence IDs."
    )


@with_retry
def _outline_call(llm, prompt: str) -> _Outline:
    return llm.with_structured_output(_Outline).invoke(prompt)


@with_retry
def _generate(llm, prompt: str) -> str:
    """Plain-text generation with retry (for the long-form draft)."""
    return llm.invoke(prompt).content


async def research_one(llm, assignment: ResearchAssignment) -> list[EvidenceRecord]:
    """Search for the assignment's question and extract structured evidence.

    Degrades gracefully: if the search returns nothing (e.g. the search engine
    rate-limits us) or extraction fails, this worker contributes no evidence
    instead of crashing the whole pipeline.
    """
    results = await search_web(assignment.question, max_results=assignment.search_budget)
    if not results.strip() or results.strip() == "No results found.":
        log.warning("research_worker_no_results", question=assignment.question[:80])
        return []

    prompt = (
        "You are a research assistant. From the SEARCH RESULTS below, extract the "
        "evidence that answers the QUESTION. For each finding give: a short id "
        "(E01, E02, ...), the claim, the source URL and title, the supporting "
        "passage, and any limitations. Include ONLY evidence relevant to the "
        "question; ignore anything in OUT OF SCOPE.\n\n"
        f"QUESTION: {assignment.question}\n"
        f"EVIDENCE TO FIND: {assignment.evidence_to_find}\n"
        f"OUT OF SCOPE: {assignment.out_of_scope}\n\n"
        f"SEARCH RESULTS:\n{results}"
    )
    try:
        return _extract(llm, prompt).records
    except Exception as exc:  # noqa: BLE001 - one worker failing must not kill the run
        log.warning("research_worker_extract_failed", error=str(exc)[:120])
        return []

class _AssignmentList(BaseModel):
    assignments: list[ResearchAssignment] = Field(
        description="3-5 research assignments covering distinct angles."
    )


@with_retry
def _plan_call(llm, prompt: str) -> _AssignmentList:
    return llm.with_structured_output(_AssignmentList).invoke(prompt)


class ResearchNodes:
    """Graph nodes for the deep-research pipeline, sharing one LLM."""

    def __init__(self, llm):
        self.llm = llm

    def plan(self, state: DeepResearchState) -> dict:
        """Decompose the topic into focused, non-overlapping research assignments."""
        prompt = (
            "You are a research lead. Break the TOPIC into 3-5 focused research "
            "assignments covering DISTINCT angles. Each needs: a specific question, "
            "what is out of scope (so workers don't overlap), what evidence to find, "
            "and a search budget (2-4).\n\n"
            f"TOPIC: {state['topic']}"
        )
        try:
            assignments = _plan_call(self.llm, prompt).assignments
        except Exception as exc:  # noqa: BLE001 - fall back to a single broad assignment
            log.warning("planner_failed", error=str(exc)[:120])
            assignments = [
                ResearchAssignment(
                    question=state["topic"],
                    out_of_scope="",
                    evidence_to_find="key facts and reputable sources",
                )
            ]
        return {"assignments": assignments}

    async def worker(self, state: dict) -> dict:
        """One research worker: turn its assigned question into evidence."""
        records = await research_one(self.llm, state["assignment"])
        return {"evidence": records}

    def gap_check(self, state: DeepResearchState) -> dict:
        """Assess whether the evidence is sufficient; if not, plan targeted follow-ups."""
        evidence = "\n".join(f"[{e.id}] {e.claim} ({e.source_url})" for e in state["evidence"])
        questions = "\n".join(f"- {a.question}" for a in state["assignments"])
        prompt = (
            "You are a research editor. Decide whether the EVIDENCE sufficiently "
            "covers the QUESTIONS for a well-grounded article on the TOPIC. If gaps "
            "remain, return targeted follow-up assignments; if coverage is good, set "
            "sufficient=true with no follow-ups.\n\n"
            f"TOPIC: {state['topic']}\n\nQUESTIONS:\n{questions}\n\nEVIDENCE:\n{evidence}"
        )
        try:
            assessment = _gap_call(self.llm, prompt)
        except Exception as exc:  # noqa: BLE001 - if we can't assess, proceed with what we have
            log.warning("gap_check_failed", error=str(exc)[:120])
            assessment = GapAssessment(sufficient=True)
        return {"gap": assessment, "rounds": state.get("rounds", 0) + 1}

    def synthesize(self, state: DeepResearchState) -> dict:
        """Re-number evidence globally, then build an outline that cites it."""
        reided = [
            e.model_copy(update={"id": f"E{i:02d}"})
            for i, e in enumerate(state["evidence"], start=1)
        ]
        evidence_block = "\n".join(
            f"[{e.id}] {e.claim} - {e.source_title} ({e.source_url})" for e in reided
        )
        prompt = (
            "You are a content strategist. Using the EVIDENCE, produce an outline for "
            "an article on the TOPIC. For each section give a heading, the claims it "
            "will make, and the evidence IDs (e.g. E01, E07) that support them. Note "
            "anything unresolved.\n\n"
            f"TOPIC: {state['topic']}\n\nEVIDENCE:\n{evidence_block}"
        )
        try:
            outline = _outline_call(self.llm, prompt).sections
        except Exception as exc:  # noqa: BLE001 - writer can still work from evidence alone
            log.warning("synthesize_failed", error=str(exc)[:120])
            outline = []
        return {"outline": outline, "final_evidence": reided}

    def write(self, state: DeepResearchState) -> dict:
        """Write the blog, following the outline and grounded in the cited evidence."""
        evidence = state.get("final_evidence", [])
        evidence_block = "\n".join(
            f"[{e.id}] {e.claim} - {e.source_title} ({e.source_url}): {e.supporting_passage}"
            for e in evidence
        )
        outline_block = "\n".join(
            f"## {s.heading}\n  claims: {'; '.join(s.claims)}\n"
            f"  evidence: {', '.join(s.evidence_ids)}"
            for s in state.get("outline", [])
        )
        prompt = (
            "You are an expert blog writer. Write a detailed Markdown article that "
            "follows the OUTLINE and is grounded in the EVIDENCE. Cite evidence inline "
            "as [E01] and include source URLs. Start with an H1 title and end with a "
            "'## Sources' section listing the URLs.\n\n"
            f"TOPIC: {state['topic']}\n\nOUTLINE:\n{outline_block}\n\nEVIDENCE:\n{evidence_block}"
        )
        content = _generate(self.llm, prompt)
        first = content.strip().splitlines()[0] if content.strip() else ""
        title = first.lstrip("# ").strip() or state["topic"]
        return {"blog": {"title": title, "content": content}}

    def critic(self, state: DeepResearchState) -> dict:
        """Two checks: evidence support + editorial quality."""
        content = state["blog"].get("content", "")
        evidence_block = "\n".join(
            f"[{e.id}] {e.claim} ({e.source_url})" for e in state.get("final_evidence", [])
        )
        prompt = (
            "You are a fact-checker and editor. Run TWO checks on the DRAFT:\n"
            "1) EVIDENCE: is every claim supported by the EVIDENCE? Flag exaggerations "
            "or dropped limitations.\n"
            "2) EDITORIAL: is it clear, coherent, useful, well-structured?\n"
            "Return evidence_ok, editorial_ok, passes (true only if BOTH pass), and "
            "specific feedback.\n\n"
            f"EVIDENCE:\n{evidence_block}\n\nDRAFT:\n{content}"
        )
        try:
            critique = _critic_call(self.llm, prompt)
        except Exception as exc:  # noqa: BLE001 - don't let a critic hiccup crash the run
            log.warning("deep_critic_failed", error=str(exc)[:120])
            critique = DeepCritique(evidence_ok=True, editorial_ok=True, passes=True, feedback="")
        return {"deep_critique": critique}

    def revise(self, state: DeepResearchState) -> dict:
        """Rewrite the draft to address the critique, staying grounded in evidence."""
        content = state["blog"].get("content", "")
        critique = state.get("deep_critique")
        feedback = critique.feedback if critique else ""
        evidence_block = "\n".join(
            f"[{e.id}] {e.claim} - {e.source_title} ({e.source_url}): {e.supporting_passage}"
            for e in state.get("final_evidence", [])
        )
        prompt = (
            "Revise the DRAFT to address the FEEDBACK while staying grounded in the "
            "EVIDENCE. Keep Markdown formatting and an accurate '## Sources' section. "
            "Return ONLY the revised Markdown.\n\n"
            f"FEEDBACK:\n{feedback}\n\nEVIDENCE:\n{evidence_block}\n\nDRAFT:\n{content}"
        )
        return {"blog": {"content": _generate(self.llm, prompt)},
                "iterations": state.get("iterations", 0) + 1}

    def route_after_critic(self, state: DeepResearchState) -> str:
        """Revise again, or finish (passes or hit the revision cap)."""
        critique = state.get("deep_critique")
        iterations = state.get("iterations", 0)
        if critique is None or critique.passes or iterations >= MAX_REVISIONS:
            return "end"
        return "revise"


def assign_workers(state: DeepResearchState) -> list[Send]:
    """Fan out: one parallel worker per assignment (LangGraph Send API)."""
    return [Send("research_worker", {"assignment": a}) for a in state["assignments"]]

def route_after_gap(state: DeepResearchState) -> str | list[Send]:
    """Loop back for targeted follow-up research, or proceed once coverage is good."""
    assessment = state.get("gap")
    rounds = state.get("rounds", 0)
    if (
        assessment is None
        or assessment.sufficient
        or rounds >= MAX_ROUNDS
        or not assessment.missing
    ):
        return "proceed"
    # Fan out again, but only for the specific gaps.
    return [Send("research_worker", {"assignment": a}) for a in assessment.missing]

