"""Audit orchestration: discovery, per-repository audits, scoring and report assembly.

A failing repository never stops the run. Its checks become UNKNOWN and the run is
marked PARTIAL. The run is FAILED only when nothing could be audited at all.
"""
from __future__ import annotations

import copy
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.auditors.environments import audit_environments, audit_organization_secrets
from src.auditors.security import audit_security
from src.auditors.workflows import audit_workflows
from src.discovery.repositories import discover_repositories, public_identifier
from src.health import scoring
from src.health.statuses import FAILED, UNKNOWN, WARNING, NON_COMPLIANT
from src.rulesets.engine import evaluate_repository, prepare_organization_scope
from src.utils.config import Settings
from src.utils.log import get_logger

log = get_logger(__name__)
SCHEMA_VERSION = 1


def _fallback(area: str, message: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": UNKNOWN, "error": message,
        "findings": [{"severity": UNKNOWN, "message": f"{area} audit: {message}"}],
    }
    if area == "ci":
        base.update(latest_conclusion=None, consecutive_failures=0, workflow_count=0,
                    invalid_files=[], failed_jobs=[], stale=False, tests_configured=False)
    elif area == "security":
        base.update(coverage="unknown", features={}, dependabot={"availability": "error", "open": None, "critical_or_high": 0},
                    code_scanning={"availability": "error", "open": None, "critical_or_high": 0},
                    actions={}, third_party_actions={"total": 0, "unpinned": 0}, limitations=[])
    elif area == "environment":
        base.update(environment_count=0, unprotected_production=0, limitations=[])
    elif area == "branch":
        base.update(action="none", reason=message, scope="repository", existing_rulesets=[], status_checks=[])
    return base


def _guarded(area: str, errors: list[str], fn, ) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # per-check isolation: recorded, never silent
        log.error("%s audit failed unexpectedly: %s", area, type(exc).__name__)
        errors.append(area)
        return _fallback(area, "audit failed unexpectedly")


def _branch_findings(branch: dict[str, Any]) -> list[dict[str, str]]:
    if branch["status"] == NON_COMPLIANT:
        return [{"severity": WARNING, "message": f"default branch not protected: {branch['reason']}"}]
    if branch["status"] == UNKNOWN:
        return [{"severity": UNKNOWN, "message": f"branch protection unknown: {branch['reason']}"}]
    return []


def _public_ci(ci: dict[str, Any], repo, redact: bool) -> dict[str, Any]:
    out = dict(ci)
    if repo.private and redact:
        out["failed_jobs"] = []
        out["latest_run_url"] = None
    return out


def audit_repository(client, settings: Settings, repo, scope: dict[str, Any], now: datetime):
    org = settings.organization
    redact = settings.redact_private_repositories
    errors: list[str] = []
    try:
        ci, docs = audit_workflows(client, org, repo, settings, now)
    except Exception as exc:
        log.error("ci audit failed unexpectedly: %s", type(exc).__name__)
        errors.append("ci")
        ci, docs = _fallback("ci", "audit failed unexpectedly"), []
    security = _guarded("security", errors, lambda: audit_security(client, org, repo, docs))
    environment = _guarded("environment", errors, lambda: audit_environments(client, org, repo.name))
    branch = _guarded("branch", errors, lambda: evaluate_repository(client, org, repo, settings, scope, "audit-only"))
    branch = dict(branch)
    branch["findings"] = _branch_findings(branch)

    overall, reasons = scoring.classify_repository(
        archived=repo.archived,
        ci_status=ci["status"],
        security_status=security["status"],
        branch_status=branch["status"],
        environment_status=environment["status"],
    )
    findings = []
    for area, block in (("CI/CD", ci), ("Security", security), ("Environment", environment), ("Branch protection", branch)):
        for finding in block.get("findings", []):
            findings.append({"area": area, "severity": finding["severity"], "message": finding["message"]})

    branch_public = {k: v for k, v in branch.items() if k not in ("existing_rulesets", "status_checks", "findings")}
    branch_public["existing_ruleset_count"] = len(branch.get("existing_rulesets", []))
    entry = {
        "name": public_identifier(repo, redact),
        "visibility": repo.visibility,
        "archived": repo.archived,
        "fork": repo.fork,
        "default_branch": repo.default_branch,
        "primary_language": repo.language,
        "url": None if (repo.private and redact) else repo.html_url,
        "overall": overall,
        "reasons": reasons,
        "ci": _public_ci(ci, repo, redact),
        "security": {k: v for k, v in security.items()},
        "environment": {k: v for k, v in environment.items()},
        "branch": branch_public,
        "findings": findings,
        "errors": errors,
    }
    limitations = list(security.get("limitations", [])) + list(environment.get("limitations", []))
    return entry, limitations


def run_audit(*, client, settings: Settings, mode: str, auth_mode: str,
              run_id: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    if mode not in ("audit-only", "dry-run"):
        raise ValueError("the audit accepts only audit-only or dry-run")
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)
    run_id = str(run_id or os.environ.get("GITHUB_RUN_ID") or f"local-{now:%Y%m%d%H%M%S}")
    org = settings.organization

    discovery = discover_repositories(client, org, settings)
    org_secrets = audit_organization_secrets(client, org)
    scope = prepare_organization_scope(client, org, settings, "audit-only")

    repos_out: list[dict[str, Any]] = []
    limitation_counts: Counter = Counter()
    for repo in discovery.repositories:
        entry, limitations = audit_repository(client, settings, repo, scope, now)
        repos_out.append(entry)
        limitation_counts.update(set(limitations))
    repos_out.sort(key=lambda r: r["name"].lower())

    stats = scoring.build_statistics(repos_out, repeated_threshold=settings.repeated_failure_threshold)
    completeness = stats["completeness"]["percent"]
    status = scoring.derive_audit_status(audited=len(repos_out), completeness_percent=completeness)

    api_limitations = [{"message": msg, "repositories": count} for msg, count in limitation_counts.most_common()]
    if org_secrets["availability"] != "available":
        api_limitations.append({"message": f"organization secret metadata {org_secrets['availability']}", "repositories": 0})
    repos_list = [r for r, _ in discovery.excluded]
    repos_all = discovery.repositories
    discovery_summary = {
        "total_discovered": discovery.total_seen,
        "audited": len(repos_all),
        "excluded": len(discovery.excluded),
        "archived": sum(1 for r in repos_all if r.archived),
        "forks": sum(1 for r in repos_all if r.fork),
        "private": sum(1 for r in repos_all if r.private),
        "public": sum(1 for r in repos_all if not r.private),
        "without_ci": stats["health"]["no_ci"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "organization": org,
        "control_repository": settings.control_repository,
        "audit": {
            "run_id": run_id,
            "timestamp": now.isoformat(timespec="seconds"),
            "status": status,
            "mode": mode,
            "auth_mode": auth_mode,
            "duration_seconds": round(time.monotonic() - started, 1),
            "completeness_percent": completeness,
            "api_requests": client.request_count,
        },
        "discovery": discovery_summary,
        "metrics": stats["health"],
        "ci_statistics": stats["ci"],
        "branch_protection": {**stats["branch"], "scope": scope["effective"], "scope_notes": scope["notes"]},
        "environment_statistics": {**stats["environment"], "organization_secrets": org_secrets},
        "security_statistics": stats["security"],
        "completeness": stats["completeness"],
        "repositories": repos_out,
        "latest_failures": scoring.build_latest_failures(repos_out),
        "recent_issues": scoring.build_recent_issues(repos_out, 15),
        "recommendations": scoring.build_recommendations(repos_out, stats),
        "api_limitations": api_limitations,
        "excluded_repositories": [
            {"name": public_identifier(r, settings.redact_private_repositories), "reason": reason}
            for r, reason in discovery.excluded
        ],
    }
