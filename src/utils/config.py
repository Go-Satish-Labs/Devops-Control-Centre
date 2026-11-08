"""Configuration loading. Organization-specific values live in config/*.yml."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
VALID_MODES = ("audit-only", "dry-run", "enforce")


class ConfigError(ValueError):
    """Raised when configuration is missing or malformed."""


def load_yaml(filename: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    path = config_dir / filename
    if not path.exists():
        raise ConfigError(f"missing configuration file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{filename} must contain a YAML mapping")
    return data


@dataclass(frozen=True)
class Settings:
    organization: str
    control_repository: str
    api_base_url: str
    request_timeout: int
    max_retries: int
    dashboard_repository_limit: int
    excluded_repositories: frozenset[str]
    excluded_for_rulesets: frozenset[str]
    write_protected_repositories: frozenset[str]
    include_forks: bool
    include_archived: bool
    stale_workflow_days: int
    repeated_failure_threshold: int
    recent_runs_window: int
    redact_private_repositories: bool
    default_mode: str
    ruleset: dict[str, Any]


def load_settings(config_dir: Path = CONFIG_DIR) -> Settings:
    org_cfg = load_yaml("organization.yml", config_dir)
    exclusions = load_yaml("exclusions.yml", config_dir)
    policy = load_yaml("audit-policy.yml", config_dir)
    rulesets = load_yaml("rulesets.yml", config_dir)

    organization = os.environ.get("DCC_ORGANIZATION") or org_cfg.get("organization")
    if not organization:
        raise ConfigError("organization must be set in config/organization.yml")

    mode = policy.get("mode", "audit-only")
    if mode not in VALID_MODES:
        raise ConfigError(f"audit-policy mode must be one of {VALID_MODES}")

    ruleset = rulesets.get("ruleset") or {}
    if ruleset.get("scope", "repository") not in ("organization", "repository"):
        raise ConfigError("rulesets.scope must be 'organization' or 'repository'")

    return Settings(
        organization=organization,
        control_repository=org_cfg.get("control_repository", "DevOps-Control-Center"),
        api_base_url=str(org_cfg.get("api_base_url", "https://api.github.com")).rstrip("/"),
        request_timeout=int(org_cfg.get("request_timeout", 30)),
        max_retries=int(org_cfg.get("max_retries", 4)),
        dashboard_repository_limit=int(org_cfg.get("dashboard_repository_limit", 40)),
        excluded_repositories=frozenset(exclusions.get("excluded_repositories") or []),
        excluded_for_rulesets=frozenset(exclusions.get("excluded_for_rulesets") or []),
        write_protected_repositories=frozenset(exclusions.get("write_protected_repositories") or []),
        include_forks=bool(exclusions.get("include_forks", True)),
        include_archived=bool(exclusions.get("include_archived", True)),
        stale_workflow_days=int(policy.get("stale_workflow_days", 90)),
        repeated_failure_threshold=int(policy.get("repeated_failure_threshold", 2)),
        recent_runs_window=int(policy.get("recent_runs_window", 20)),
        redact_private_repositories=bool(policy.get("redact_private_repositories", True)),
        default_mode=mode,
        ruleset=ruleset,
    )
