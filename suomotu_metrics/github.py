"""Minimal read-only GitHub REST client on the standard library.

The client talks to api.github.com and to nowhere else. The constructor
accepts a transport callable — (url, headers) -> (status, headers, body) —
so tests substitute recorded responses without touching the network.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
MAX_RATE_LIMIT_WAIT = 300  # seconds we are willing to sleep on a rate limit


class GitHubError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def default_transport(url, headers):
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()
    except urllib.error.URLError as error:
        raise GitHubError(f"network error reaching api.github.com: {error.reason}")


def parse_link_header(value):
    """Parse an RFC 5988 Link header into {rel: url}."""
    links = {}
    for part in (value or "").split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip().lstrip("<").rstrip(">")
        for segment in segments[1:]:
            segment = segment.strip()
            if segment.startswith('rel="') and segment.endswith('"'):
                links[segment[5:-1]] = url
    return links


class Client:
    def __init__(self, token=None, transport=None, sleep=time.sleep):
        self.token = token
        self.transport = transport or default_transport
        self.sleep = sleep

    def _headers(self):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "suomotu-metrics",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_url(self, url):
        """GET an absolute API URL. Returns (parsed_json, response_headers)."""
        status, headers, body = self.transport(url, self._headers())
        headers = {k.lower(): v for k, v in headers.items()}
        if status in (403, 429) and headers.get("x-ratelimit-remaining") == "0":
            reset = int(headers.get("x-ratelimit-reset", "0"))
            wait = max(0, reset - int(time.time())) + 1
            if wait <= MAX_RATE_LIMIT_WAIT:
                self.sleep(wait)
                status, headers, body = self.transport(url, self._headers())
                headers = {k.lower(): v for k, v in headers.items()}
            else:
                raise GitHubError(
                    f"GitHub rate limit reached; resets in {wait} seconds — rerun then",
                    status=status,
                )
        if status == 404:
            raise GitHubError(f"not found: {url}", status=404)
        if status == 401:
            raise GitHubError(
                "GitHub rejected the token (401) — check GITHUB_TOKEN", status=401
            )
        if status >= 400:
            raise GitHubError(f"GitHub returned {status} for {url}", status=status)
        return json.loads(body), headers

    def get(self, path, params=None):
        url = API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self.get_url(url)

    def paginate(self, path, params=None, items_key=None):
        """Yield items across pages, following Link rel="next" verbatim.

        Endpoints that wrap their list in an envelope (e.g. actions/runs)
        name the list field via items_key.
        """
        params = dict(params or {})
        params.setdefault("per_page", 100)
        url = API_ROOT + path + "?" + urllib.parse.urlencode(params)
        while url:
            payload, headers = self.get_url(url)
            yield from (payload[items_key] if items_key else payload)
            url = parse_link_header(headers.get("link")).get("next")

    def first_and_last_of(self, path, params=None):
        """For a newest-first listing: return (oldest_item, newest_item).

        Fetches page one; when a Link rel="last" exists, fetches that page for
        the oldest item — one extra request instead of walking the history.
        """
        params = dict(params or {})
        params.setdefault("per_page", 100)
        url = API_ROOT + path + "?" + urllib.parse.urlencode(params)
        page, headers = self.get_url(url)
        if not page:
            return None, None
        newest = page[0]
        last_url = parse_link_header(headers.get("link")).get("last")
        if last_url:
            page, _ = self.get_url(last_url)
        return page[-1], newest
