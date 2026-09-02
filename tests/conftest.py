"""Shared test harness: a fake transport and API-shaped payload builders.

No test touches the network; the fake transport feeds recorded or synthetic
responses to the client through the same interface the real transport uses.
"""

import json
import sqlite3
from urllib.parse import parse_qsl, urlparse

import pytest

from suomotu_metrics import db


class FakeTransport:
    """Routes (path, query) to canned responses; records each call."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    @staticmethod
    def _key(path, params):
        return (path, frozenset((k, str(v)) for k, v in (params or {}).items()))

    def add(self, path, params=None, body=None, link=None, status=200):
        headers = {"Link": link} if link else {}
        payload = json.dumps(body if body is not None else {}).encode()
        self.routes.setdefault(self._key(path, params), []).append(
            (status, headers, payload)
        )
        return self

    def add_raw(self, path, params, status, headers, body):
        self.routes.setdefault(self._key(path, params), []).append(
            (status, headers, json.dumps(body).encode())
        )
        return self

    def __call__(self, url, headers):
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query))
        self.calls.append((parsed.path, params))
        key = self._key(parsed.path, params)
        if key not in self.routes:
            raise AssertionError(f"unexpected request: {parsed.path} {params}")
        responses = self.routes[key]
        return responses.pop(0) if len(responses) > 1 else responses[0]


def pr_payload(
    number,
    created_at,
    updated_at=None,
    merged_at=None,
    merge_commit_sha=None,
    head_ref="feature",
    title="a change",
    body="",
    draft=False,
    state=None,
):
    return {
        "number": number,
        "title": title,
        "body": body,
        "head": {"ref": head_ref},
        "draft": draft,
        "state": state or ("closed" if merged_at else "open"),
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "merged_at": merged_at,
        "merge_commit_sha": merge_commit_sha,
    }


def review_payload(review_id, state, submitted_at):
    return {"id": review_id, "state": state, "submitted_at": submitted_at}


def commit_payload(sha, date, message="a commit"):
    return {"sha": sha, "commit": {"committer": {"date": date}, "message": message}}


def run_payload(run_id, head_sha, head_branch, conclusion, created_at):
    return {
        "id": run_id,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "conclusion": conclusion,
        "status": "completed",
        "event": "push",
        "created_at": created_at,
    }


@pytest.fixture
def con():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def transport():
    return FakeTransport()
