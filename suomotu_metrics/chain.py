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
    """Detect work items and record artifact commit timestamps. Returns count."""
    try:
        entries, _ = client.get(f"/repos/{full_name}/contents/work")
    except GitHubError as error:
        if error.status == 404:
            return 0
        raise
    if not isinstance(entries, list):
        return 0
    count = 0
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
            db.upsert_artifact_commits(
                con,
                repo_id,
                folder,
                artifact.removesuffix(".md"),
                oldest["commit"]["committer"]["date"],
                newest["commit"]["committer"]["date"],
            )
        count += 1
    return count
