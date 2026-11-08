"""Test doubles: a routed fake GitHub client and an audit-document builder."""
from src.github.client import GitHubAPIError
from src.health import scoring


class FakeClient:
    """Routes by exact path. Unknown paths behave like GitHub 404 responses."""

    def __init__(self, routes=None, lists=None, graphql=None):
        self.routes = dict(routes or {})
        self.lists = dict(lists or {})
        self.posts: list[tuple[str, dict]] = []
        self.patches: list[tuple[str, dict]] = []
        self.request_count = 0
        self._graphql = graphql

    def get_json(self, path, params=None):
        value = self.routes.get(path)
        if value is None:
            raise GitHubAPIError(404, "Not Found", path)
        if isinstance(value, Exception):
            raise value
        return value

    def paginate(self, path, params=None, item_key=None):
        value = self.lists.get(path)
        if value is None:
            raise GitHubAPIError(404, "Not Found", path)
        if isinstance(value, Exception):
            raise value
        yield from value

    def post_json(self, path, body):
        self.posts.append((path, body))
        return {"id": len(self.posts), "number": len(self.posts)}

    def patch_json(self, path, body):
        self.patches.append((path, body))
        return {}

    def graphql(self, query, variables=None):
        if self._graphql is None:
            raise GitHubAPIError(404, "no GraphQL handler", "/graphql")
        return self._graphql(query, variables or {})


def repo_dict(name="r", overall="HEALTHY", ci="HEALTHY", security="OK", branch="COMPLIANT",
              env="CONFIGURED", conclusion="success", coverage="covered", failures=0):
    return {
        "name": name, "visibility": "public", "archived": False, "fork": False,
        "default_branch": "main", "primary_language": "Python", "url": None,
        "overall": overall, "reasons": [],
        "ci": {"status": ci, "latest_conclusion": conclusion, "consecutive_failures": failures,
               "failed_jobs": [], "latest_run_url": None, "latest_run_at": None},
        "security": {"status": security, "coverage": coverage,
                     "dependabot": {"open": 0}, "code_scanning": {"open": 0}},
        "branch": {"status": branch, "action": "none", "reason": ""},
        "environment": {"status": env},
        "findings": [], "errors": [],
    }


def make_audit(repos, status="COMPLETE"):
    stats = scoring.build_statistics(repos, repeated_threshold=2)
    return {
        "schema_version": 1,
        "organization": "Go-Satish-Labs",
        "control_repository": "DevOps-Control-Center",
        "audit": {"run_id": "123", "timestamp": "2026-11-08T06:00:00+00:00", "status": status,
                  "mode": "audit-only", "auth_mode": "test", "duration_seconds": 1.0,
                  "completeness_percent": stats["completeness"]["percent"], "api_requests": 5},
        "discovery": {"total_discovered": len(repos), "audited": len(repos), "excluded": 0,
                      "archived": 0, "forks": 0, "private": 0, "public": len(repos),
                      "without_ci": stats["health"]["no_ci"]},
        "metrics": stats["health"],
        "ci_statistics": stats["ci"],
        "branch_protection": {**stats["branch"], "scope": "repository", "scope_notes": []},
        "environment_statistics": {**stats["environment"],
                                   "organization_secrets": {"availability": "available", "secret_count": 0}},
        "security_statistics": stats["security"],
        "completeness": stats["completeness"],
        "repositories": repos,
        "latest_failures": scoring.build_latest_failures(repos),
        "recent_issues": scoring.build_recent_issues(repos, 15),
        "recommendations": scoring.build_recommendations(repos, stats),
        "api_limitations": [],
        "excluded_repositories": [],
    }
