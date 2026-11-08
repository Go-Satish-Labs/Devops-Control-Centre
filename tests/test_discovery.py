from dataclasses import replace

from src.discovery.repositories import (exclusion_reason, new_repository_names, normalize_repository,
                                        public_identifier)
from src.utils.config import load_settings


def settings(**overrides):
    return replace(load_settings(), **overrides)


def item(**overrides):
    data = {"name": "api", "default_branch": "main", "private": False, "archived": False,
            "fork": False, "language": "Python", "html_url": "https://github.com/Go-Satish-Labs/api"}
    data.update(overrides)
    return data


def test_visibility_derived_when_missing():
    assert normalize_repository(item(private=True)).visibility == "private"
    assert normalize_repository(item()).visibility == "public"


def test_configured_exclusion_and_forks():
    s = settings(excluded_repositories=frozenset({"legacy"}), include_forks=False)
    assert exclusion_reason(normalize_repository(item(name="legacy")), s) == "configured exclusion"
    assert exclusion_reason(normalize_repository(item(fork=True)), s) is not None
    assert exclusion_reason(normalize_repository(item()), s) is None


def test_archived_repositories_are_kept_by_default():
    assert exclusion_reason(normalize_repository(item(archived=True)), settings()) is None


def test_private_identifiers_are_redacted_and_stable():
    repo = normalize_repository(item(name="secret-service", private=True))
    redacted = public_identifier(repo, True)
    assert redacted.startswith("private-")
    assert "secret" not in redacted
    assert redacted == public_identifier(repo, True)
    assert public_identifier(repo, False) == "secret-service"


def test_new_repositories_detected():
    assert new_repository_names(["a", "b", "c"], ["a"]) == ["b", "c"]
