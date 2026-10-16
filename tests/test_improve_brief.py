import pytest
import blog
from conftest import SRC  # noqa: F401  (conftest puts scripts/ on sys.path)

BASE = {"topic": "Tokens", "audience": "front-end leads", "primary_keyword": "design tokens", "tone": "practical"}


def test_create_brief_unchanged(root):
    assert blog.brief_errors({**BASE, "target_words": {"min": 700, "max": 1100}}, root) == []
    errs = blog.brief_errors(BASE, root)
    assert any("target_words" in e for e in errs)  # still required in create mode


def test_improve_brief_needs_source_and_goal(root):
    b = {**BASE, "mode": "improve"}
    errs = blog.brief_errors(b, root)
    assert any(e.startswith("source") for e in errs) and any(e.startswith("goal") for e in errs)
    ok = {**b, "source": {"kind": "local", "ref": "drafts/post.md"}, "goal": ["clarity", "tighten"]}
    assert blog.brief_errors(ok, root) == []  # target_words is derived from the source later


def test_improve_brief_rejects_bad_kind_and_mode(root):
    bad = {**BASE, "mode": "improve", "goal": "clarity", "source": {"kind": "notion", "ref": "x"}}
    assert blog.brief_errors(bad, root)
    assert blog.brief_errors({**BASE, "mode": "rewrite", "target_words": {"min": 1, "max": 2}}, root)


def test_min_greater_than_max_still_rejected(root):
    assert blog.brief_errors({**BASE, "target_words": {"min": 9, "max": 2}}, root) == ["target_words: min > max"]
