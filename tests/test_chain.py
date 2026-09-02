"""Chain detection: structural discovery, artifact timestamps, bare repos."""

from conftest import commit_payload

from suomotu_metrics import chain, db
from suomotu_metrics.github import Client


def seed_repo(con):
    db.upsert_repo(con, {"id": 1, "full_name": "acme/rocket", "default_branch": "main"})


def test_bare_repo_is_silent(con, transport):
    seed_repo(con)
    transport.add(
        "/repos/acme/rocket/contents/work", body={"message": "Not Found"}, status=404
    )
    count = chain.collect_chain(con, Client(transport=transport), 1, "acme/rocket")
    assert count == 0
    assert con.execute("SELECT COUNT(*) c FROM work_items").fetchone()["c"] == 0


def test_detects_work_items_and_timestamps(con, transport):
    seed_repo(con)
    transport.add(
        "/repos/acme/rocket/contents/work",
        body=[
            {"type": "dir", "name": "001-alpha"},
            {"type": "dir", "name": "notes"},  # wrong shape: skipped
            {"type": "file", "name": "002-file.md"},  # a file: skipped
        ],
    )
    for artifact, first, last in (
        ("intent.md", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"),
        ("spec.md", "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"),
    ):
        transport.add(
            "/repos/acme/rocket/commits",
            {"path": f"work/001-alpha/{artifact}", "per_page": 100},
            body=[commit_payload("n", last), commit_payload("o", first)],
        )
    # plan.md has no commits yet: an in-flight work item
    transport.add(
        "/repos/acme/rocket/commits",
        {"path": "work/001-alpha/plan.md", "per_page": 100},
        body=[],
    )

    count = chain.collect_chain(con, Client(transport=transport), 1, "acme/rocket")

    assert count == 1
    rows = con.execute(
        "SELECT artifact, first_commit_at, last_commit_at FROM artifact_commits "
        "ORDER BY artifact"
    ).fetchall()
    assert [(r["artifact"], r["first_commit_at"]) for r in rows] == [
        ("intent", "2026-08-01T00:00:00Z"),
        ("spec", "2026-08-02T00:00:00Z"),
    ]
    assert rows[1]["last_commit_at"] == "2026-08-03T00:00:00Z"
    assert db.get_state(con, 1, "chain_watermark") == "2026-08-03T00:00:00Z"


def test_quiet_chain_probe_skips_artifact_fetches(con, transport):
    """With a watermark and no new commits under work/, one probe suffices."""
    seed_repo(con)
    db.upsert_work_item(con, 1, "001-alpha")
    db.set_state(con, 1, "chain_watermark", "2026-08-03T00:00:00Z")
    transport.add(
        "/repos/acme/rocket/commits",
        {"path": "work", "since": "2026-08-03T00:00:00Z", "per_page": 1},
        body=[],
    )
    count = chain.collect_chain(con, Client(transport=transport), 1, "acme/rocket")
    assert count == 1
    assert transport.calls == [
        ("/repos/acme/rocket/commits",
         {"path": "work", "since": "2026-08-03T00:00:00Z", "per_page": "1"}),
    ]
