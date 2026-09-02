"""Report rendering: sections, formatting, and the org's language rules."""

import re
from datetime import datetime, timezone

from test_metrics import seed_repo, seed_scenario

from suomotu_metrics import db, report

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

BANNED_WORDS = re.compile(r"\b(never|always|nothing|every)\b", re.IGNORECASE)


def test_report_carries_metrics_and_definitions(con):
    seed_scenario(con)
    content = report.render(con, 1, "acme/rocket", 12, NOW)
    assert "# Suomotu Metrics — acme/rocket" in content
    assert "| First-pass merge share | 75% | 4 merged PRs |" in content
    assert "| Change failure rate | 50% | 4 merged PRs |" in content
    assert "| Lead time (median) | 24.0h | 4 merged PRs |" in content
    assert "## Week by week" in content
    assert "## How these numbers are computed" in content
    assert "**First-pass merge share**" in content


def test_bare_repo_report_explains_the_second_tier(con):
    seed_scenario(con)
    content = report.render(con, 1, "acme/rocket", 12, NOW)
    assert "## Artifact chain" not in content
    assert "No artifact chain detected" in content


def test_chain_section_appears_with_work_items(con):
    seed_scenario(con)
    db.upsert_work_item(con, 1, "001-alpha")
    db.upsert_artifact_commits(
        con, 1, "001-alpha", "intent", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )
    db.upsert_artifact_commits(
        con, 1, "001-alpha", "spec", "2026-08-02T00:00:00Z", "2026-08-02T00:00:00Z"
    )
    content = report.render(con, 1, "acme/rocket", 12, NOW)
    assert "## Artifact chain" in content
    assert "| 001-alpha | 24.0h |" in content
    assert "No artifact chain detected" not in content


def test_report_respects_the_language_rules(con):
    seed_scenario(con)
    content = report.render(con, 1, "acme/rocket", 12, NOW)
    hits = BANNED_WORDS.findall(content)
    assert hits == []


def test_duration_formatting():
    assert report.format_hours(None) == "—"
    assert report.format_hours(0.5) == "30m"
    assert report.format_hours(24.0) == "24.0h"
    assert report.format_hours(72.0) == "3.0d"
    assert report.format_hours(-30.0) == "-30.0h"  # out-of-order chain span
    assert report.format_share(0.6667) == "67%"
    assert report.format_share(None) == "—"


def test_write_report_places_the_file(con, tmp_path):
    seed_repo(con)
    path = report.write_report(con, 1, "acme/rocket", 12, NOW, tmp_path)
    assert path == tmp_path / "acme-rocket" / "2026-W36.md"
    assert path.read_text(encoding="utf-8").startswith("# Suomotu Metrics")
