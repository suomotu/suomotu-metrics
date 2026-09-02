"""Tier-two collection: artifact-chain detection.

A repo keeps a chain when it holds `work/NNN-slug/` folders containing
`intent.md`, `spec.md`, `plan.md`. Detection is structural; a repo without a
`work/` folder is simply a bare repo and this module stays silent.
"""

import re

from . import db
from .github import GitHubError

ARTIFACTS = ("intent.md", "spec.md", "plan.md")
WORK_ITEM_PATTERN = re.compile(r"^\d{3}-[A-Za-z0-9._-]+$")


def collect_chain(con, client, repo_id, full_name):
    """Detect work items and record artifact commit timestamps. Returns count.

    Incremental: one probe request asks whether anything under work/ changed
    since the last pass; when the answer is no, the per-artifact fetches are
    skipped and the stored rows stand.
    """
    watermark = db.get_state(con, repo_id, "chain_watermark")
    if watermark:
        probe, _ = client.get(
            f"/repos/{full_name}/commits",
            {"path": "work", "since": watermark, "per_page": 1},
        )
        if not probe:
            row = con.execute(
                "SELECT COUNT(*) AS c FROM work_items WHERE repo_id = ?", (repo_id,)
            ).fetchone()
            return row["c"]
    try:
        entries, _ = client.get(f"/repos/{full_name}/contents/work")
    except GitHubError as error:
        if error.status == 404:
            return 0
        raise
    if not isinstance(entries, list):
        return 0
    count = 0
    newest_seen = watermark
    for entry in entries:
        if entry.get("type") != "dir" or not WORK_ITEM_PATTERN.match(entry["name"]):
            continue
        folder = entry["name"]
        db.upsert_work_item(con, repo_id, folder)
        for artifact in ARTIFACTS:
            path = f"work/{folder}/{artifact}"
            oldest, newest = client.first_and_last_of(
                f"/repos/{full_name}/commits", {"path": path}
            )
            if oldest is None:
                continue
            last_at = newest["commit"]["committer"]["date"]
            db.upsert_artifact_commits(
                con,
                repo_id,
                folder,
                artifact.removesuffix(".md"),
                oldest["commit"]["committer"]["date"],
                last_at,
            )
            if newest_seen is None or last_at > newest_seen:
                newest_seen = last_at
        count += 1
    if newest_seen:
        db.set_state(con, repo_id, "chain_watermark", newest_seen)
    return count
