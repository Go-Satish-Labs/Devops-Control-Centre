"""CSV report: one row per audited repository. Cells are formula-injection safe."""
import csv
import io
from typing import Any

from src.utils.text import csv_safe

CSV_COLUMNS = [
    "repository", "visibility", "archived", "fork", "default_branch", "primary_language",
    "overall", "ci_status", "ci_latest_conclusion", "security_status", "security_coverage",
    "branch_status", "branch_action", "environment_status", "finding_count", "reasons",
]


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def render_csv(audit: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for repo in audit.get("repositories", []):
        row = [
            repo.get("name"), repo.get("visibility"), _yes_no(repo.get("archived")), _yes_no(repo.get("fork")),
            repo.get("default_branch") or "", repo.get("primary_language") or "", repo.get("overall"),
            repo["ci"]["status"], repo["ci"].get("latest_conclusion") or "",
            repo["security"]["status"], repo["security"].get("coverage", ""),
            repo["branch"]["status"], repo["branch"].get("action", ""),
            repo["environment"]["status"], len(repo.get("findings", [])),
            "; ".join(repo.get("reasons", [])),
        ]
        writer.writerow([csv_safe(value) for value in row])
    return buffer.getvalue()
