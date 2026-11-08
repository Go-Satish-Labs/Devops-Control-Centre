import json
from datetime import timedelta
from pathlib import Path

import pytest

from src.reporting.csv_generator import render_csv
from src.reporting.json_generator import render_json
from src.reporting.markdown_generator import render_markdown
from src.reporting.publisher import ArtifactValidationError, PublishError, publish, validate_artifacts
from src.reporting.svg_generator import render_svg
from tests.fakes import make_audit, repo_dict


def write_build(build: Path, audit: dict) -> None:
    (build / "assets").mkdir(parents=True, exist_ok=True)
    (build / "reports").mkdir(parents=True, exist_ok=True)
    (build / "assets" / "organization-health.svg").write_text(render_svg(audit), encoding="utf-8")
    (build / "reports" / "organization-health.json").write_text(render_json(audit), encoding="utf-8")
    (build / "reports" / "organization-health.md").write_text(render_markdown(audit), encoding="utf-8")
    (build / "reports" / "organization-health.csv").write_text(render_csv(audit), encoding="utf-8")


def test_publish_writes_artifacts_and_history(tmp_path):
    build, target = tmp_path / "build", tmp_path / "repo"
    write_build(build, make_audit([repo_dict()]))
    result = publish(build, target)
    assert result["changed"] is True
    assert (target / "assets" / "organization-health.svg").is_file()
    assert (target / "reports" / "organization-health.csv").is_file()
    history = list((target / "reports" / "history").glob("*.json"))
    assert len(history) == 1


def test_failed_audit_is_never_published(tmp_path):
    build, target = tmp_path / "build", tmp_path / "repo"
    write_build(build, make_audit([], status="FAILED"))
    with pytest.raises(PublishError):
        publish(build, target)
    assert not (target / "assets" / "organization-health.svg").exists()


def test_unchanged_content_is_not_republished(tmp_path):
    build, target = tmp_path / "build", tmp_path / "repo"
    audit = make_audit([repo_dict()])
    write_build(build, audit)
    publish(build, target)
    later = json.loads(json.dumps(audit))
    later["audit"]["timestamp"] = "2026-11-08T12:00:00+00:00"
    later["audit"]["run_id"] = "999"
    write_build(build, later)
    assert publish(build, target)["changed"] is False


def test_invalid_svg_is_rejected(tmp_path):
    build = tmp_path / "build"
    write_build(build, make_audit([repo_dict()]))
    (build / "assets" / "organization-health.svg").write_text("<svg><broken", encoding="utf-8")
    with pytest.raises(ArtifactValidationError):
        validate_artifacts(build)
