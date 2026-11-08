import pytest

from src.github.client import GitHubAPIError, GitHubClient


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, links=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.links = links or {}
        self.content = b"x" if payload is not None else b""
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        return self.responses.pop(0)


def make_client(responses):
    sleeps = []
    session = FakeSession(responses)
    client = GitHubClient("token", base_url="https://api.test", session=session,
                          sleep=sleeps.append, max_retries=3, clock=lambda: 1000)
    return client, session, sleeps


def test_retries_server_error_then_succeeds():
    client, session, sleeps = make_client([FakeResponse(502), FakeResponse(200, {"ok": True})])
    assert client.get_json("/x") == {"ok": True}
    assert len(session.calls) == 2
    assert sleeps == [1]


def test_permission_error_is_not_retried():
    client, session, sleeps = make_client([FakeResponse(403, {"message": "Resource not accessible"})])
    with pytest.raises(GitHubAPIError) as exc:
        client.get_json("/x")
    assert exc.value.kind == "permission"
    assert len(session.calls) == 1
    assert sleeps == []


def test_rate_limit_waits_for_reset_then_retries():
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1030"}
    client, session, sleeps = make_client([FakeResponse(403, {}, headers), FakeResponse(200, {"ok": 1})])
    client.get_json("/x")
    assert sleeps == [30]
    assert len(session.calls) == 2


def test_paginate_follows_link_header():
    first = FakeResponse(200, [{"id": 1}], links={"next": {"url": "https://api.test/page2"}})
    second = FakeResponse(200, [{"id": 2}])
    client, session, _ = make_client([first, second])
    assert [item["id"] for item in client.paginate("/items")] == [1, 2]
    assert session.calls[1][1] == "https://api.test/page2"


def test_not_found_is_unavailable_not_retried():
    client, session, sleeps = make_client([FakeResponse(404, {"message": "Not Found"})])
    with pytest.raises(GitHubAPIError) as exc:
        client.get_json("/missing")
    assert exc.value.kind == "not_found"
    assert exc.value.is_unavailable
    assert len(session.calls) == 1
