"""Organization repository discovery and identifier redaction."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.utils.config import Settings


@dataclass(frozen=True)
class RepositoryInfo:
    name: str
    default_branch: str | None
    visibility: str
    private: bool
    archived: bool
    fork: bool
    language: str | None
    html_url: str | None
    pushed_at: str | None


@dataclass
class DiscoveryResult:
    repositories: list[RepositoryInfo] = field(default_factory=list)
    excluded: list[tuple[RepositoryInfo, str]] = field(default_factory=list)

    @property
    def total_seen(self) -> int:
        return len(self.repositories) + len(self.excluded)


def normalize_repository(item: Mapping[str, Any]) -> RepositoryInfo:
    private = bool(item.get("private"))
    visibility = item.get("visibility") or ("private" if private else "public")
    return RepositoryInfo(
        name=item["name"],
        default_branch=item.get("default_branch"),
        visibility=visibility,
        private=private,
        archived=bool(item.get("archived")),
        fork=bool(item.get("fork")),
        language=item.get("language"),
        html_url=item.get("html_url"),
        pushed_at=item.get("pushed_at"),
    )


def exclusion_reason(repo: RepositoryInfo, settings: Settings) -> str | None:
    if repo.name in settings.excluded_repositories:
        return "configured exclusion"
    if repo.fork and not settings.include_forks:
        return "fork excluded by configuration"
    if repo.archived and not settings.include_archived:
        return "archived repository excluded by configuration"
    return None


def discover_repositories(client, organization: str, settings: Settings) -> DiscoveryResult:
    result = DiscoveryResult()
    for item in client.paginate(f"/orgs/{organization}/repos", params={"type": "all"}):
        repo = normalize_repository(item)
        reason = exclusion_reason(repo, settings)
        if reason:
            result.excluded.append((repo, reason))
        else:
            result.repositories.append(repo)
    result.repositories.sort(key=lambda r: r.name.lower())
    return result


def public_identifier(repo: RepositoryInfo, redact_private: bool) -> str:
    """Private names become stable hashes so public artifacts never expose them."""
    if redact_private and repo.private:
        digest = hashlib.sha256(repo.name.encode("utf-8")).hexdigest()[:8]
        return f"private-{digest}"
    return repo.name


def new_repository_names(current: Iterable[str], previous: Iterable[str]) -> list[str]:
    return sorted(set(current) - set(previous))
