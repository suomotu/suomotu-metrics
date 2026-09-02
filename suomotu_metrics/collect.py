"""Tier-one collection: pull requests, reviews, commits, CI runs, reverts.

Collection is incremental: sync_state stores per-repo watermarks, and later
runs fetch from the watermark forward.
"""

import re

from . import chain, db

REVERT_PATTERN = re.compile(r"This reverts commit ([0-9a-f]{7,40})")


def collect_repo(con, client, full_name):
    """Collect one repo. Returns a plain-English summary dict."""
    repo, _ = client.get(f"/repos/{full_name}")
    repo_id = db.upsert_repo(con, repo)
    default_branch = repo["default_branch"]

    new_prs = _collect_pull_requests(con, client, repo_id, full_name)
    new_runs = _collect_ci_runs(con, client, repo_id, full_name)
    new_reverts = _collect_reverts(con, client, repo_id, full_name, default_branch)
    work_items = chain.collect_chain(con, client, repo_id, full_name)

    con.commit()
    return {
        "repo": full_name,
        "new_prs": new_prs,
        "new_runs": new_runs,
        "new_reverts": new_reverts,
        "work_items": work_items,
    }


def _collect_pull_requests(con, client, repo_id, full_name):
    watermark = db.get_state(con, repo_id, "prs_watermark")
    newest_seen = watermark
    count = 0
    for pr in client.paginate(
        f"/repos/{full_name}/pulls",
        {"state": "all", "sort": "updated", "direction": "desc"},
    ):
        if watermark and pr["updated_at"] <= watermark:
            break
        db.upsert_pull_request(con, repo_id, pr)
        number = pr["number"]
        for review in client.paginate(f"/repos/{full_name}/pulls/{number}/reviews"):
            db.upsert_review(con, repo_id, number, review)
        for commit in client.paginate(f"/repos/{full_name}/pulls/{number}/commits"):
            db.upsert_pr_commit(
                con, repo_id, number, commit["sha"], commit["commit"]["committer"]["date"]
            )
        if newest_seen is None or pr["updated_at"] > newest_seen:
            newest_seen = pr["updated_at"]
        count += 1
    if newest_seen:
        db.set_state(con, repo_id, "prs_watermark", newest_seen)
    return count


def _collect_ci_runs(con, client, repo_id, full_name):
    watermark = db.get_state(con, repo_id, "runs_watermark")
    params = {}
    if watermark:
        params["created"] = f">={watermark[:10]}"
    newest_seen = watermark
    count = 0
    for run in client.paginate(f"/repos/{full_name}/actions/runs", params):
        db.upsert_ci_run(con, repo_id, run)
        if newest_seen is None or run["created_at"] > newest_seen:
            newest_seen = run["created_at"]
        count += 1
    if newest_seen:
        db.set_state(con, repo_id, "runs_watermark", newest_seen)
    return count


def _collect_reverts(con, client, repo_id, full_name, default_branch):
    """Scan default-branch commit messages for reverts of merged PRs."""
    watermark = db.get_state(con, repo_id, "commits_watermark")
    params = {"sha": default_branch}
    if watermark:
        params["since"] = watermark
    newest_seen = watermark
    marked = 0
    for commit in client.paginate(f"/repos/{full_name}/commits", params):
        committed_at = commit["commit"]["committer"]["date"]
        if newest_seen is None or committed_at > newest_seen:
            newest_seen = committed_at
        for reverted_sha in REVERT_PATTERN.findall(commit["commit"]["message"]):
            marked += db.mark_reverted(con, repo_id, reverted_sha, committed_at)
    if newest_seen:
        db.set_state(con, repo_id, "commits_watermark", newest_seen)
    return marked
