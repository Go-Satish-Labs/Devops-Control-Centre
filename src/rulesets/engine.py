"""Branch ruleset planning. Writes happen only in enforce mode; existing rules are never modified."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.discovery.repositories import RepositoryInfo, public_identifier
from src.github.client import GitHubAPIError
from src.health.statuses import COMPLIANT, EXCLUDED, NON_COMPLIANT, NOT_APPLICABLE, UNKNOWN
from src.utils.config import VALID_MODES, Settings
from src.utils.log import get_logger

log = get_logger(__name__)
DEFAULT_RULESET_NAME = "DCC Default Branch Protection"


def ruleset_name(settings: Settings) -> str:
    return settings.ruleset.get("name", DEFAULT_RULESET_NAME)


def target_branches(settings: Settings) -> list[str]:
    return list(settings.ruleset.get("target_branches", ["main", "master"]))


def excluded_for_rulesets(settings: Settings) -> set[str]:
    return set(settings.excluded_for_rulesets) | set(settings.write_protected_repositories) \
        | set(settings.excluded_repositories)


def build_ruleset_payload(settings: Settings, *, status_checks=(), organization_scope=False,
                          excluded_repositories=()) -> dict[str, Any]:
    cfg = settings.ruleset
    conditions: dict[str, Any] = {
        "ref_name": {"include": [f"refs/heads/{b}" for b in target_branches(settings)], "exclude": []}
    }
    if organization_scope:
        conditions["repository_name"] = {
            "include": ["~ALL"], "exclude": sorted(excluded_repositories), "protected": False,
        }
    rules: list[dict[str, Any]] = []
    if cfg.get("block_branch_deletion", True):
        rules.append({"type": "deletion"})
    if cfg.get("block_force_pushes", True):
        rules.append({"type": "non_fast_forward"})
    if cfg.get("require_pull_request", True):
        rules.append({"type": "pull_request", "parameters": {
            "required_approving_review_count": int(cfg.get("required_approvals", 1)),
            "dismiss_stale_reviews_on_push": True,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": bool(cfg.get("require_conversation_resolution", True)),
        }})
    if cfg.get("copilot_code_review", False):
        rules.append({"type": "copilot_code_review", "parameters": {
            "review_on_push": True,
            "review_draft_pull_requests": False,
        }})
    if status_checks:
        rules.append({"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": False,
            "required_status_checks": [{"context": c} for c in status_checks],
        }})
    return {
        "name": ruleset_name(settings),
        "target": "branch",
        "enforcement": "active",
        "conditions": conditions,
        "rules": rules,
        "bypass_actors": [],
    }


def ruleset_covers_branch(detail: dict[str, Any], branch: str) -> bool:
    if detail.get("enforcement") != "active" or detail.get("target", "branch") != "branch":
        return False
    include = ((detail.get("conditions") or {}).get("ref_name") or {}).get("include", [])
    if not any(item in (f"refs/heads/{branch}", "~DEFAULT_BRANCH", "~ALL") for item in include):
        return False
    return any(rule.get("type") == "pull_request" for rule in detail.get("rules", []))


def detect_status_checks(client, org: str, repo_name: str, branch: str, limit: int = 5) -> list[str]:
    """Names of checks from GitHub Actions that succeeded on the default branch head."""
    try:
        ref = client.get_json(f"/repos/{org}/{repo_name}/branches/{branch}")
        sha = ref["commit"]["sha"]
        payload = client.get_json(f"/repos/{org}/{repo_name}/commits/{sha}/check-runs", params={"per_page": 100})
    except (GitHubAPIError, KeyError, TypeError):
        return []
    names: list[str] = []
    for run in payload.get("check_runs", []):
        if (run.get("app") or {}).get("slug") != "github-actions" or run.get("conclusion") != "success":
            continue
        name = run.get("name")
        if name and name not in names:
            names.append(name)
    return names[:limit]


def resolve_status_checks(client, org: str, repo: RepositoryInfo, settings: Settings) -> list[str]:
    configured = settings.ruleset.get("required_status_checks", "auto")
    if isinstance(configured, list):
        return [str(c) for c in configured]
    if str(configured).lower() == "auto":
        return detect_status_checks(client, org, repo.name, repo.default_branch or "")
    return []


def _result(status, action, reason, *, scope="repository", status_checks=None, existing=None):
    return {
        "status": status, "action": action, "reason": reason, "scope": scope,
        "status_checks": list(status_checks or []), "existing_rulesets": list(existing or []),
    }


def prepare_organization_scope(client, org: str, settings: Settings, mode: str) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "requested": settings.ruleset.get("scope", "repository"),
        "effective": "repository", "covers_all": False, "notes": [],
    }
    name = ruleset_name(settings)
    try:
        existing = list(client.paginate(f"/orgs/{org}/rulesets"))
    except GitHubAPIError as exc:
        scope["notes"].append(f"organization rulesets {exc.kind}; using repository-level rulesets")
        return scope
    if any(entry.get("name") == name for entry in existing):
        scope.update(effective="organization", covers_all=True)
        scope["notes"].append("organization ruleset already exists")
        return scope
    if scope["requested"] != "organization":
        return scope
    if mode != "enforce":
        scope["notes"].append("organization ruleset would be created in enforce mode")
        return scope
    payload = build_ruleset_payload(
        settings, organization_scope=True, excluded_repositories=excluded_for_rulesets(settings)
    )
    try:
        client.post_json(f"/orgs/{org}/rulesets", payload)
        scope.update(effective="organization", covers_all=True)
        scope["notes"].append("organization ruleset created")
    except GitHubAPIError as exc:
        scope["notes"].append(f"organization ruleset creation failed ({exc.kind}); using repository-level rulesets")
    return scope


def evaluate_repository(client, org: str, repo: RepositoryInfo, settings: Settings,
                        scope: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}")
    branches = target_branches(settings)
    if repo.name in excluded_for_rulesets(settings):
        return _result(EXCLUDED, "skip", "excluded or write-protected by configuration")
    if repo.archived:
        return _result(NOT_APPLICABLE, "skip", "archived repository")
    if not repo.default_branch:
        return _result(NOT_APPLICABLE, "skip", "empty repository")
    if repo.default_branch not in branches:
        return _result(NOT_APPLICABLE, "skip", f"default branch '{repo.default_branch}' is not a target branch")
    if scope.get("covers_all"):
        return _result(COMPLIANT, "none", "covered by organization ruleset", scope="organization")

    try:
        listing = list(client.paginate(f"/repos/{org}/{repo.name}/rulesets"))
    except GitHubAPIError as exc:
        return _result(UNKNOWN, "none", f"rulesets {exc.kind}")

    name = ruleset_name(settings)
    named = covered = unreadable = False
    existing_names: list[str] = []
    for entry in listing:
        if entry.get("name") == name:
            named = True
        try:
            detail = client.get_json(f"/repos/{org}/{repo.name}/rulesets/{entry['id']}")
        except GitHubAPIError:
            unreadable = True
            continue
        existing_names.append(entry.get("name", ""))
        if ruleset_covers_branch(detail, repo.default_branch):
            covered = True

    if covered:
        return _result(COMPLIANT, "none", "an active ruleset already covers the default branch", existing=existing_names)
    if unreadable:
        return _result(UNKNOWN, "none", "could not read existing ruleset details", existing=existing_names)
    if named:
        return _result(NON_COMPLIANT, "manual_review",
                       "a ruleset with this name exists but does not cover the default branch",
                       existing=existing_names)

    checks = resolve_status_checks(client, org, repo, settings)
    payload = build_ruleset_payload(settings, status_checks=checks)
    if mode != "enforce":
        return _result(NON_COMPLIANT, "would_create", "no covering ruleset found",
                       status_checks=checks, existing=existing_names)
    try:
        client.post_json(f"/repos/{org}/{repo.name}/rulesets", payload)
    except GitHubAPIError as exc:
        return _result(NON_COMPLIANT, "error", f"ruleset creation failed ({exc.kind})",
                       status_checks=checks, existing=existing_names)
    return _result(COMPLIANT, "created", "ruleset created", status_checks=checks, existing=existing_names)


def run_rulesets(client, settings: Settings, repositories: list[RepositoryInfo], mode: str) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}")
    scope = prepare_organization_scope(client, settings.organization, settings, mode)
    plans = []
    for repo in repositories:
        try:
            outcome = evaluate_repository(client, settings.organization, repo, settings, scope, mode)
        except GitHubAPIError as exc:
            outcome = _result(UNKNOWN, "none", f"audit error ({exc.kind})")
        plans.append({"repository": public_identifier(repo, settings.redact_private_repositories), **outcome})
    actions = Counter(p["action"] for p in plans)
    summary = {
        "evaluated": len(plans),
        "compliant": sum(1 for p in plans if p["status"] == COMPLIANT),
        "non_compliant": sum(1 for p in plans if p["status"] == NON_COMPLIANT),
        "unknown": sum(1 for p in plans if p["status"] == UNKNOWN),
        "excluded": sum(1 for p in plans if p["status"] == EXCLUDED),
        "created": actions["created"],
        "would_create": actions["would_create"],
        "errors": actions["error"],
    }
    return {
        "schema_version": 1,
        "organization": settings.organization,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": scope,
        "summary": summary,
        "repositories": plans,
    }
