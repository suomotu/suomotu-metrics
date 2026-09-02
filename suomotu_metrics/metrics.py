"""Metric computation: pure functions over collected facts.

Definitions are implemented here exactly as the spec states them; the report
layer prints them next to the numbers.
"""

import statistics
from datetime import datetime, timedelta, timezone


def parse_ts(value):
    return datetime.fromisoformat(value)


def iso_week(ts):
    calendar = ts.isocalendar()
    return f"{calendar.year}-W{calendar.week:02d}"


def hours_between(start, end):
    return (parse_ts(end) - parse_ts(start)).total_seconds() / 3600.0


def median(values):
    return statistics.median(values) if values else None


def _window_monday(now):
    day = now.date() - timedelta(days=now.weekday())
    return day


def week_keys(now, weeks):
    """The trailing `weeks` ISO week keys, oldest first, ending at now's week."""
    monday = _window_monday(now)
    return [
        iso_week(monday - timedelta(weeks=offset))
        for offset in range(weeks - 1, -1, -1)
    ]


def window_start(now, weeks):
    start = _window_monday(now) - timedelta(weeks=weeks - 1)
    return datetime(start.year, start.month, start.day, tzinfo=timezone.utc)


def _load_facts(con, repo_id):
    prs = con.execute(
        "SELECT * FROM pull_requests WHERE repo_id = ?", (repo_id,)
    ).fetchall()
    reviews = {}
    for row in con.execute(
        "SELECT pr_number, state, submitted_at FROM reviews "
        "WHERE repo_id = ? AND submitted_at IS NOT NULL",
        (repo_id,),
    ):
        reviews.setdefault(row["pr_number"], []).append(row)
    commits = {}
    for row in con.execute(
        "SELECT pr_number, committed_at FROM pr_commits WHERE repo_id = ?", (repo_id,)
    ):
        commits.setdefault(row["pr_number"], []).append(row["committed_at"])
    failed_shas = {
        row["head_sha"]
        for row in con.execute(
            "SELECT c.head_sha FROM ci_runs c JOIN repos r ON r.id = c.repo_id "
            "WHERE c.repo_id = ? AND c.head_branch = r.default_branch "
            "AND c.conclusion = 'failure'",
            (repo_id,),
        )
    }
    first_review = {
        number: min(r["submitted_at"] for r in rows)
        for number, rows in reviews.items()
    }
    return prs, reviews, commits, failed_shas, first_review


def is_first_pass(pr_reviews, pr_commit_times, first_review_at):
    if any(r["state"] == "CHANGES_REQUESTED" for r in pr_reviews):
        return False
    if first_review_at is None:
        return True
    return not any(t > first_review_at for t in pr_commit_times)


def is_change_failure(pr, failed_shas):
    if pr["reverted_at"]:
        return True
    sha = pr["merge_commit_sha"]
    return bool(sha and sha in failed_shas)


def compute(con, repo_id, weeks, now):
    """Weekly values and a window summary for the five tier-one metrics."""
    prs, reviews, commits, failed_shas, first_review = _load_facts(con, repo_id)
    keys = week_keys(now, weeks)
    start = window_start(now, weeks)

    merged = [
        pr
        for pr in prs
        if pr["merged_at"] and parse_ts(pr["merged_at"]) >= start
    ]
    reviewed = [
        pr
        for pr in prs
        if not pr["draft"]
        and pr["number"] in first_review
        and parse_ts(pr["created_at"]) >= start
    ]

    def bucket(items, timestamp_of):
        buckets = {key: [] for key in keys}
        for item in items:
            key = iso_week(parse_ts(timestamp_of(item)))
            if key in buckets:
                buckets[key].append(item)
        return buckets

    merged_by_week = bucket(merged, lambda pr: pr["merged_at"])
    reviewed_by_week = bucket(reviewed, lambda pr: pr["created_at"])

    def stats(merged_prs, reviewed_prs):
        first_pass = [
            is_first_pass(
                reviews.get(pr["number"], []),
                commits.get(pr["number"], []),
                first_review.get(pr["number"]),
            )
            for pr in merged_prs
        ]
        failures = [is_change_failure(pr, failed_shas) for pr in merged_prs]
        # A review submitted after the merge (a post-merge approval) is not a
        # review phase; negative spans stay out of the median.
        review_spans = [
            span
            for pr in merged_prs
            if pr["number"] in first_review
            if (span := hours_between(first_review[pr["number"]], pr["merged_at"])) >= 0
        ]
        return {
            "merged": len(merged_prs),
            "review_sample": len(review_spans),
            "first_pass_share": (sum(first_pass) / len(first_pass)) if first_pass else None,
            "lead_time_h": median(
                [hours_between(pr["created_at"], pr["merged_at"]) for pr in merged_prs]
            ),
            "time_to_first_review_h": median(
                [
                    hours_between(pr["created_at"], first_review[pr["number"]])
                    for pr in reviewed_prs
                ]
            ),
            "reviewed": len(reviewed_prs),
            "review_time_h": median(review_spans),
            "change_failure_rate": (sum(failures) / len(failures)) if failures else None,
        }

    weekly = [
        {"week": key, **stats(merged_by_week[key], reviewed_by_week[key])}
        for key in keys
    ]
    summary = stats(merged, reviewed)
    return {"weeks": weekly, "summary": summary}


def _links_folder(text, folder, all_folders):
    """True when text names this folder rather than a longer sibling folder.

    Branch names may extend the folder name (001-alpha-build), so a plain
    substring match stands — except where the match is actually a longer
    known work-item folder (003-metrics must not claim 003-metrics-tool).
    """
    longer = [f for f in all_folders if f != folder and f.startswith(folder)]
    index = text.find(folder)
    while index != -1:
        if not any(text.startswith(f, index) for f in longer):
            return True
        index = text.find(folder, index + 1)
    return False


def compute_chain(con, repo_id):
    """Per-work-item stage timings and out-of-order edit flags."""
    artifacts = {}
    for row in con.execute(
        "SELECT folder, artifact, first_commit_at, last_commit_at "
        "FROM artifact_commits WHERE repo_id = ?",
        (repo_id,),
    ):
        artifacts.setdefault(row["folder"], {})[row["artifact"]] = row
    merged_prs = [
        (row, f"{row['head_ref'] or ''}\n{row['title'] or ''}\n{row['body'] or ''}")
        for row in con.execute(
            "SELECT number, head_ref, title, body, merged_at FROM pull_requests "
            "WHERE repo_id = ? AND merged_at IS NOT NULL",
            (repo_id,),
        )
    ]

    folders = [
        row["folder"]
        for row in con.execute(
            "SELECT folder FROM work_items WHERE repo_id = ? ORDER BY folder",
            (repo_id,),
        )
    ]
    items = []
    for folder in folders:
        stages = artifacts.get(folder, {})
        intent, spec, plan = (stages.get(a) for a in ("intent", "spec", "plan"))

        def span(a, b):
            if a and b:
                return hours_between(a["first_commit_at"], b["first_commit_at"])
            return None

        linked = [
            pr for pr, text in merged_prs if _links_folder(text, folder, folders)
        ]
        merge_at = min((pr["merged_at"] for pr in linked), default=None)

        flags = []
        if intent and spec and intent["last_commit_at"] > spec["first_commit_at"]:
            flags.append("intent edited after the spec existed")
        if spec and plan and spec["last_commit_at"] > plan["first_commit_at"]:
            flags.append("spec edited after the plan existed")

        items.append(
            {
                "folder": folder,
                "intent_to_spec_h": span(intent, spec),
                "spec_to_plan_h": span(spec, plan),
                "plan_to_merge_h": (
                    hours_between(plan["first_commit_at"], merge_at)
                    if plan and merge_at
                    else None
                ),
                "linked_prs": [pr["number"] for pr in linked],
                "flags": flags,
            }
        )
    return items
