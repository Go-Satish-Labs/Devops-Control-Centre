"""Health classification and organization-wide statistics. Pure functions, no I/O."""
from __future__ import annotations

from collections import Counter
from typing import Any

from src.health.statuses import (
    COMPLIANT, CONCLUDED, CONFIGURED, CRITICAL, FAILED, FAILURE_CONCLUSIONS, HEALTHY, NO_CI,
    NON_COMPLIANT, NOT_APPLICABLE, NOT_CONFIGURED, UNKNOWN, WARNING,
)

CHECK_AREAS = ("ci", "security", "branch", "environment")
SEVERITY_ORDER = {CRITICAL: 0, FAILED: 0, UNKNOWN: 1, WARNING: 2}
OVERALL_ORDER = {FAILED: 0, UNKNOWN: 1, WARNING: 2, NO_CI: 3, HEALTHY: 4, NOT_APPLICABLE: 5}


def percentage(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def classify_repository(*, archived: bool, ci_status: str, security_status: str,
                        branch_status: str, environment_status: str) -> tuple[str, list[str]]:
    if archived:
        return NOT_APPLICABLE, ["archived repository"]
    if ci_status == NOT_APPLICABLE:
        return NOT_APPLICABLE, ["empty repository"]
    if ci_status == NO_CI:
        return NO_CI, ["no CI/CD workflows"]
    failures = []
    if ci_status == FAILED:
        failures.append("CI/CD failing")
    if security_status == CRITICAL:
        failures.append("critical or high security alerts")
    if failures:
        return FAILED, failures
    unknown = [label for label, status in (
        ("CI/CD", ci_status), ("security", security_status),
        ("branch protection", branch_status), ("environment", environment_status),
    ) if status == UNKNOWN]
    if unknown:
        return UNKNOWN, [f"incomplete data for {', '.join(unknown)}"]
    warnings = []
    if ci_status == WARNING:
        warnings.append("CI/CD warnings")
    if security_status == WARNING:
        warnings.append("security warnings")
    if branch_status == NON_COMPLIANT:
        warnings.append("default branch not protected")
    if environment_status == WARNING:
        warnings.append("unprotected production environment")
    if warnings:
        return WARNING, warnings
    return HEALTHY, []


def build_statistics(repos: list[dict[str, Any]], repeated_threshold: int = 2) -> dict[str, Any]:
    applicable = [r for r in repos if r["overall"] != NOT_APPLICABLE]
    counts = Counter(r["overall"] for r in repos)
    health = {
        "audited": len(repos),
        "applicable": len(applicable),
        "healthy": counts.get(HEALTHY, 0),
        "warning": counts.get(WARNING, 0),
        "failed": counts.get(FAILED, 0),
        "no_ci": counts.get(NO_CI, 0),
        "unknown": counts.get(UNKNOWN, 0),
        "not_applicable": counts.get(NOT_APPLICABLE, 0),
        "health_percent": percentage(counts.get(HEALTHY, 0), len(applicable)),
    }

    ci_eval = [r for r in repos if r["ci"].get("latest_conclusion") in CONCLUDED]
    ci_success = sum(1 for r in ci_eval if r["ci"]["latest_conclusion"] == "success")
    ci = {
        "evaluated": len(ci_eval),
        "latest_success": ci_success,
        "latest_failed": sum(1 for r in repos if r["ci"]["status"] == FAILED
                             and r["ci"].get("latest_conclusion") in FAILURE_CONCLUSIONS),
        "success_percent": percentage(ci_success, len(ci_eval)),
        "repeated_failures": sum(1 for r in repos if r["ci"].get("consecutive_failures", 0) >= repeated_threshold),
    }

    branch_eval = [r for r in repos if r["branch"]["status"] in (COMPLIANT, NON_COMPLIANT)]
    branch_ok = sum(1 for r in branch_eval if r["branch"]["status"] == COMPLIANT)
    branch = {
        "evaluated": len(branch_eval),
        "compliant": branch_ok,
        "non_compliant": len(branch_eval) - branch_ok,
        "compliance_percent": percentage(branch_ok, len(branch_eval)),
    }

    open_dependabot = sum(((r["security"].get("dependabot") or {}).get("open") or 0) for r in repos)
    open_code = sum(((r["security"].get("code_scanning") or {}).get("open") or 0) for r in repos)
    sec_covered = sum(1 for r in applicable if r["security"].get("coverage") == "covered")
    security = {
        "covered": sec_covered,
        "coverage_percent": percentage(sec_covered, len(applicable)),
        "critical": sum(1 for r in repos if r["security"]["status"] == CRITICAL),
        "warning": sum(1 for r in repos if r["security"]["status"] == WARNING),
        "open_dependabot_alerts": open_dependabot,
        "open_code_scanning_alerts": open_code,
    }

    env_covered = sum(1 for r in applicable if r["environment"]["status"] != UNKNOWN)
    environment = {
        "configured": sum(1 for r in repos if r["environment"]["status"] == CONFIGURED),
        "not_configured": sum(1 for r in repos if r["environment"]["status"] == NOT_CONFIGURED),
        "warnings": sum(1 for r in repos if r["environment"]["status"] == WARNING),
        "coverage_percent": percentage(env_covered, len(applicable)),
    }

    total_checks = len(repos) * len(CHECK_AREAS)
    completed = sum(1 for r in repos for area in CHECK_AREAS if r[area]["status"] != UNKNOWN)
    completeness_pct = percentage(completed, total_checks)
    completeness = {
        "checks_total": total_checks,
        "checks_completed": completed,
        "percent": completeness_pct if completeness_pct is not None else 0.0,
    }
    return {"health": health, "ci": ci, "branch": branch, "security": security,
            "environment": environment, "completeness": completeness}


def derive_audit_status(*, audited: int, completeness_percent: float | None) -> str:
    if audited == 0:
        return "FAILED"
    if completeness_percent is None or completeness_percent < 100:
        return "PARTIAL"
    return "COMPLETE"


def build_recent_issues(repos: list[dict[str, Any]], limit: int = 15) -> list[dict[str, str]]:
    items = []
    for repo in repos:
        for finding in repo.get("findings", []):
            items.append({
                "repository": repo["name"],
                "area": finding["area"],
                "severity": finding["severity"],
                "message": finding["message"],
            })
    items.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 3), i["repository"].lower(), i["area"]))
    return items[:limit]


def build_latest_failures(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for repo in repos:
        ci = repo["ci"]
        if ci.get("latest_conclusion") in FAILURE_CONCLUSIONS:
            failures.append({
                "repository": repo["name"],
                "conclusion": ci["latest_conclusion"],
                "consecutive_failures": ci.get("consecutive_failures", 0),
                "failed_jobs": ci.get("failed_jobs", []),
                "run_url": ci.get("latest_run_url"),
                "run_at": ci.get("latest_run_at"),
            })
    return failures


def build_recommendations(repos: list[dict[str, Any]], stats: dict[str, Any]) -> list[dict[str, str]]:
    recs: list[dict[str, str]] = []
    if stats["security"]["critical"]:
        recs.append({"priority": "high", "message":
                     f"Resolve critical or high security alerts in {stats['security']['critical']} repository(ies) first."})
    if stats["ci"]["latest_failed"]:
        recs.append({"priority": "high", "message":
                     f"Investigate failing latest CI/CD runs in {stats['ci']['latest_failed']} repository(ies); see latest_failures."})
    if stats["ci"]["repeated_failures"]:
        recs.append({"priority": "medium", "message":
                     f"Stabilise {stats['ci']['repeated_failures']} repository(ies) with repeated consecutive failures."})
    if stats["health"]["no_ci"]:
        recs.append({"priority": "medium", "message":
                     f"Add CI/CD workflows to {stats['health']['no_ci']} repository(ies) without them."})
    if stats["branch"]["non_compliant"]:
        recs.append({"priority": "medium", "message":
                     f"Run the branch ruleset workflow in dry-run mode, review the plan, then enforce it for {stats['branch']['non_compliant']} repository(ies)."})
    if stats["environment"]["warnings"]:
        recs.append({"priority": "medium", "message":
                     f"Add reviewers, wait timers or branch restrictions to {stats['environment']['warnings']} repository(ies) with unprotected production environments."})
    if stats["completeness"]["percent"] < 100:
        recs.append({"priority": "medium", "message":
                     "Grant the audit token the missing read permissions to complete coverage; see api_limitations."})
    if stats["security"]["open_dependabot_alerts"]:
        recs.append({"priority": "low", "message":
                     f"Review {stats['security']['open_dependabot_alerts']} open Dependabot alert(s)."})
    order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: order[r["priority"]])
    return recs
