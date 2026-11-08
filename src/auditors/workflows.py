"""GitHub Actions auditing: workflow definitions, executions and CI/CD classification."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import yaml

from src.github.client import GitHubAPIError
from src.health.statuses import FAILED, FAILURE_CONCLUSIONS, HEALTHY, NO_CI, NOT_APPLICABLE, UNKNOWN, WARNING, worst
from src.utils.log import get_logger

log = get_logger(__name__)

WORKFLOW_DIR = ".github/workflows"
IN_FLIGHT = frozenset({"in_progress", "queued", "waiting", "requested", "pending"})
TEST_HINTS = (
    "pytest", "npm test", "yarn test", "pnpm test", "go test", "mvn test", "gradle test",
    "cargo test", "jest", "vitest", "dotnet test", "rspec", "phpunit",
)
BUILD_HINTS = (
    "docker build", "npm run build", "mvn package", "gradle build", "go build",
    "cargo build", "dotnet build", "python -m build", "make build",
)
DEPLOY_HINTS = (
    "deploy", "kubectl apply", "helm upgrade", "terraform apply", "cdk deploy",
    "serverless deploy", "gh-pages",
)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_workflow(path: str, text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {"path": path, "valid": False, "data": None}
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        return {"path": path, "valid": False, "data": None}
    return {"path": path, "valid": True, "data": data}


def detect_capabilities(texts: list[str]) -> dict[str, bool]:
    blob = "\n".join(texts).lower()
    return {
        "tests_configured": any(hint in blob for hint in TEST_HINTS),
        "build_configured": any(hint in blob for hint in BUILD_HINTS),
        "deploy_configured": any(hint in blob for hint in DEPLOY_HINTS) or "environment:" in blob,
    }


def summarize_runs(runs: list[dict[str, Any]], stale_days: int, now: datetime) -> dict[str, Any]:
    conclusions = [run.get("conclusion") or run.get("status") or "unknown" for run in runs]
    consecutive = 0
    for conclusion in conclusions:
        if conclusion in FAILURE_CONCLUSIONS:
            consecutive += 1
        else:
            break
    latest = runs[0] if runs else {}
    latest_at = parse_time(latest.get("created_at") or latest.get("run_started_at"))
    stale = latest_at is not None and (now - latest_at).days >= stale_days
    return {
        "recent_runs": len(runs),
        "recent_failures": sum(1 for c in conclusions if c in FAILURE_CONCLUSIONS),
        "recent_cancellations": sum(1 for c in conclusions if c == "cancelled"),
        "consecutive_failures": consecutive,
        "latest_conclusion": conclusions[0] if conclusions else None,
        "latest_run_id": latest.get("id"),
        "latest_run_at": latest.get("created_at"),
        "latest_run_url": latest.get("html_url"),
        "stale": stale,
    }


def classify_ci(*, workflow_count: int, invalid_count: int, active_count: int,
                summary: dict[str, Any], capabilities: dict[str, bool],
                repeated_threshold: int) -> tuple[str, list[tuple[str, str]]]:
    """Pure classification. Returns (status, [(severity, message), ...])."""
    if workflow_count == 0:
        return NO_CI, []
    findings: list[tuple[str, str]] = []
    valid_count = workflow_count - invalid_count
    if invalid_count:
        findings.append((WARNING, f"{invalid_count} workflow file(s) are invalid YAML or define no jobs"))
    if valid_count == 0:
        findings.append((FAILED, "no valid workflow definitions"))
    elif active_count == 0:
        findings.append((WARNING, "all workflows are disabled"))
    else:
        if summary["recent_runs"] == 0:
            findings.append((WARNING, "no workflow executions recorded on the default branch"))
        else:
            latest = summary["latest_conclusion"]
            if latest in FAILURE_CONCLUSIONS:
                findings.append((FAILED, f"latest default-branch run concluded: {latest}"))
            elif latest == "cancelled":
                findings.append((WARNING, "latest default-branch run was cancelled"))
            elif latest in IN_FLIGHT:
                findings.append((WARNING, "latest run is still in progress"))
            elif latest != "success":
                findings.append((WARNING, f"latest default-branch run concluded: {latest}"))
            if summary["consecutive_failures"] >= repeated_threshold:
                findings.append((FAILED, f"{summary['consecutive_failures']} consecutive failed runs"))
            if summary["stale"]:
                findings.append((WARNING, "latest workflow execution is stale"))
    if not capabilities.get("tests_configured"):
        findings.append((WARNING, "no automated test step detected"))
    status = worst(sev for sev, _ in findings) if findings else HEALTHY
    return status, findings


def list_workflow_files(client, org: str, repo_name: str, ref: str) -> list[dict[str, Any]]:
    try:
        listing = client.get_json(f"/repos/{org}/{repo_name}/contents/{WORKFLOW_DIR}", params={"ref": ref})
    except GitHubAPIError as exc:
        if exc.status_code == 404:
            return []
        raise
    if not isinstance(listing, list):
        return []
    return [
        item for item in listing
        if item.get("type") == "file" and item.get("name", "").endswith((".yml", ".yaml"))
    ]


def fetch_file_text(client, org: str, repo_name: str, ref: str, path: str) -> str:
    payload = client.get_json(f"/repos/{org}/{repo_name}/contents/{path}", params={"ref": ref})
    raw = payload.get("content") or ""
    return base64.b64decode(raw).decode("utf-8", errors="replace")


def _failed_job_names(client, org: str, repo_name: str, run_id: int) -> list[str]:
    try:
        payload = client.get_json(
            f"/repos/{org}/{repo_name}/actions/runs/{run_id}/jobs", params={"filter": "latest", "per_page": 100}
        )
    except GitHubAPIError:
        return []
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    return [job.get("name", "unnamed job") for job in jobs if job.get("conclusion") in FAILURE_CONCLUSIONS][:20]


def audit_workflows(client, org: str, repo, settings, now: datetime | None = None):
    """Audit one repository's CI/CD. Returns (result, parsed_valid_workflow_docs)."""
    now = now or datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "status": UNKNOWN, "error": None, "workflow_count": 0, "invalid_files": [],
        "active_workflows": 0, "tests_configured": False, "build_configured": False,
        "deploy_configured": False, "recent_runs": 0, "recent_failures": 0,
        "recent_cancellations": 0, "consecutive_failures": 0, "latest_conclusion": None,
        "latest_run_at": None, "latest_run_url": None, "latest_run_id": None,
        "failed_jobs": [], "stale": False, "findings": [],
    }
    if not repo.default_branch:
        result["status"] = NOT_APPLICABLE
        return result, []

    ref = repo.default_branch
    docs: list[dict[str, Any]] = []
    try:
        files = list_workflow_files(client, org, repo.name, ref)
        texts = []
        for item in files:
            text = fetch_file_text(client, org, repo.name, ref, item["path"])
            texts.append(text)
            parsed = parse_workflow(item["path"], text)
            if parsed["valid"]:
                docs.append(parsed)
            else:
                result["invalid_files"].append(item["path"])
        result["workflow_count"] = len(files)
        result.update(detect_capabilities(texts))

        active = 0
        summary = summarize_runs([], settings.stale_workflow_days, now)
        if files:
            definitions = list(client.paginate(f"/repos/{org}/{repo.name}/actions/workflows", item_key="workflows"))
            active = sum(1 for wf in definitions if wf.get("state") == "active")
            payload = client.get_json(
                f"/repos/{org}/{repo.name}/actions/runs",
                params={"branch": ref, "per_page": settings.recent_runs_window},
            )
            runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
            summary = summarize_runs(runs, settings.stale_workflow_days, now)

        status, findings = classify_ci(
            workflow_count=len(files),
            invalid_count=len(result["invalid_files"]),
            active_count=active,
            summary=summary,
            capabilities={k: result[k] for k in ("tests_configured", "build_configured", "deploy_configured")},
            repeated_threshold=settings.repeated_failure_threshold,
        )
        result.update(summary)
        result["active_workflows"] = active
        if summary["latest_conclusion"] in FAILURE_CONCLUSIONS and summary["latest_run_id"]:
            result["failed_jobs"] = _failed_job_names(client, org, repo.name, summary["latest_run_id"])
        result["status"] = status
        result["findings"] = [{"severity": sev, "message": msg} for sev, msg in findings]
    except GitHubAPIError as exc:
        result["status"] = UNKNOWN
        result["error"] = f"{exc.kind}"
        result["findings"] = [{"severity": UNKNOWN, "message": f"CI/CD audit unavailable ({exc.kind})"}]
    return result, docs
