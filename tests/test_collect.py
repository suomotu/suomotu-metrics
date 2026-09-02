"""Collection against the fake transport: population, reverts, incrementality."""

import json
from pathlib import Path

from conftest import commit_payload, pr_payload, review_payload, run_payload

from suomotu_metrics import collect, db
from suomotu_metrics.github import Client

FIXTURES = Path(__file__).parent / "fixtures"
M4 = "a" * 40


def wire_repo(transport, prs=(), runs=(), branch_commits=(), work_status=404):
    transport.add(
        "/repos/acme/rocket",
        body={"id": 1, "full_name": "acme/rocket", "default_branch": "main"},
    )
    transport.add(
        "/repos/acme/rocket/pulls",
        {"state": "all", "sort": "updated", "direction": "desc", "per_page": 100},
        body=list(prs),
    )
    transport.add(
        "/repos/acme/rocket/actions/runs",
        {"per_page": 100},
        body={"total_count": len(runs), "workflow_runs": list(runs)},
    )
    transport.add(
        "/repos/acme/rocket/commits",
        {"sha": "main", "per_page": 100},
        body=list(branch_commits),
    )
    transport.add(
        "/repos/acme/rocket/contents/work",
        body={"message": "Not Found"},
        status=work_status,
    )


def test_collect_populates_facts(con, transport):
    pr = pr_payload(
        4,
        "2026-08-17T00:00:00Z",
        updated_at="2026-08-18T00:05:00Z",
        merged_at="2026-08-18T00:00:00Z",
        merge_commit_sha=M4,
    )
    wire_repo(
        transport,
        prs=[pr],
        runs=[run_payload(31, M4, "main", "success", "2026-08-18T00:10:00Z")],
        branch_commits=[
            commit_payload(
                "r1",
                "2026-08-19T00:00:00Z",
                message=f'Revert "a change"\n\nThis reverts commit {M4}.',
            )
        ],
    )
    transport.add(
        "/repos/acme/rocket/pulls/4/reviews",
        {"per_page": 100},
        body=[review_payload(41, "APPROVED", "2026-08-17T06:00:00Z")],
    )
    transport.add(
        "/repos/acme/rocket/pulls/4/commits",
        {"per_page": 100},
        body=[commit_payload("c4", "2026-08-17T01:00:00Z")],
    )

    summary = collect.collect_repo(con, Client(transport=transport), "acme/rocket")

    assert summary == {
        "repo": "acme/rocket",
        "new_prs": 1,
        "new_runs": 1,
        "new_reverts": 1,
        "work_items": 0,
    }
    row = con.execute("SELECT * FROM pull_requests WHERE number = 4").fetchone()
    assert row["merged_at"] == "2026-08-18T00:00:00Z"
    assert row["reverted_at"] == "2026-08-19T00:00:00Z"
    assert con.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"] == 1
    assert con.execute("SELECT COUNT(*) c FROM pr_commits").fetchone()["c"] == 1
    assert con.execute("SELECT COUNT(*) c FROM ci_runs").fetchone()["c"] == 1
    assert db.get_state(con, 1, "prs_watermark") == "2026-08-18T00:05:00Z"


def test_second_run_fetches_from_watermark(con, transport):
    stale = pr_payload(3, "2026-08-01T00:00:00Z", updated_at="2026-08-10T00:00:00Z")
    boundary = pr_payload(4, "2026-08-17T00:00:00Z", updated_at="2026-08-18T00:05:00Z")
    wire_repo(transport, prs=[boundary, stale])
    transport.add("/repos/acme/rocket/pulls/4/reviews", {"per_page": 100}, body=[])
    transport.add("/repos/acme/rocket/pulls/4/commits", {"per_page": 100}, body=[])
    transport.add("/repos/acme/rocket/pulls/3/reviews", {"per_page": 100}, body=[])
    transport.add("/repos/acme/rocket/pulls/3/commits", {"per_page": 100}, body=[])
    client = Client(transport=transport)

    first = collect.collect_repo(con, client, "acme/rocket")
    assert first["new_prs"] == 2

    # No runs or branch commits were seen, so those watermarks stay unset and
    # the second pass reuses the same plain routes.
    assert db.get_state(con, 1, "runs_watermark") is None
    assert db.get_state(con, 1, "commits_watermark") is None

    # The watermark comparison is strict, so the boundary PR (updated exactly
    # at the watermark) is rechecked — catching a review submitted in that
    # same second — while older PRs stay untouched.
    second = collect.collect_repo(con, client, "acme/rocket")
    assert second["new_prs"] == 1

    boundary_fetches = [c for c in transport.calls if c[0].endswith("/pulls/4/reviews")]
    stale_fetches = [c for c in transport.calls if c[0].endswith("/pulls/3/reviews")]
    assert len(boundary_fetches) == 2
    assert len(stale_fetches) == 1


def test_first_run_bounded_by_cutoff(con, transport):
    recent = pr_payload(2, "2026-08-17T00:00:00Z", updated_at="2026-08-18T00:00:00Z")
    ancient = pr_payload(1, "2020-01-01T00:00:00Z", updated_at="2020-01-02T00:00:00Z")
    wire_repo(transport, prs=[recent, ancient])
    transport.add("/repos/acme/rocket/pulls/2/reviews", {"per_page": 100}, body=[])
    transport.add("/repos/acme/rocket/pulls/2/commits", {"per_page": 100}, body=[])
    # With a cutoff, first-run CI and commit fetches are window-bounded too.
    transport.add(
        "/repos/acme/rocket/actions/runs",
        {"per_page": 100, "created": ">=2026-06-15"},
        body={"total_count": 0, "workflow_runs": []},
    )
    transport.add(
        "/repos/acme/rocket/commits",
        {"sha": "main", "since": "2026-06-15T00:00:00Z", "per_page": 100},
        body=[],
    )

    summary = collect.collect_repo(
        con, Client(transport=transport), "acme/rocket", cutoff="2026-06-15T00:00:00Z"
    )
    assert summary["new_prs"] == 1  # the ancient PR stopped the walk
    ancient_fetches = [c for c in transport.calls if "/pulls/1/" in c[0]]
    assert ancient_fetches == []


def test_pending_ci_run_gets_its_conclusion(con, transport):
    wire_repo(
        transport,
        runs=[run_payload(31, "m1", "main", None, "2026-08-18T00:10:00Z")],
    )
    client = Client(transport=transport)
    collect.collect_repo(con, client, "acme/rocket")
    row = con.execute("SELECT conclusion FROM ci_runs WHERE run_id = 31").fetchone()
    assert row["conclusion"] is None

    # Next pass refetches the pending run individually before paginating.
    transport.add(
        "/repos/acme/rocket/actions/runs/31",
        body=run_payload(31, "m1", "main", "failure", "2026-08-18T00:10:00Z"),
    )
    transport.add(
        "/repos/acme/rocket/actions/runs",
        {"per_page": 100, "created": ">=2026-08-18"},
        body={"total_count": 0, "workflow_runs": []},
    )
    collect.collect_repo(con, client, "acme/rocket")
    row = con.execute("SELECT conclusion FROM ci_runs WHERE run_id = 31").fetchone()
    assert row["conclusion"] == "failure"


def test_revert_pr_body_marks_target(con, transport):
    target = pr_payload(
        5,
        "2026-08-10T00:00:00Z",
        updated_at="2026-08-11T00:00:00Z",
        merged_at="2026-08-11T00:00:00Z",
        merge_commit_sha="b" * 40,
    )
    revert = pr_payload(
        6,
        "2026-08-12T00:00:00Z",
        updated_at="2026-08-13T00:00:00Z",
        merged_at="2026-08-13T00:00:00Z",
        merge_commit_sha="c" * 40,
        body="Reverts acme/rocket#5",
    )
    wire_repo(transport, prs=[revert, target])
    for number in (5, 6):
        transport.add(f"/repos/acme/rocket/pulls/{number}/reviews", {"per_page": 100}, body=[])
        transport.add(f"/repos/acme/rocket/pulls/{number}/commits", {"per_page": 100}, body=[])

    summary = collect.collect_repo(con, Client(transport=transport), "acme/rocket")
    assert summary["new_reverts"] == 1
    row = con.execute("SELECT reverted_at FROM pull_requests WHERE number = 5").fetchone()
    assert row["reverted_at"] == "2026-08-13T00:00:00Z"


def test_recorded_fixture_shapes_flow_through(con, transport):
    """The sanitized fixtures recorded from the live API parse end to end."""
    prs = json.loads((FIXTURES / "pulls_recorded.json").read_text())
    number = prs[0]["number"]
    wire_repo(
        transport,
        prs=prs,
        runs=json.loads((FIXTURES / "runs_recorded.json").read_text())["workflow_runs"],
    )
    transport.add(
        f"/repos/acme/rocket/pulls/{number}/reviews",
        {"per_page": 100},
        body=json.loads((FIXTURES / "reviews_recorded.json").read_text()),
    )
    transport.add(
        f"/repos/acme/rocket/pulls/{number}/commits",
        {"per_page": 100},
        body=json.loads((FIXTURES / "pr_commits_recorded.json").read_text()),
    )
    summary = collect.collect_repo(con, Client(transport=transport), "acme/rocket")
    assert summary["new_prs"] == 1
    assert con.execute("SELECT COUNT(*) c FROM pull_requests").fetchone()["c"] == 1
