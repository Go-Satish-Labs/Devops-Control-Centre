from datetime import datetime, timezone

from src.notify.notifier import ensure_daily_discussion, render_discussion_body, sync_issues
from tests.fakes import FakeClient, make_audit, repo_dict

ORG, CTRL = "Go-Satish-Labs", "DevOps-Control-Center"
ISSUES = f"/repos/{ORG}/{CTRL}/issues"
CFG = {"label": "dcc-audit", "statuses": ["FAILED"], "max_new_per_run": 25}
URL = "https://example.test/report"
NOW = datetime(2026, 11, 8, 7, tzinfo=timezone.utc)


def issue_posts(client):
    return [body for path, body in client.posts if path == ISSUES]


def test_creates_issue_only_for_failed_repositories():
    audit = make_audit([repo_dict(name="payments", overall="FAILED"),
                        repo_dict(name="web", overall="WARNING"),
                        repo_dict(name="core", overall="HEALTHY")])
    client = FakeClient(lists={ISSUES: []})
    summary = sync_issues(client, ORG, CTRL, audit, CFG, URL)
    assert len(issue_posts(client)) == 1
    assert issue_posts(client)[0]["title"] == "[DCC] payments needs attention"
    assert summary["created"] == 1


def test_closes_issue_when_repository_recovers():
    existing = {"title": "[DCC] payments needs attention", "number": 4, "state": "open", "body": ""}
    client = FakeClient(lists={ISSUES: [existing]})
    audit = make_audit([repo_dict(name="payments", overall="HEALTHY")])
    summary = sync_issues(client, ORG, CTRL, audit, CFG, URL)
    assert summary["closed"] == 1
    assert (f"{ISSUES}/4", {"state": "closed", "state_reason": "completed"}) in client.patches


def test_reopens_closed_issue_when_repository_fails_again():
    existing = {"title": "[DCC] payments needs attention", "number": 5, "state": "closed", "body": "old"}
    client = FakeClient(lists={ISSUES: [existing]})
    audit = make_audit([repo_dict(name="payments", overall="FAILED")])
    summary = sync_issues(client, ORG, CTRL, audit, CFG, URL)
    assert summary["reopened"] == 1
    assert client.patches[0][1]["state"] == "open"
    assert issue_posts(client) == []


def test_pull_requests_are_not_mistaken_for_issues():
    pull_request = {"title": "[DCC] payments needs attention", "number": 9,
                    "state": "open", "pull_request": {}}
    client = FakeClient(lists={ISSUES: [pull_request]})
    audit = make_audit([repo_dict(name="payments", overall="FAILED")])
    assert sync_issues(client, ORG, CTRL, audit, CFG, URL)["created"] == 1


def test_issue_creation_is_capped_per_run():
    audit = make_audit([repo_dict(name=f"r{i}", overall="FAILED") for i in range(5)])
    client = FakeClient(lists={ISSUES: []})
    summary = sync_issues(client, ORG, CTRL, audit, {**CFG, "max_new_per_run": 2}, URL)
    assert summary["created"] == 2
    assert summary["deferred"] == 3


def test_discussion_is_created_once_per_day():
    created = []

    def graphql(query, variables):
        if "discussionCategories" in query:
            return {"repository": {"id": "R1", "hasDiscussionsEnabled": True,
                                   "discussionCategories": {"nodes": [{"id": "C1", "name": "Audit Reports"}]}}}
        if "createDiscussion" in query:
            created.append(variables)
            return {"createDiscussion": {"discussion": {"id": "D9", "url": "https://x/d9"}}}
        if "discussions(" in query:
            return {"repository": {"discussions": {"nodes": []}}}
        raise AssertionError(query)

    client = FakeClient(graphql=graphql)
    result = ensure_daily_discussion(client, ORG, CTRL, "Audit Reports",
                                      "Daily organization health: 2026-11-08", "body")
    assert result["action"] == "created"
    assert len(created) == 1


def test_discussion_body_warns_when_audit_is_stale():
    audit = make_audit([repo_dict(name="payments", overall="FAILED")])
    body = render_discussion_body(audit, report_url=URL, now=NOW, stale_after_hours=0)
    assert "latest audit data is about 1 hours old" in body
