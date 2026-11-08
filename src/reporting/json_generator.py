"""JSON report: the complete, machine-readable audit record."""
import json
from typing import Any


def render_json(audit: dict[str, Any]) -> str:
    return json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
