"""Command-line entry points used by GitHub Actions and by local runs.

    python -m src.cli audit --mode audit-only --output build
    python -m src.cli rulesets --mode dry-run --output build
    python -m src.cli discover --output build
    python -m src.cli validate --source build
    python -m src.cli publish --source build --target .
    python -m src.cli notify --source reports/organization-health.json --output build
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.audit_runner import run_audit
from src.discovery.repositories import discover_repositories, new_repository_names, public_identifier
from src.github.auth import AuthError, resolve_credentials
from src.github.client import GitHubAPIError, GitHubClient
from src.notify.notifier import run_notifications
from src.reporting.csv_generator import render_csv
from src.reporting.json_generator import render_json
from src.reporting.markdown_generator import render_markdown
from src.reporting.publisher import ArtifactValidationError, PublishError, publish, validate_artifacts
from src.reporting.svg_generator import render_svg
from src.rulesets.engine import run_rulesets
from src.utils.config import VALID_MODES, ConfigError, Settings, load_settings
from src.utils.log import configure_logging, get_logger
from src.utils.summary import write_step_summary
from src.utils.text import md_escape

log = get_logger("dcc.cli")
ENFORCE_CONFIRMATION = "ENFORCE"


def _client(settings: Settings):
    credentials = resolve_credentials(settings.organization, settings.api_base_url)
    client = GitHubClient(
        credentials.token,
        base_url=settings.api_base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    )
    return client, credentials.mode


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _audit_summary(audit: dict) -> str:
    m, d = audit["metrics"], audit["discovery"]
    return "\n".join([
        f"## Organization audit: {audit['audit']['status']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Discovered | {d['total_discovered']} |",
        f"| Audited | {d['audited']} |",
        f"| Healthy | {m['healthy']} |",
        f"| Warning | {m['warning']} |",
        f"| Failed | {m['failed']} |",
        f"| No CI/CD | {m['no_ci']} |",
        f"| Unknown | {m['unknown']} |",
        f"| Completeness | {audit['audit']['completeness_percent']}% |",
    ])


def cmd_audit(args, settings: Settings) -> int:
    mode = args.mode or (settings.default_mode if settings.default_mode != "enforce" else "audit-only")
    client, auth_mode = _client(settings)
    audit = run_audit(client=client, settings=settings, mode=mode, auth_mode=auth_mode)
    out = Path(args.output)
    _write(out / "assets" / "organization-health.svg", render_svg(audit, settings.dashboard_repository_limit))
    _write(out / "reports" / "organization-health.json", render_json(audit))
    _write(out / "reports" / "organization-health.md", render_markdown(audit))
    _write(out / "reports" / "organization-health.csv", render_csv(audit))
    write_step_summary(_audit_summary(audit))
    status = audit["audit"]["status"]
    log.info("audit complete status=%s repositories=%d", status, len(audit["repositories"]))
    return 1 if status == "FAILED" else 0


def cmd_rulesets(args, settings: Settings) -> int:
    confirmation = os.environ.get("DCC_CONFIRM_ENFORCE", "").strip()
    if args.mode == "enforce" and confirmation != ENFORCE_CONFIRMATION:
        log.error("enforce refused: the confirm box must contain ENFORCE (received %d characters)",
                  len(confirmation))
        return 2
    client, _ = _client(settings)
    discovery = discover_repositories(client, settings.organization, settings)
    report = run_rulesets(client, settings, discovery.repositories, args.mode)
    out = Path(args.output)
    _write(out / "rulesets-report.json", json.dumps(report, indent=2, sort_keys=True) + "\n")

    s = report["summary"]
    lines = [
        f"## Branch rulesets ({args.mode})",
        "",
        f"- Repositories visible to the token: {discovery.total_seen}",
        f"- Excluded by configuration: {len(discovery.excluded)}",
        f"- Evaluated: {s['evaluated']}, compliant: {s['compliant']}, non-compliant: {s['non_compliant']}",
        f"- Would create: {s['would_create']}, created: {s['created']}, errors: {s['errors']}",
        f"- Scope: {report['scope']['effective']} ({'; '.join(report['scope']['notes']) or 'no notes'})",
        "",
        "| Repository | Status | Action | Reason |",
        "|---|---|---|---|",
    ]
    for plan in report["repositories"]:
        lines.append(f"| {md_escape(plan['repository'])} | {plan['status']} | {plan['action']} | "
                     f"{md_escape(plan['reason'])} |")
        log.info("ruleset repo=%s status=%s action=%s reason=%s",
                 plan["repository"], plan["status"], plan["action"], plan["reason"])
    for repo, reason in discovery.excluded:
        name = public_identifier(repo, settings.redact_private_repositories)
        lines.append(f"| {md_escape(name)} | EXCLUDED | skip | {md_escape(reason)} |")
    write_step_summary("\n".join(lines))
    return 1 if s["errors"] else 0


def cmd_discover(args, settings: Settings) -> int:
    client, _ = _client(settings)
    discovery = discover_repositories(client, settings.organization, settings)
    names = [public_identifier(r, settings.redact_private_repositories) for r in discovery.repositories]
    baseline_path = Path("reports/organization-health.json")
    baseline = None
    if baseline_path.is_file():
        previous = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline = [r["name"] for r in previous.get("repositories", [])]
    new = new_repository_names(names, baseline) if baseline is not None else []
    result = {
        "organization": settings.organization,
        "discovered": discovery.total_seen,
        "audited": len(names),
        "excluded": len(discovery.excluded),
        "baseline_available": baseline is not None,
        "new_since_last_report": new,
    }
    _write(Path(args.output) / "discovery.json", json.dumps(result, indent=2) + "\n")
    write_step_summary("\n".join([
        "## Repository discovery", "",
        f"- Discovered: {result['discovered']}, audited: {result['audited']}, excluded: {result['excluded']}",
        f"- New since last report: {', '.join(new) if new else 'none'}"
        if baseline is not None else "- No baseline report yet; new-repository comparison skipped.",
    ]))
    return 0


def cmd_validate(args, settings: Settings) -> int:
    audit = validate_artifacts(Path(args.source))
    print(f"artifacts valid: status={audit['audit']['status']} repositories={len(audit['repositories'])}")
    return 0


def cmd_publish(args, settings: Settings) -> int:
    result = publish(Path(args.source), Path(args.target))
    print(json.dumps(result, indent=2))
    return 0


def cmd_notify(args, settings: Settings) -> int:
    source = Path(args.source)
    if not source.is_file():
        log.error("no audit report at %s; run the Organization Audit first", source)
        return 1
    audit = json.loads(source.read_text(encoding="utf-8"))
    client, _ = _client(settings)
    result = run_notifications(client, settings, audit, datetime.now(timezone.utc))
    _write(Path(args.output) / "notifications.json", json.dumps(result, indent=2, default=str) + "\n")
    flagged = result["flagged_repositories"]
    lines = [
        "## Daily notifications",
        "",
        f"- Audit data: status {result['audit_status']}, auth {result['audit_auth_mode']}, "
        f"from {result['audit_timestamp']}",
        f"- Flagged repositories: {len(flagged)}" + (f" ({', '.join(flagged)})" if flagged else ""),
    ]
    if result["discussion"]:
        lines.append(f"- Discussion: {result['discussion']['action']} {result['discussion']['url']}")
    else:
        lines.append("- Discussion: not posted")
    if result["project"]:
        lines.append(f"- Project #{result['project']['number']}: found")
    if result["issues"]:
        i = result["issues"]
        lines.append(f"- Issues: created {i['created']}, updated {i['updated']}, reopened {i['reopened']}, "
                     f"closed {i['closed']}, added to project {i['added_to_project']}, deferred {i['deferred']}")
    for err in result["errors"]:
        lines.append(f"- Error: {err}")
    write_step_summary("\n".join(lines))
    for err in result["errors"]:
        log.error(err)
    return 1 if result["errors"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dcc", description="DevOps-Control-Center")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="audit the organization and write reports")
    audit.add_argument("--mode", choices=["audit-only", "dry-run"], default=None)
    audit.add_argument("--output", default="build")
    rulesets = sub.add_parser("rulesets", help="plan or enforce branch rulesets")
    rulesets.add_argument("--mode", choices=list(VALID_MODES), default="dry-run")
    rulesets.add_argument("--output", default="build")
    discover = sub.add_parser("discover", help="discover repositories and report new ones")
    discover.add_argument("--output", default="build")
    validate = sub.add_parser("validate", help="validate generated artifacts")
    validate.add_argument("--source", default="build")
    publish_cmd = sub.add_parser("publish", help="validate and copy artifacts into the repository")
    publish_cmd.add_argument("--source", default="build")
    publish_cmd.add_argument("--target", default=".")
    notify = sub.add_parser("notify", help="post the daily discussion and sync code issues")
    notify.add_argument("--source", default="reports/organization-health.json")
    notify.add_argument("--output", default="build")
    return parser


HANDLERS = {
    "audit": cmd_audit, "rulesets": cmd_rulesets, "discover": cmd_discover,
    "validate": cmd_validate, "publish": cmd_publish, "notify": cmd_notify,
}


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
        return HANDLERS[args.command](args, settings)
    except (ConfigError, AuthError, GitHubAPIError, ArtifactValidationError, PublishError, ValueError) as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
