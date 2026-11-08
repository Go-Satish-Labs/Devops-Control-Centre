from datetime import datetime, timezone

from dataclasses import replace

from src.audit_runner import run_audit
from src.health.statuses import NO_CI
from src.utils.config import load_settings
from tests.fakes import FakeClient

NOW = datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc)
ORG = "Go-Satish-Labs"


def settings():
    return replace(load_settings(), organization=ORG)


def test_no_visible_repositories_is_failed():
    client = FakeClient(lists={f"/orgs/{ORG}/repos": []})
    audit = run_audit(client=client, settings=settings(), mode="audit-only", auth_mode="test",
                      run_id="t1", now=NOW)
    assert audit["audit"]["status"] == "FAILED"
    assert audit["repositories"] == []


def test_inaccessible_checks_make_the_audit_partial_not_successful():
    repo_item = {"name": "api", "default_branch": "main", "private": False, "archived": False,
                 "fork": False, "language": "Python", "html_url": f"https://github.com/{ORG}/api"}
    client = FakeClient(lists={f"/orgs/{ORG}/repos": [repo_item]})
    audit = run_audit(client=client, settings=settings(), mode="audit-only", auth_mode="test",
                      run_id="t2", now=NOW)
    repo = audit["repositories"][0]
    assert repo["ci"]["status"] == NO_CI
    assert repo["environment"]["status"] == "UNKNOWN"
    assert audit["audit"]["status"] == "PARTIAL"
    assert audit["audit"]["completeness_percent"] < 100


def test_audit_never_accepts_enforce_mode():
    try:
        run_audit(client=FakeClient(), settings=settings(), mode="enforce", auth_mode="test", now=NOW)
    except ValueError:
        return
    raise AssertionError("enforce must not be accepted by the audit")
