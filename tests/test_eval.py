"""Tests for the LLM-as-judge (mocked, no real LLM)."""

from src.eval.judge import Score, judge_blog


class _FakeStructured:
    def __init__(self, result):
        self.result = result

    def invoke(self, prompt):
        return self.result


class FakeJudgeLLM:
    """Returns a canned Score from with_structured_output(...).invoke(...)."""

    def __init__(self, score: Score):
        self.score = score

    def with_structured_output(self, schema):
        return _FakeStructured(self.score)


def test_judge_returns_structured_score():
    canned = Score(grounding=8, structure=7, clarity=9, seo=6, overall=8, rationale="solid")
    result = judge_blog(FakeJudgeLLM(canned), "Docker", "some content")
    assert result.overall == 8
    assert result.grounding == 8
