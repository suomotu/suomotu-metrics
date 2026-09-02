"""Tier-one collection: pull requests, reviews, commits, CI runs, reverts.

Collection is incremental: sync_state stores per-repo watermarks, and later
runs fetch from the watermark forward. A first run bounds itself to the
reporting window (the cutoff), so pointing the tool at a decade-old repo
collects weeks of history, not years. Progress commits per pull request, so
an interrupted run resumes instead of restarting.
"""

import re

from . import chain, db

REVERT_PATTERN = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
REVERT_PR_PATTERN = re.compile(r"Reverts \S+#(\d+)")


def collect_repo(con, client, full_name, cutoff=None):
    """Collect one repo. Returns a plain-English summary dict.

    cutoff is an ISO timestamp; history older than it is skipped when no
    watermark exists yet.
    """
    repo, _ = client.get(f"/repos/{full_name}")
    repo_id = db.upsert_repo(con, repo)
    default_branch = repo["default_branch"]

    new_prs = _collect_pull_requests(con, client, repo_id, full_name, cutoff)
    new_runs = _collect_ci_runs(con, client, repo_id, full_name, cutoff)
    new_reverts = _collect_reverts(
        con, client, repo_id, full_name, default_branch, cutoff
    )
    new_reverts += _collect_pr_reverts(con, repo_id)
    work_items = chain.collect_chain(con, client, repo_id, full_name)

    con.commit()
    return {
        "repo": full_name,
        "new_prs": new_prs,
        "new_runs": new_runs,
        "new_reverts": new_reverts,
        "work_items": work_items,
    }


def _collect_pull_requests(con, client, repo_id, full_name, cutoff):
    watermark = db.get_state(con, repo_id, "prs_watermark")
    newest_seen = watermark
    count = 0
    for pr in client.paginate(
        f"/repos/{full_name}/pulls",
        {"state": "all", "sort": "updated", "direction": "desc"},
    ):
        # Strict comparison: a PR sharing the watermark second is reprocessed,
        # so a review landing in that same second is picked up next run.
        if watermark and pr["updated_at"] < watermark:
            break
        if not watermark and cutoff and pr["updated_at"] < cutoff:
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
        con.commit()  # progress survives an interrupted run
    if newest_seen:
        db.set_state(con, repo_id, "prs_watermark", newest_seen)
    return count


def _collect_ci_runs(con, client, repo_id, full_name, cutoff):
    # Runs stored while still in progress get their conclusion on a later
    # pass: refetch each stored run with no conclusion yet.
    pending = con.execute(
        "SELECT run_id FROM ci_runs WHERE repo_id = ? AND conclusion IS NULL",
        (repo_id,),
    ).fetchall()
    for row in pending:
        run, _ = client.get(f"/repos/{full_name}/actions/runs/{row['run_id']}")
        db.upsert_ci_run(con, repo_id, run)

    watermark = db.get_state(con, repo_id, "runs_watermark")
    params = {}
    since = watermark or cutoff
    if since:
        params["created"] = f">={since[:10]}"
    newest_seen = watermark
    count = 0
    for run in client.paginate(
        f"/repos/{full_name}/actions/runs", params, items_key="workflow_runs"
    ):
        db.upsert_ci_run(con, repo_id, run)
        if newest_seen is None or run["created_at"] > newest_seen:
            newest_seen = run["created_at"]
        count += 1
    if newest_seen:
        db.set_state(con, repo_id, "runs_watermark", newest_seen)
    con.commit()
    return count


def _collect_reverts(con, client, repo_id, full_name, default_branch, cutoff):
    """Scan default-branch commit messages for reverts of merged PRs."""
    watermark = db.get_state(con, repo_id, "commits_watermark")
    params = {"sha": default_branch}
    since = watermark or cutoff
    if since:
        params["since"] = since
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


def _collect_pr_reverts(con, repo_id):
    """Second revert signal: a merged PR whose body says "Reverts owner/repo#N"
    (the text GitHub writes on its generated revert PRs) marks PR N reverted.
    """
    rows = con.execute(
        "SELECT number, body, merged_at FROM pull_requests "
        "WHERE repo_id = ? AND merged_at IS NOT NULL AND body LIKE '%Reverts %#%'",
        (repo_id,),
    ).fetchall()
    marked = 0
    for row in rows:
        for target in REVERT_PR_PATTERN.findall(row["body"] or ""):
            marked += db.mark_reverted_by_number(
                con, repo_id, int(target), row["merged_at"]
            )
    return marked
