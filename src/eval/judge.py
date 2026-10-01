"""LLM-as-judge: score a blog against a fixed rubric, returning structured scores."""

from pydantic import BaseModel, Field

from src.nodes.blog_node import with_retry


class Score(BaseModel):
    """A blog's scorecard (each dimension 1-10)."""

    grounding: int = Field(description="1-10: are claims supported by cited sources?")
    structure: int = Field(description="1-10: logical flow, headings, readability.")
    clarity: int = Field(description="1-10: clear, concise, engaging writing.")
    seo: int = Field(description="1-10: SEO-friendly title, keywords, meta-worthiness.")
    overall: int = Field(description="1-10: overall quality.")
    rationale: str = Field(description="One or two sentences justifying the scores.")


@with_retry
def _judge_call(llm, prompt: str) -> Score:
    return llm.with_structured_output(Score).invoke(prompt)


def judge_blog(llm, topic: str, content: str) -> Score:
    """Score a blog using an LLM as judge (structured output, with retries)."""
    prompt = (
        "You are a strict, fair blog-quality judge. Score the blog below on each "
        "dimension from 1 to 10 and give a brief rationale. Be consistent and "
        "critical.\n\n"
        f"TOPIC: {topic}\n\nBLOG:\n{content}"
    )
    return _judge_call(llm, prompt)
