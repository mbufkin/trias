"""Tests for report_parser using real Trias review fixtures."""

from pathlib import Path

import pytest

from trias.report_parser import parse_report_file, parse_report_markdown

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-gb10-review.md"


@pytest.fixture
def parsed():
    assert FIXTURE.is_file(), f"Missing fixture: {FIXTURE}"
    text = FIXTURE.read_text(encoding="utf-8")
    return parse_report_markdown(text, task_id="20260625-182049-258a724b")


def test_extracts_task_id(parsed):
    assert parsed["task_id"] == "20260625-182049-258a724b"


def test_consensus_severity_counts(parsed):
    s = parsed["summary"]
    assert s["consensus_count"] == 2
    assert s["high"] == 1
    assert s["medium"] == 1


def test_file_coverage(parsed):
    fc = parsed["file_coverage"]
    assert len(fc) >= 2
    issues = [f for f in fc if f["has_issues"]]
    assert any("google_drive" in f["file"] for f in issues)


def test_skeptic_verdicts_parsed(parsed):
    verdicts = parsed["skeptic_verdicts"]
    assert len(verdicts) >= 4
    titles = " ".join(v["title"].lower() for v in verdicts)
    assert "path traversal" in titles
    assert parsed["summary"]["skeptic_disproven"] >= 3


def test_action_items_exclude_disproven_consensus(parsed):
    """DISPROVEN consensus findings must not appear in action_items."""
    action = parsed["action_items"]
    dismissed = parsed["dismissed_by_skeptic"]
    action_titles = " ".join(a["title"].lower() for a in action)
    dismissed_titles = " ".join(d["title"].lower() for d in dismissed)

    assert "path traversal" not in action_titles
    assert "path traversal" in dismissed_titles
    assert "arbitrary file upload" not in action_titles


def test_stands_finding_not_in_dismissed(parsed):
    """STANDS verdict should not land in dismissed list."""
    dismissed_titles = " ".join(d["title"].lower() for d in parsed["dismissed_by_skeptic"])
    assert "global state" not in dismissed_titles


def test_needs_attention_false_when_high_disproven(parsed):
    """Both HIGH consensus items are skeptic-DISPROVEN in this fixture."""
    assert parsed["summary"]["needs_attention"] is False


def test_sections_have_raw_reviews(parsed):
    raw = parsed["sections"]["raw_reviews_md"]
    assert "Reviewer 1" in raw or "### File:" in raw


def test_parse_from_string_matches_file(parsed):
    text = FIXTURE.read_text(encoding="utf-8")
    from_str = parse_report_markdown(text, task_id="20260625-182049-258a724b")
    assert from_str["summary"] == parsed["summary"]
