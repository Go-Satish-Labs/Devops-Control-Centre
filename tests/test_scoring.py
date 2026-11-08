from src.health.scoring import (build_statistics, classify_repository, derive_audit_status, percentage)
from src.health.statuses import (COMPLIANT, CONFIGURED, CRITICAL, FAILED, HEALTHY, NO_CI, NON_COMPLIANT,
                                 NOT_APPLICABLE, NOT_CONFIGURED, OK, UNKNOWN, WARNING)
from tests.fakes import repo_dict


def classify(**overrides):
    base = dict(archived=False, ci_status=HEALTHY, security_status=OK, branch_status=COMPLIANT,
                environment_status=CONFIGURED)
    base.update(overrides)
    return classify_repository(**base)[0]


def test_archived_is_not_applicable():
    assert classify(archived=True) == NOT_APPLICABLE


def test_missing_ci_is_no_ci():
    assert classify(ci_status=NO_CI, branch_status=NON_COMPLIANT) == NO_CI


def test_failing_ci_or_critical_security_is_failed():
    assert classify(ci_status=FAILED) == FAILED
    assert classify(security_status=CRITICAL) == FAILED


def test_unknown_inputs_never_become_healthy():
    assert classify(ci_status=UNKNOWN) == UNKNOWN
    assert classify(security_status=UNKNOWN) == UNKNOWN


def test_warnings_and_healthy():
    assert classify() == HEALTHY
    assert classify(ci_status=WARNING) == WARNING
    assert classify(branch_status=NON_COMPLIANT) == WARNING
    assert classify(environment_status=NOT_CONFIGURED) == HEALTHY


def test_percentage_handles_zero_denominator():
    assert percentage(1, 3) == 33.3
    assert percentage(0, 0) is None


def test_health_excludes_archived_from_denominator():
    repos = [repo_dict(overall=HEALTHY), repo_dict(overall=WARNING), repo_dict(overall=NOT_APPLICABLE)]
    stats = build_statistics(repos)
    assert stats["health"]["health_percent"] == 50.0
    assert stats["health"]["not_applicable"] == 1


def test_completeness_counts_unknown_checks():
    repos = [repo_dict(ci=UNKNOWN), repo_dict()]
    stats = build_statistics(repos)
    assert stats["completeness"]["checks_total"] == 8
    assert stats["completeness"]["percent"] == 87.5


def test_audit_status_rules():
    assert derive_audit_status(audited=0, completeness_percent=100.0) == "FAILED"
    assert derive_audit_status(audited=5, completeness_percent=80.0) == "PARTIAL"
    assert derive_audit_status(audited=5, completeness_percent=100.0) == "COMPLETE"
