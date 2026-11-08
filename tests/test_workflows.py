from datetime import datetime, timedelta, timezone

import yaml

from src.auditors.security import classify_action_reference, iter_uses
from src.auditors.workflows import classify_ci, detect_capabilities, parse_workflow, summarize_runs
from src.health.statuses import FAILED, HEALTHY, NO_CI, WARNING

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)
VALID = "name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
NO_TESTS = "name: x\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"


def run(conclusion, days_ago=1):
    created = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {"id": 1, "conclusion": conclusion, "status": "completed", "created_at": created,
            "html_url": "https://example.test/run"}


def classify(runs, *, texts=(VALID,), active=1, invalid=0, count=1):
    summary = summarize_runs(runs, stale_days=90, now=NOW)
    status, _ = classify_ci(workflow_count=count, invalid_count=invalid, active_count=active,
                            summary=summary, capabilities=detect_capabilities(list(texts)),
                            repeated_threshold=2)
    return status


def test_invalid_yaml_is_detected():
    assert parse_workflow("a.yml", "jobs: [unclosed")["valid"] is False


def test_missing_jobs_is_detected():
    assert parse_workflow("a.yml", "name: x")["valid"] is False


def test_valid_workflow_is_parsed():
    assert parse_workflow("ci.yml", VALID)["valid"] is True


def test_no_workflow_files_is_no_ci():
    assert classify([], count=0) == NO_CI


def test_no_executions_is_not_healthy():
    assert classify([]) == WARNING


def test_successful_tested_workflow_is_healthy():
    assert classify([run("success")]) == HEALTHY


def test_latest_failure_is_failed():
    assert classify([run("failure"), run("success")]) == FAILED


def test_repeated_failures_are_failed():
    assert classify([run("failure"), run("failure")]) == FAILED


def test_cancelled_latest_run_is_warning():
    assert classify([run("cancelled"), run("success")]) == WARNING


def test_missing_test_step_is_warning():
    assert classify([run("success")], texts=(NO_TESTS,)) == WARNING


def test_stale_latest_run_is_warning():
    assert classify([run("success", days_ago=120)]) == WARNING


def test_all_workflows_disabled_is_warning():
    assert classify([run("success")], active=0) == WARNING


def test_invalid_only_is_failed():
    assert classify([], count=1, invalid=1) == FAILED


def test_action_reference_classification():
    assert classify_action_reference("Go-Satish-Labs", "actions/checkout@v4") == ("first_party", False)
    assert classify_action_reference("Go-Satish-Labs", "some/tool@" + "a" * 40) == ("third_party", True)
    assert classify_action_reference("Go-Satish-Labs", "some/tool@v2") == ("third_party", False)
    assert classify_action_reference("Go-Satish-Labs", "./local-action") == ("local", True)


def test_iter_uses_reads_jobs_and_steps():
    doc = yaml.safe_load(
        "on: push\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n"
        "  b:\n    uses: other/wf/.github/workflows/x.yml@main\n"
    )
    assert set(iter_uses(doc)) == {"actions/checkout@v4", "other/wf/.github/workflows/x.yml@main"}
