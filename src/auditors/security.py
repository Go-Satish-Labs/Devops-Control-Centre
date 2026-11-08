"""Repository security configuration auditing. Unsupported features are limitations, not failures."""
from __future__ import annotations

import re
from typing import Any, Iterator

from src.github.client import GitHubAPIError
from src.health.statuses import CRITICAL, OK, UNKNOWN, WARNING

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HIGH_SEVERITIES = frozenset({"critical", "high"})


def iter_uses(workflow_data: dict[str, Any]) -> Iterator[str]:
    for job in (workflow_data.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        if isinstance(job.get("uses"), str):
            yield job["uses"]
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                yield step["uses"]


def classify_action_reference(org: str, reference: str) -> tuple[str | None, bool]:
    """Returns (kind, pinned_to_sha). Kind is local, docker, first_party, third_party or None."""
    if reference.startswith("./"):
        return "local", True
    if reference.startswith("docker://"):
        return "docker", False
    if "@" not in reference:
        return None, False
    target, ref = reference.split("@", 1)
    owner = target.split("/", 1)[0].lower()
    kind = "first_party" if owner in {org.lower(), "actions", "github"} else "third_party"
    return kind, bool(SHA_PATTERN.match(ref))


def _feature_status(block: dict[str, Any], key: str) -> str:
    value = block.get(key)
    return value.get("status", "unknown") if isinstance(value, dict) else "unknown"


def _alert_summary(client, path: str, params: dict, severity_of) -> dict[str, Any]:
    try:
        alerts = list(client.paginate(path, params=params))
    except GitHubAPIError as exc:
        availability = {"not_found": "not_enabled", "permission": "inaccessible"}.get(exc.kind, "error")
        return {"availability": availability, "open": None, "critical_or_high": 0}
    high = sum(1 for alert in alerts if str(severity_of(alert) or "").lower() in HIGH_SEVERITIES)
    return {"availability": "available", "open": len(alerts), "critical_or_high": high}


def _dependabot_severity(alert: dict[str, Any]) -> str:
    return (alert.get("security_vulnerability") or {}).get("severity", "")


def _code_scanning_severity(alert: dict[str, Any]) -> str:
    rule = alert.get("rule") or {}
    return rule.get("security_severity_level") or ""


def audit_security(client, org: str, repo, workflow_docs: list[dict[str, Any]]) -> dict[str, Any]:
    base = f"/repos/{org}/{repo.name}"
    limitations: list[str] = []
    findings: list[dict[str, str]] = []
    features = {"secret_scanning": "unknown", "push_protection": "unknown", "dependabot_security_updates": "unknown"}

    details = None
    try:
        details = client.get_json(base)
    except GitHubAPIError as exc:
        limitations.append(f"repository details {exc.kind}")
    saa = details.get("security_and_analysis") if isinstance(details, dict) else None
    if isinstance(saa, dict):
        features = {
            "secret_scanning": _feature_status(saa, "secret_scanning"),
            "push_protection": _feature_status(saa, "secret_scanning_push_protection"),
            "dependabot_security_updates": _feature_status(saa, "dependabot_security_updates"),
        }
    else:
        limitations.append("security_and_analysis not visible to the token")

    dependabot = _alert_summary(client, f"{base}/dependabot/alerts", {"state": "open"}, _dependabot_severity)
    code_scanning = _alert_summary(client, f"{base}/code-scanning/alerts", {"state": "open"}, _code_scanning_severity)
    for label, block in (("Dependabot alerts", dependabot), ("Code scanning alerts", code_scanning)):
        if block["availability"] == "not_enabled":
            limitations.append(f"{label} not enabled or unsupported")
        elif block["availability"] != "available":
            limitations.append(f"{label} {block['availability']}")

    actions = {"default_workflow_permissions": None, "can_approve_pull_request_reviews": None}
    try:
        perms = client.get_json(f"{base}/actions/permissions/workflow")
        actions = {
            "default_workflow_permissions": perms.get("default_workflow_permissions"),
            "can_approve_pull_request_reviews": perms.get("can_approve_pull_request_reviews"),
        }
    except GitHubAPIError as exc:
        limitations.append(f"actions workflow permissions {exc.kind}")

    third_party_total = unpinned = 0
    for doc in workflow_docs:
        for reference in iter_uses(doc["data"]):
            kind, pinned = classify_action_reference(org, reference)
            if kind == "third_party":
                third_party_total += 1
                if not pinned:
                    unpinned += 1

    critical = dependabot["critical_or_high"] + code_scanning["critical_or_high"]
    if critical:
        findings.append({"severity": CRITICAL, "message": f"{critical} open critical or high security alert(s)"})
    for label, key in (("Secret scanning", "secret_scanning"), ("Push protection", "push_protection")):
        if features[key] == "disabled":
            if repo.private:
                limitations.append(f"{label} disabled (may require an Advanced Security license)")
            else:
                findings.append({"severity": WARNING, "message": f"{label} is disabled"})
    open_dependabot = dependabot["open"] or 0
    if open_dependabot:
        findings.append({"severity": WARNING, "message": f"{open_dependabot} open Dependabot alert(s)"})
    if actions["default_workflow_permissions"] == "write":
        findings.append({"severity": WARNING, "message": "default GITHUB_TOKEN permission is read/write"})
    if unpinned:
        findings.append({"severity": WARNING,
                         "message": f"{unpinned} third-party action reference(s) not pinned to a commit SHA"})

    visible = isinstance(saa, dict) or dependabot["availability"] == "available" \
        or code_scanning["availability"] == "available"
    if critical:
        status = CRITICAL
    elif findings:
        status = WARNING
    elif visible:
        status = OK
    else:
        status = UNKNOWN
    covered = features["secret_scanning"] == "enabled" and dependabot["availability"] == "available"
    coverage = "covered" if covered else ("partial" if visible else "unknown")

    return {
        "status": status,
        "coverage": coverage,
        "features": features,
        "dependabot": dependabot,
        "code_scanning": code_scanning,
        "actions": actions,
        "third_party_actions": {"total": third_party_total, "unpinned": unpinned},
        "limitations": limitations,
        "findings": findings,
    }
