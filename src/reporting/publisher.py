"""Artifact validation and safe publishing. Failed audits are never published."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from src.reporting.csv_generator import CSV_COLUMNS

ASSET_FILES = {
    "svg": Path("assets/organization-health.svg"),
    "json": Path("reports/organization-health.json"),
    "md": Path("reports/organization-health.md"),
    "csv": Path("reports/organization-health.csv"),
}
VOLATILE_AUDIT_KEYS = ("timestamp", "run_id", "duration_seconds", "api_requests")


class ArtifactValidationError(ValueError):
    pass


class PublishError(RuntimeError):
    pass


def validate_artifacts(source: Path) -> dict:
    source = Path(source)
    for rel in ASSET_FILES.values():
        if not (source / rel).is_file():
            raise ArtifactValidationError(f"missing artifact: {rel}")
    try:
        audit = json.loads((source / ASSET_FILES["json"]).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ArtifactValidationError(f"invalid JSON: {exc}") from exc
    for key in ("schema_version", "organization", "audit", "metrics", "repositories"):
        if key not in audit:
            raise ArtifactValidationError(f"JSON report missing key: {key}")
    if audit["audit"].get("status") not in ("COMPLETE", "PARTIAL", "FAILED"):
        raise ArtifactValidationError("JSON report has an invalid audit status")

    try:
        root = ET.parse(source / ASSET_FILES["svg"]).getroot()
    except ET.ParseError as exc:
        raise ArtifactValidationError(f"SVG is not well-formed XML: {exc}") from exc
    if not root.tag.endswith("svg") or root.find("{http://www.w3.org/2000/svg}title") is None:
        raise ArtifactValidationError("SVG root or title element is invalid")

    markdown = (source / ASSET_FILES["md"]).read_text(encoding="utf-8")
    if not markdown.startswith("# "):
        raise ArtifactValidationError("Markdown report has no top-level heading")

    with (source / ASSET_FILES["csv"]).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows or rows[0] != CSV_COLUMNS:
        raise ArtifactValidationError("CSV header does not match the expected columns")
    if len(rows) - 1 != len(audit["repositories"]):
        raise ArtifactValidationError("CSV row count does not match the repository count")
    return audit


def fingerprint(audit: dict) -> str:
    stable = copy.deepcopy(audit)
    for key in VOLATILE_AUDIT_KEYS:
        stable.get("audit", {}).pop(key, None)
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _history_name(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d-%H%M%S") + ".json"


def publish(source: Path, target: Path) -> dict:
    source, target = Path(source), Path(target)
    audit = validate_artifacts(source)
    if audit["audit"]["status"] == "FAILED":
        raise PublishError("refusing to publish a FAILED audit; the last successful artifacts are preserved")

    current = target / ASSET_FILES["json"]
    if current.is_file():
        try:
            previous = json.loads(current.read_text(encoding="utf-8"))
            if fingerprint(previous) == fingerprint(audit):
                return {"changed": False, "written": [], "reason": "content unchanged"}
        except (ValueError, KeyError):
            pass

    written = []
    for rel in ASSET_FILES.values():
        _write_atomic(target / rel, (source / rel).read_bytes())
        written.append(str(rel))
    history_rel = Path("reports/history") / _history_name(audit["audit"]["timestamp"])
    _write_atomic(target / history_rel, (source / ASSET_FILES["json"]).read_bytes())
    written.append(str(history_rel))
    return {"changed": True, "written": written, "status": audit["audit"]["status"]}
