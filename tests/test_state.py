"""Tests for the blog state reducer - pure logic, no LLM involved."""

from src.states.blogstate import merge_blog


def test_merge_combines_partial_updates():
    # title set earlier + content set later should merge into both.
    assert merge_blog({"title": "T"}, {"content": "C"}) == {"title": "T", "content": "C"}


def test_merge_handles_none():
    # A None on either side should behave like an empty dict.
    assert merge_blog(None, {"title": "T"}) == {"title": "T"}
    assert merge_blog({"title": "T"}, None) == {"title": "T"}


def test_new_value_overrides_same_key():
    assert merge_blog({"title": "old"}, {"title": "new"}) == {"title": "new"}
