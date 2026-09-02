"""Hand-computed cases for each metric definition, edge cases included."""

from datetime import datetime, timezone

from conftest import pr_payload

from suomotu_metrics import db, metrics

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)  # Wednesday, 2026-W36


def seed_repo(con):
    db.upsert_repo(con, {"id": 1, "full_name": "acme/rocket", "default_branch": "main"})


def insert_pr(con, number, created, merged=None, sha=None, draft=False, head="feature"):
    db.upsert_pull_request(
        con,
        1,
        pr_payload(
            number,
            created,
            merged_at=merged,
            merge_commit_sha=sha,
            draft=draft,
            head_ref=head,
        ),
    )


def insert_review(con, pr, review_id, state, submitted):
    db.upsert_review(
        con, 1, pr, {"id": review_id, "state": state, "submitted_at": submitted}
    )


def seed_scenario(con):
    """Six PRs whose expected numbers are worked out by hand.

    PR1 merged, approved, commit before review        -> first-pass, lead 48h
    PR2 merged after changes requested                -> not first-pass, lead 12h
    PR3 merged with no reviews, CI failed on merge    -> first-pass, failure
    PR4 merged approved, later reverted               -> first-pass, failure
    PR5 open draft with no reviews                    -> excluded from both sets
    PR6 closed unmerged, reviewed                     -> counts for first-review time
    """
    seed_repo(con)
    insert_pr(con, 1, "2026-08-03T10:00:00Z", "2026-08-05T10:00:00Z", "m1")
    insert_review(con, 1, 11, "APPROVED", "2026-08-04T10:00:00Z")
    db.upsert_pr_commit(con, 1, 1, "c1", "2026-08-03T09:00:00Z")

    insert_pr(con, 2, "2026-08-10T00:00:00Z", "2026-08-10T12:00:00Z", "m2")
    insert_review(con, 2, 21, "CHANGES_REQUESTED", "2026-08-10T02:00:00Z")
    insert_review(con, 2, 22, "APPROVED", "2026-08-10T08:00:00Z")
    db.upsert_pr_commit(con, 2, 2, "c2", "2026-08-10T05:00:00Z")

    insert_pr(con, 3, "2026-08-11T00:00:00Z", "2026-08-12T00:00:00Z", "m3")
    db.upsert_pr_commit(con, 3, 3, "c3", "2026-08-11T01:00:00Z")
    db.upsert_ci_run(
        con,
        1,
        {
            "id": 31,
            "head_sha": "m3",
            "head_branch": "main",
            "conclusion": "failure",
            "created_at": "2026-08-12T00:10:00Z",
        },
    )

    insert_pr(con, 4, "2026-08-17T00:00:00Z", "2026-08-18T00:00:00Z", "m4")
    insert_review(con, 4, 41, "APPROVED", "2026-08-17T06:00:00Z")
    db.upsert_pr_commit(con, 4, 4, "c4", "2026-08-17T01:00:00Z")
    db.mark_reverted(con, 1, "m4", "2026-08-19T00:00:00Z")

    insert_pr(con, 5, "2026-08-20T00:00:00Z", draft=True)

    insert_pr(con, 6, "2026-08-01T00:00:00Z")
    insert_review(con, 6, 61, "APPROVED", "2026-08-01T04:00:00Z")


def test_summary_hand_computed(con):
    seed_scenario(con)
    summary = metrics.compute(con, 1, 12, NOW)["summary"]
    assert summary["merged"] == 4
    assert summary["first_pass_share"] == 0.75  # PR1, PR3, PR4 of 4
    assert summary["lead_time_h"] == 24.0  # median of 48, 12, 24, 24
    assert summary["change_failure_rate"] == 0.5  # PR3 (CI), PR4 (revert)
    assert summary["review_time_h"] == 18.0  # median of 24, 10, 18
    assert summary["review_sample"] == 3  # PR1, PR2, PR4 — PR3 merged unreviewed
    assert summary["time_to_first_review_h"] == 5.0  # median of 24, 2, 6, 4
    assert summary["reviewed"] == 4  # PR1, PR2, PR4, PR6 — draft PR5 excluded


def test_weekly_buckets(con):
    seed_scenario(con)
    weekly = {week["week"]: week for week in metrics.compute(con, 1, 12, NOW)["weeks"]}
    week_of = lambda d: metrics.iso_week(metrics.parse_ts(d))
    w1 = weekly[week_of("2026-08-05T10:00:00Z")]
    assert (w1["merged"], w1["first_pass_share"], w1["lead_time_h"]) == (1, 1.0, 48.0)
    w2 = weekly[week_of("2026-08-10T12:00:00Z")]
    assert w2["merged"] == 2
    assert w2["first_pass_share"] == 0.5
    assert w2["change_failure_rate"] == 0.5
    w3 = weekly[week_of("2026-08-18T00:00:00Z")]
    assert (w3["merged"], w3["change_failure_rate"]) == (1, 1.0)


def test_merges_outside_window_excluded(con):
    seed_repo(con)
    insert_pr(con, 1, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "old")
    summary = metrics.compute(con, 1, 12, NOW)["summary"]
    assert summary["merged"] == 0
    assert summary["first_pass_share"] is None
    assert summary["lead_time_h"] is None


def test_first_pass_rules():
    first = "2026-08-04T10:00:00Z"
    approved = [{"state": "APPROVED", "submitted_at": first}]
    changes = [{"state": "CHANGES_REQUESTED", "submitted_at": first}]
    assert metrics.is_first_pass([], [], None) is True  # no reviews at all
    assert metrics.is_first_pass(approved, ["2026-08-03T00:00:00Z"], first) is True
    assert metrics.is_first_pass(approved, ["2026-08-05T00:00:00Z"], first) is False
    assert metrics.is_first_pass(changes, [], first) is False


def test_post_merge_review_stays_out_of_review_time(con):
    """An approval left after the merge is not a review phase."""
    seed_repo(con)
    insert_pr(con, 1, "2026-08-11T00:00:00Z", "2026-08-12T00:00:00Z", "m1")
    insert_review(con, 1, 11, "APPROVED", "2026-08-13T06:00:00Z")  # after merge
    summary = metrics.compute(con, 1, 12, NOW)["summary"]
    assert summary["review_time_h"] is None
    assert summary["review_sample"] == 0


def test_linkage_requires_folder_boundaries(con):
    """A folder name that is a prefix of another folder links no wrong PRs."""
    seed_repo(con)
    db.upsert_work_item(con, 1, "003-metrics")
    db.upsert_work_item(con, 1, "003-metrics-tool")
    db.upsert_artifact_commits(
        con, 1, "003-metrics", "plan", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )
    insert_pr(
        con, 7, "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z", "m7",
        head="003-metrics-tool",
    )
    items = {item["folder"]: item for item in metrics.compute_chain(con, 1)}
    assert items["003-metrics"]["linked_prs"] == []
    assert items["003-metrics"]["plan_to_merge_h"] is None
    assert items["003-metrics-tool"]["linked_prs"] == [7]


def test_failure_needs_default_branch(con):
    """A CI failure on a feature branch does not fail the change."""
    seed_repo(con)
    insert_pr(con, 1, "2026-08-11T00:00:00Z", "2026-08-12T00:00:00Z", "m1")
    db.upsert_ci_run(
        con,
        1,
        {
            "id": 5,
            "head_sha": "m1",
            "head_branch": "feature",
            "conclusion": "failure",
            "created_at": "2026-08-11T00:10:00Z",
        },
    )
    summary = metrics.compute(con, 1, 12, NOW)["summary"]
    assert summary["change_failure_rate"] == 0.0


def test_chain_stage_timings_and_flags(con):
    seed_repo(con)
    db.upsert_work_item(con, 1, "001-alpha")
    db.upsert_artifact_commits(
        con, 1, "001-alpha", "intent", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )
    # spec last edit lands after the plan's first commit -> flagged
    db.upsert_artifact_commits(
        con, 1, "001-alpha", "spec", "2026-08-02T00:00:00Z", "2026-08-05T00:00:00Z"
    )
    db.upsert_artifact_commits(
        con, 1, "001-alpha", "plan", "2026-08-04T00:00:00Z", "2026-08-04T00:00:00Z"
    )
    insert_pr(
        con, 9, "2026-08-04T06:00:00Z", "2026-08-06T00:00:00Z", "m9", head="001-alpha-build"
    )
    items = metrics.compute_chain(con, 1)
    assert len(items) == 1
    item = items[0]
    assert item["intent_to_spec_h"] == 24.0
    assert item["spec_to_plan_h"] == 48.0
    assert item["plan_to_merge_h"] == 48.0
    assert item["linked_prs"] == [9]
    assert item["flags"] == ["spec edited after the plan existed"]


def test_chain_missing_plan_yields_none(con):
    seed_repo(con)
    db.upsert_work_item(con, 1, "002-beta")
    db.upsert_artifact_commits(
        con, 1, "002-beta", "intent", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )
    item = metrics.compute_chain(con, 1)[0]
    assert item["intent_to_spec_h"] is None
    assert item["plan_to_merge_h"] is None
    assert item["flags"] == []
