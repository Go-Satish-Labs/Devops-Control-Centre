from dataclasses import replace

from src.discovery.repositories import RepositoryInfo
from src.github.client import GitHubAPIError
from src.health.statuses import COMPLIANT, EXCLUDED, NON_COMPLIANT, NOT_APPLICABLE, UNKNOWN
from src.rulesets.engine import (build_ruleset_payload, evaluate_repository, prepare_organization_scope,
                                 ruleset_covers_branch, ruleset_name)
from src.utils.config import load_settings
from tests.fakes import FakeClient

ORG = "Go-Satish-Labs"
SCOPE = {"requested": "repository", "effective": "repository", "covers_all": False, "notes": []}
ACTIVE_DETAIL = {"enforcement": "active", "target": "branch",
                 "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
                 "rules": [{"type": "pull_request"}]}
CHECKS = {
    f"/repos/{ORG}/api/branches/main": {"commit": {"sha": "abc"}},
    f"/repos/{ORG}/api/commits/abc/check-runs": {"check_runs": [
        {"name": "test", "conclusion": "success", "app": {"slug": "github-actions"}}]},
}


def settings(**overrides):
    return replace(load_settings(), **overrides)


def repo(name="api", branch="main", archived=False):
    return RepositoryInfo(name=name, default_branch=branch, visibility="public", private=False,
                          archived=archived, fork=False, language="Python", html_url=None, pushed_at=None)


def test_payload_contains_required_rules():
    payload = build_ruleset_payload(settings(), status_checks=["test"])
    types = {rule["type"] for rule in payload["rules"]}
    assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= types
    assert payload["enforcement"] == "active"
    assert payload["name"] == ruleset_name(settings())


def test_organization_payload_applies_exclusions():
    payload = build_ruleset_payload(settings(), organization_scope=True,
                                    excluded_repositories=["DevOps-Control-Center"])
    assert payload["conditions"]["repository_name"]["include"] == ["~ALL"]
    assert payload["conditions"]["repository_name"]["exclude"] == ["DevOps-Control-Center"]


def test_coverage_detection():
    assert ruleset_covers_branch(ACTIVE_DETAIL, "main")
    assert not ruleset_covers_branch({**ACTIVE_DETAIL, "enforcement": "disabled"}, "main")
    assert not ruleset_covers_branch({**ACTIVE_DETAIL, "rules": []}, "main")


def test_dry_run_plans_without_writing():
    client = FakeClient(routes=CHECKS, lists={f"/repos/{ORG}/api/rulesets": []})
    result = evaluate_repository(client, ORG, repo(), settings(), SCOPE, "dry-run")
    assert result["status"] == NON_COMPLIANT
    assert result["action"] == "would_create"
    assert result["status_checks"] == ["test"]
    assert client.posts == []


def test_enforce_creates_exactly_once():
    client = FakeClient(routes=CHECKS, lists={f"/repos/{ORG}/api/rulesets": []})
    result = evaluate_repository(client, ORG, repo(), settings(), SCOPE, "enforce")
    assert result["action"] == "created"
    assert len(client.posts) == 1
    assert client.posts[0][0] == f"/repos/{ORG}/api/rulesets"


def test_existing_covering_ruleset_is_compliant_and_untouched():
    client = FakeClient(
        routes={**CHECKS, f"/repos/{ORG}/api/rulesets/7": ACTIVE_DETAIL},
        lists={f"/repos/{ORG}/api/rulesets": [{"id": 7, "name": "Custom policy"}]},
    )
    result = evaluate_repository(client, ORG, repo(), settings(), SCOPE, "enforce")
    assert result["status"] == COMPLIANT
    assert client.posts == []


def test_same_name_ruleset_is_never_duplicated():
    client = FakeClient(
        routes={**CHECKS, f"/repos/{ORG}/api/rulesets/8": {**ACTIVE_DETAIL, "enforcement": "disabled"}},
        lists={f"/repos/{ORG}/api/rulesets": [{"id": 8, "name": ruleset_name(settings())}]},
    )
    result = evaluate_repository(client, ORG, repo(), settings(), SCOPE, "enforce")
    assert result["action"] == "manual_review"
    assert client.posts == []


def test_excluded_repository_is_skipped():
    client = FakeClient()
    result = evaluate_repository(client, ORG, repo(), settings(excluded_repositories=frozenset({"api"})),
                                 SCOPE, "enforce")
    assert result["status"] == EXCLUDED
    assert client.posts == []


def test_archived_repository_is_not_applicable():
    result = evaluate_repository(FakeClient(), ORG, repo(archived=True), settings(), SCOPE, "enforce")
    assert result["status"] == NOT_APPLICABLE


def test_permission_error_on_rulesets_is_unknown_not_compliant():
    client = FakeClient(lists={f"/repos/{ORG}/api/rulesets": GitHubAPIError(403, "forbidden")})
    result = evaluate_repository(client, ORG, repo(), settings(), SCOPE, "enforce")
    assert result["status"] == UNKNOWN
    assert client.posts == []


def test_organization_scope_falls_back_when_not_enforcing():
    client = FakeClient()
    scope = prepare_organization_scope(client, ORG, settings(), "dry-run")
    assert scope["effective"] == "repository"
    assert client.posts == []
