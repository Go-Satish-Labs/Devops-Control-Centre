"""Environment and secret metadata auditing. Only names and counts are read, never values."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from src.github.client import GitHubAPIError
from src.health.statuses import CONFIGURED, NOT_CONFIGURED, UNKNOWN, WARNING

PRODUCTION_PATTERN = re.compile(r"prod|live|release", re.IGNORECASE)


def _availability(exc: GitHubAPIError) -> str:
    if exc.kind == "permission":
        return "inaccessible"
    if exc.kind == "not_found":
        return "unsupported"
    return "error"


def analyze_environment(env: dict[str, Any]) -> dict[str, Any]:
    reviewers = 0
    wait_minutes = 0
    for rule in env.get("protection_rules") or []:
        if rule.get("type") == "required_reviewers":
            reviewers += len(rule.get("reviewers") or [])
        elif rule.get("type") == "wait_timer":
            wait_minutes = int(rule.get("wait_timer") or 0)
    policy = env.get("deployment_branch_policy") or {}
    branch_restricted = bool(policy.get("protected_branches") or policy.get("custom_branch_policies"))
    return {
        "name": env.get("name", ""),
        "protected": reviewers > 0 or branch_restricted or wait_minutes > 0,
        "required_reviewers": reviewers,
        "wait_timer_minutes": wait_minutes,
        "branch_restricted": branch_restricted,
        "secret_count": None,
    }


def audit_environments(client, org: str, repo_name: str) -> dict[str, Any]:
    base = f"/repos/{org}/{repo_name}"
    result: dict[str, Any] = {
        "status": UNKNOWN, "availability": "available", "error": None, "environment_count": 0,
        "protected_environments": 0, "unprotected_production": 0,
        "repository_secret_count": None, "environment_secret_count": None,
        "limitations": [], "findings": [],
    }
    try:
        environments = [
            analyze_environment(env)
            for env in client.paginate(f"{base}/environments", item_key="environments")
        ]
    except GitHubAPIError as exc:
        result["availability"] = _availability(exc)
        result["error"] = exc.kind
        result["findings"] = [{"severity": UNKNOWN, "message": f"environment metadata {result['availability']}"}]
        return result

    result["environment_count"] = len(environments)
    result["protected_environments"] = sum(1 for e in environments if e["protected"])
    unprotected_prod = [e for e in environments if PRODUCTION_PATTERN.search(e["name"]) and not e["protected"]]
    result["unprotected_production"] = len(unprotected_prod)

    env_secret_total = 0
    for env in environments:
        try:
            payload = client.get_json(
                f"{base}/environments/{quote(env['name'], safe='')}/secrets", params={"per_page": 1}
            )
            env_secret_total += int(payload.get("total_count", 0))
        except GitHubAPIError as exc:
            result["limitations"].append(f"environment secret metadata {_availability(exc)}")
    result["environment_secret_count"] = env_secret_total

    try:
        payload = client.get_json(f"{base}/actions/secrets", params={"per_page": 1})
        result["repository_secret_count"] = int(payload.get("total_count", 0))
    except GitHubAPIError as exc:
        result["limitations"].append(f"repository secret metadata {_availability(exc)}")

    if environments and unprotected_prod:
        result["status"] = WARNING
        result["findings"].append({
            "severity": WARNING,
            "message": f"{len(unprotected_prod)} production-like environment(s) lack reviewers, wait timers or branch restrictions",
        })
    elif environments:
        result["status"] = CONFIGURED
    else:
        result["status"] = NOT_CONFIGURED
    return result


def audit_organization_secrets(client, org: str) -> dict[str, Any]:
    try:
        payload = client.get_json(f"/orgs/{org}/actions/secrets", params={"per_page": 1})
        return {"availability": "available", "secret_count": int(payload.get("total_count", 0))}
    except GitHubAPIError as exc:
        return {"availability": _availability(exc), "secret_count": None}
