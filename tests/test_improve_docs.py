from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
SKILL = (SRC / ".claude" / "skills" / "blog" / "SKILL.md").read_text()
WRITER = (SRC / ".claude" / "agents" / "blog-writer.md").read_text()
REVIEWER = (SRC / ".claude" / "agents" / "blog-reviewer.md").read_text()
ADAPTER = (SRC / "config" / "qed42_review_adapter.md").read_text()


def test_skill_covers_every_improve_command_and_action():
    for needle in ("$BLOG classify", "FETCH_GDOC", "read_doc_markdown", "submit-source", "submit-assessment",
                   '"kind": "assess"', "approve-failing", "--approved-by-human", "approvable", "no_changes",
                   "Improve intake", "--note"):
        assert needle in SKILL, needle


def test_skill_keeps_the_gate_rules():
    assert "never judge readiness yourself" in SKILL.lower()
    assert "Never publish anything" in SKILL
    # the override is the user's decision, asked with AskUserQuestion, never taken by the skill
    assert "AskUserQuestion" in SKILL.split("approve-failing")[0] or "AskUserQuestion" in SKILL.split("approve-failing")[1][:600]


def test_agents_and_adapter_know_the_improve_mode():
    assert "improve mode" in WRITER.lower() and "`changes`" in WRITER
    assert "assess" in REVIEWER.lower()
    assert "assess" in ADAPTER.lower()
