"""Metric computation: pure functions over collected facts.

Definitions are implemented here exactly as the spec states them; the report
layer prints them next to the numbers.
"""

from datetime import datetime, timedelta, timezone


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_week(ts):
    return ts.strftime("%G-W%V")


def hours_between(start, end):
    return (parse_ts(end) - parse_ts(start)).total_seconds() / 3600.0


def median(values):
    values = sorted(values)
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


def week_keys(now, weeks):
    """The trailing `weeks` ISO week keys, oldest first, ending at now's week."""
    monday = now.date() - timedelta(days=now.weekday())
    keys = []
    for offset in range(weeks - 1, -1, -1):
        day = monday - timedelta(weeks=offset)
        keys.append(datetime(day.year, day.month, day.day).strftime("%G-W%V"))
    return keys


def window_start(now, weeks):
    monday = now.date() - timedelta(days=now.weekday())
    start = monday - timedelta(weeks=weeks - 1)
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
    return prs, reviews, commits, failed_shas


def first_review_at(pr_reviews):
    times = [r["submitted_at"] for r in pr_reviews]
    return min(times) if times else None


def is_first_pass(pr, pr_reviews, pr_commit_times):
    if any(r["state"] == "CHANGES_REQUESTED" for r in pr_reviews):
        return False
    first = first_review_at(pr_reviews)
    if first is None:
        return True
    return not any(t > first for t in pr_commit_times)


def is_change_failure(pr, failed_shas):
    if pr["reverted_at"]:
        return True
    sha = pr["merge_commit_sha"]
    return bool(sha and sha in failed_shas)


def compute(con, repo_id, weeks, now):
    """Weekly values and a window summary for the five tier-one metrics."""
    prs, reviews, commits, failed_shas = _load_facts(con, repo_id)
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
        and first_review_at(reviews.get(pr["number"], [])) is not None
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
            is_first_pass(pr, reviews.get(pr["number"], []), commits.get(pr["number"], []))
            for pr in merged_prs
        ]
        failures = [is_change_failure(pr, failed_shas) for pr in merged_prs]
        review_spans = []
        for pr in merged_prs:
            first = first_review_at(reviews.get(pr["number"], []))
            if first:
                review_spans.append(hours_between(first, pr["merged_at"]))
        return {
            "merged": len(merged_prs),
            "review_sample": len(review_spans),
            "first_pass_share": (sum(first_pass) / len(first_pass)) if first_pass else None,
            "lead_time_h": median(
                [hours_between(pr["created_at"], pr["merged_at"]) for pr in merged_prs]
            ),
            "time_to_first_review_h": median(
                [
                    hours_between(
                        pr["created_at"], first_review_at(reviews.get(pr["number"], []))
                    )
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


def compute_chain(con, repo_id):
    """Per-work-item stage timings and out-of-order edit flags."""
    artifacts = {}
    for row in con.execute(
        "SELECT folder, artifact, first_commit_at, last_commit_at "
        "FROM artifact_commits WHERE repo_id = ?",
        (repo_id,),
    ):
        artifacts.setdefault(row["folder"], {})[row["artifact"]] = row
    merged_prs = con.execute(
        "SELECT number, head_ref, title, body, merged_at FROM pull_requests "
        "WHERE repo_id = ? AND merged_at IS NOT NULL",
        (repo_id,),
    ).fetchall()

    items = []
    for row in con.execute(
        "SELECT folder FROM work_items WHERE repo_id = ? ORDER BY folder", (repo_id,)
    ):
        folder = row["folder"]
        stages = artifacts.get(folder, {})
        intent, spec, plan = (stages.get(a) for a in ("intent", "spec", "plan"))

        def span(a, b):
            if a and b:
                return hours_between(a["first_commit_at"], b["first_commit_at"])
            return None

        linked = [
            pr
            for pr in merged_prs
            if folder in (pr["head_ref"] or "")
            or folder in (pr["title"] or "")
            or folder in (pr["body"] or "")
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
