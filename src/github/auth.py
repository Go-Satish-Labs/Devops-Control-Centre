"""Credential resolution. Preferred: GitHub App installation token (set by the workflow)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import jwt
import requests


class AuthError(RuntimeError):
    """Raised when no usable credentials are available."""


@dataclass(frozen=True)
class Credentials:
    token: str
    mode: str


def create_app_jwt(app_id: str, private_key_pem: str, now: float | None = None) -> str:
    issued = int(now or time.time())
    payload = {"iat": issued - 60, "exp": issued + 540, "iss": str(app_id)}
    token = jwt.encode(payload, private_key_pem, algorithm="RS256")
    return token if isinstance(token, str) else token.decode("utf-8")


def installation_token_for_org(app_id: str, private_key_pem: str, org: str,
                               base_url: str = "https://api.github.com", timeout: int = 30) -> str:
    app_jwt = create_app_jwt(app_id, private_key_pem)
    headers = {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}
    installation = requests.get(f"{base_url}/orgs/{org}/installation", headers=headers, timeout=timeout)
    if installation.status_code >= 400:
        raise AuthError(f"GitHub App is not installed on {org} (HTTP {installation.status_code})")
    installation_id = installation.json()["id"]
    token_response = requests.post(
        f"{base_url}/app/installations/{installation_id}/access_tokens", headers=headers, timeout=timeout
    )
    if token_response.status_code >= 400:
        raise AuthError(f"could not create installation token (HTTP {token_response.status_code})")
    return token_response.json()["token"]


def resolve_credentials(organization: str, base_url: str = "https://api.github.com", env=None) -> Credentials:
    env = dict(os.environ if env is None else env)
    if env.get("DCC_TOKEN"):
        return Credentials(env["DCC_TOKEN"], env.get("DCC_AUTH_MODE") or "token")
    app_id, key = env.get("DCC_APP_ID"), env.get("DCC_APP_PRIVATE_KEY")
    if app_id and key:
        token = installation_token_for_org(app_id, key.replace("\\n", "\n"), organization, base_url)
        return Credentials(token, "github-app")
    if env.get("GITHUB_TOKEN"):
        return Credentials(env["GITHUB_TOKEN"], "github-token-limited")
    raise AuthError("no credentials: set DCC_TOKEN, DCC_APP_ID + DCC_APP_PRIVATE_KEY, or GITHUB_TOKEN")
