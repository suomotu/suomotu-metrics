"""SQLite schema and access helpers.

The tables store facts as GitHub reports them (timestamps, states, SHAs).
Derived numbers live in the report layer, so a definition can be tuned in a
point release with history intact.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY,
    full_name TEXT UNIQUE NOT NULL,
    default_branch TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pull_requests (
    repo_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    title TEXT,
    body TEXT,
    head_ref TEXT,
    draft INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    merged_at TEXT,
    merge_commit_sha TEXT,
    reverted_at TEXT,
    PRIMARY KEY (repo_id, number)
);
CREATE TABLE IF NOT EXISTS reviews (
    repo_id INTEGER NOT NULL,
    pr_number INTEGER NOT NULL,
    review_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    submitted_at TEXT,
    PRIMARY KEY (repo_id, review_id)
);
CREATE TABLE IF NOT EXISTS pr_commits (
    repo_id INTEGER NOT NULL,
    pr_number INTEGER NOT NULL,
    sha TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    PRIMARY KEY (repo_id, pr_number, sha)
);
CREATE TABLE IF NOT EXISTS ci_runs (
    repo_id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    head_sha TEXT NOT NULL,
    head_branch TEXT,
    conclusion TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (repo_id, run_id)
);
CREATE TABLE IF NOT EXISTS work_items (
    repo_id INTEGER NOT NULL,
    folder TEXT NOT NULL,
    PRIMARY KEY (repo_id, folder)
);
CREATE TABLE IF NOT EXISTS artifact_commits (
    repo_id INTEGER NOT NULL,
    folder TEXT NOT NULL,
    artifact TEXT NOT NULL,
    first_commit_at TEXT NOT NULL,
    last_commit_at TEXT NOT NULL,
    PRIMARY KEY (repo_id, folder, artifact)
);
CREATE TABLE IF NOT EXISTS sync_state (
    repo_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (repo_id, key)
);
"""


def connect(path):
    if path != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_repo(con, repo):
    con.execute(
        "INSERT INTO repos (id, full_name, default_branch) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name, "
        "default_branch=excluded.default_branch",
        (repo["id"], repo["full_name"], repo["default_branch"]),
    )
    return repo["id"]


def upsert_pull_request(con, repo_id, pr):
    # ON CONFLICT updates only the GitHub-sourced columns, so locally derived
    # columns (reverted_at) survive re-collection by construction.
    con.execute(
        "INSERT INTO pull_requests "
        "(repo_id, number, title, body, head_ref, draft, state, created_at, "
        " updated_at, merged_at, merge_commit_sha) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repo_id, number) DO UPDATE SET "
        "title=excluded.title, body=excluded.body, head_ref=excluded.head_ref, "
        "draft=excluded.draft, state=excluded.state, "
        "created_at=excluded.created_at, updated_at=excluded.updated_at, "
        "merged_at=excluded.merged_at, merge_commit_sha=excluded.merge_commit_sha",
        (
            repo_id,
            pr["number"],
            pr.get("title"),
            pr.get("body"),
            (pr.get("head") or {}).get("ref"),
            1 if pr.get("draft") else 0,
            pr["state"],
            pr["created_at"],
            pr["updated_at"],
            pr.get("merged_at"),
            pr.get("merge_commit_sha"),
        ),
    )


def upsert_review(con, repo_id, pr_number, review):
    con.execute(
        "INSERT OR REPLACE INTO reviews "
        "(repo_id, pr_number, review_id, state, submitted_at) VALUES (?, ?, ?, ?, ?)",
        (repo_id, pr_number, review["id"], review["state"], review.get("submitted_at")),
    )


def upsert_pr_commit(con, repo_id, pr_number, sha, committed_at):
    con.execute(
        "INSERT OR REPLACE INTO pr_commits (repo_id, pr_number, sha, committed_at) "
        "VALUES (?, ?, ?, ?)",
        (repo_id, pr_number, sha, committed_at),
    )


def upsert_ci_run(con, repo_id, run):
    con.execute(
        "INSERT OR REPLACE INTO ci_runs "
        "(repo_id, run_id, head_sha, head_branch, conclusion, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            repo_id,
            run["id"],
            run["head_sha"],
            run.get("head_branch"),
            run.get("conclusion"),
            run["created_at"],
        ),
    )


def mark_reverted(con, repo_id, merge_commit_sha, reverted_at):
    """Prefix match, so abbreviated SHAs in revert messages still land."""
    cur = con.execute(
        "UPDATE pull_requests SET reverted_at = ? "
        "WHERE repo_id = ? AND merge_commit_sha LIKE ? || '%' "
        "AND reverted_at IS NULL",
        (reverted_at, repo_id, merge_commit_sha),
    )
    return cur.rowcount


def mark_reverted_by_number(con, repo_id, pr_number, reverted_at):
    cur = con.execute(
        "UPDATE pull_requests SET reverted_at = ? "
        "WHERE repo_id = ? AND number = ? AND merged_at IS NOT NULL "
        "AND reverted_at IS NULL",
        (reverted_at, repo_id, pr_number),
    )
    return cur.rowcount


def get_repo_id(con, full_name):
    row = con.execute(
        "SELECT id FROM repos WHERE full_name = ?", (full_name,)
    ).fetchone()
    return row["id"] if row else None


def upsert_work_item(con, repo_id, folder):
    con.execute(
        "INSERT OR IGNORE INTO work_items (repo_id, folder) VALUES (?, ?)",
        (repo_id, folder),
    )


def upsert_artifact_commits(con, repo_id, folder, artifact, first_at, last_at):
    con.execute(
        "INSERT OR REPLACE INTO artifact_commits "
        "(repo_id, folder, artifact, first_commit_at, last_commit_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (repo_id, folder, artifact, first_at, last_at),
    )


def get_state(con, repo_id, key):
    row = con.execute(
        "SELECT value FROM sync_state WHERE repo_id = ? AND key = ?", (repo_id, key)
    ).fetchone()
    return row["value"] if row else None


def set_state(con, repo_id, key, value):
    con.execute(
        "INSERT OR REPLACE INTO sync_state (repo_id, key, value) VALUES (?, ?, ?)",
        (repo_id, key, value),
    )
