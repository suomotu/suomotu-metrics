import pytest

from suomotu_metrics.github import Client, GitHubError, parse_link_header


def test_get_returns_parsed_json(transport):
    transport.add("/repos/acme/rocket", body={"id": 1})
    client = Client(token="t", transport=transport)
    payload, _ = client.get("/repos/acme/rocket")
    assert payload == {"id": 1}


def test_auth_and_agent_headers_sent(transport):
    captured = {}

    def spy(url, headers):
        captured.update(headers)
        return transport(url, headers)

    transport.add("/repos/acme/rocket", body={})
    Client(token="secret", transport=spy).get("/repos/acme/rocket")
    assert captured["Authorization"] == "Bearer secret"
    assert captured["User-Agent"] == "suomotu-metrics"


def test_parse_link_header():
    value = (
        '<https://api.github.com/x?page=2>; rel="next", '
        '<https://api.github.com/x?page=9>; rel="last"'
    )
    links = parse_link_header(value)
    assert links["next"].endswith("page=2")
    assert links["last"].endswith("page=9")


def test_paginate_follows_next_links_verbatim(transport):
    transport.add(
        "/repos/a/b/things",
        {"per_page": 100},
        body=["one", "two"],
        link='<https://api.github.com/repositories/5/things?per_page=100&page=2>; rel="next"',
    )
    transport.add(
        "/repositories/5/things",
        {"per_page": 100, "page": 2},
        body=["three"],
    )
    client = Client(transport=transport)
    assert list(client.paginate("/repos/a/b/things")) == ["one", "two", "three"]


def test_paginate_unwraps_workflow_runs(transport):
    transport.add(
        "/repos/a/b/actions/runs",
        {"per_page": 100},
        body={"total_count": 1, "workflow_runs": [{"id": 7}]},
    )
    client = Client(transport=transport)
    assert list(client.paginate("/repos/a/b/actions/runs")) == [{"id": 7}]


def test_first_and_last_of_uses_last_page(transport):
    transport.add(
        "/repos/a/b/commits",
        {"path": "work/001-x/intent.md", "per_page": 100},
        body=[{"sha": "newest"}],
        link='<https://api.github.com/repositories/5/commits?path=p&per_page=100&page=3>; rel="last"',
    )
    transport.add(
        "/repositories/5/commits",
        {"path": "p", "per_page": 100, "page": 3},
        body=[{"sha": "older"}, {"sha": "oldest"}],
    )
    client = Client(transport=transport)
    oldest, newest = client.first_and_last_of(
        "/repos/a/b/commits", {"path": "work/001-x/intent.md"}
    )
    assert oldest["sha"] == "oldest"
    assert newest["sha"] == "newest"


def test_first_and_last_of_single_page(transport):
    transport.add(
        "/repos/a/b/commits",
        {"path": "p", "per_page": 100},
        body=[{"sha": "new"}, {"sha": "old"}],
    )
    oldest, newest = Client(transport=transport).first_and_last_of(
        "/repos/a/b/commits", {"path": "p"}
    )
    assert (oldest["sha"], newest["sha"]) == ("old", "new")


def test_404_raises_with_status(transport):
    transport.add("/repos/a/gone", body={"message": "Not Found"}, status=404)
    with pytest.raises(GitHubError) as exc:
        Client(transport=transport).get("/repos/a/gone")
    assert exc.value.status == 404


def test_rate_limit_sleeps_and_retries(transport):
    import time as time_module

    reset = int(time_module.time()) + 5
    transport.add_raw(
        "/repos/a/b",
        None,
        403,
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
        {"message": "rate limited"},
    )
    transport.add("/repos/a/b", body={"id": 1})
    naps = []
    client = Client(transport=transport, sleep=naps.append)
    payload, _ = client.get("/repos/a/b")
    assert payload == {"id": 1}
    assert len(naps) == 1 and naps[0] >= 1


def test_rate_limit_with_long_reset_raises(transport):
    import time as time_module

    reset = int(time_module.time()) + 7200
    transport.add_raw(
        "/repos/a/b",
        None,
        403,
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
        {"message": "rate limited"},
    )
    with pytest.raises(GitHubError, match="rate limit"):
        Client(transport=transport, sleep=lambda _: None).get("/repos/a/b")
