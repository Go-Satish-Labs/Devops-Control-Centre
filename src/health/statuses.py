"""Status vocabulary shared by auditors, scoring and reporting."""

HEALTHY = "HEALTHY"
WARNING = "WARNING"
FAILED = "FAILED"
NO_CI = "NO_CI"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNKNOWN = "UNKNOWN"

CRITICAL = "CRITICAL"
OK = "OK"

CONFIGURED = "CONFIGURED"
NOT_CONFIGURED = "NOT_CONFIGURED"

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON_COMPLIANT"
EXCLUDED = "EXCLUDED"

FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
CONCLUDED = frozenset({"success", "cancelled"}) | FAILURE_CONCLUSIONS

_RANK = {
    OK: 0, HEALTHY: 0, CONFIGURED: 0, COMPLIANT: 0, NOT_CONFIGURED: 0,
    NOT_APPLICABLE: 0, EXCLUDED: 0, NO_CI: 1, UNKNOWN: 2,
    WARNING: 3, NON_COMPLIANT: 3, CRITICAL: 4, FAILED: 4,
}


def worst(statuses) -> str:
    """Return the most severe status from an iterable (HEALTHY when empty)."""
    values = [s for s in statuses if s]
    if not values:
        return HEALTHY
    return max(values, key=lambda s: _RANK.get(s, 2))
