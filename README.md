# DevOps-Control-Center

Central governance and monitoring for every repository in **Go-Satish-Labs**. It discovers repositories, audits CI/CD, environments, secrets metadata and security configuration, plans or enforces default-branch rulesets, and publishes an SVG health dashboard plus JSON, Markdown and CSV reports. It runs entirely on GitHub Actions, with no external hosting.

## What it produces

| Artifact | Purpose |
|---|---|
| `assets/organization-health.svg` | Primary dashboard, generated from real audit results |
| `reports/organization-health.json` | Complete machine-readable audit record |
| `reports/organization-health.md` | Human-readable report |
| `reports/organization-health.csv` | One row per repository |
| `reports/history/YYYY-MM-DD-HHMMSS.json` | Historical JSON snapshots |

Dashboard raw URL, once committed:
`https://raw.githubusercontent.com/Go-Satish-Labs/DevOps-Control-Center/main/assets/organization-health.svg`

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| Organization Audit | Every 6 hours, manual, repository-created dispatch | Read-only audit. Writes to `build/` only |
| Report Generation | After a successful audit | Validates artifacts, publishes them, commits only if content changed |
| Branch Ruleset Enforcement | Daily (dry-run), manual | Plans rulesets. `enforce` requires typing `ENFORCE` |
| Repository Discovery | Daily, manual, repository-created dispatch | Discovers repositories and reports new ones |

If an audit fails, nothing is published and the last successful dashboard and reports stay in place. If some repositories cannot be read, the audit still completes and is marked **PARTIAL** with its completeness percentage. It is never reported as fully successful.

## Health classification

Per repository, the overall status is one of `HEALTHY`, `WARNING`, `FAILED`, `NO_CI`, `NOT_APPLICABLE` (archived or empty), or `UNKNOWN`. A repository with no workflow executions is never classified as healthy. Organization health is the share of healthy repositories among applicable ones, with archived repositories excluded.

## Configuration

All organization-specific values are in `config/`:

- `organization.yml`: organization name, API URL, retry settings, dashboard row limit.
- `exclusions.yml`: excluded repositories, ruleset exclusions, write-protected repositories, fork and archive handling.
- `audit-policy.yml`: default mode, stale-workflow threshold, repeated-failure threshold, private-repository redaction.
- `rulesets.yml`: ruleset name, target branches, pull-request rules, status-check behaviour.

Nothing about repositories is hardcoded.

## Safety guarantees

- The audit never writes to any repository. Audit-only is the default.
- Rulesets are created only in `enforce` mode and only when no covering ruleset exists. Existing rules are never modified or deleted, and a same-named ruleset that does not cover the branch is reported for manual review, not duplicated.
- `.github` and `DevOps-Control-Center` are never given rulesets (see `exclusions.yml`). The organization README is never modified.
- Secret values are never requested. Only secret counts are read.
- Private repository names are replaced with stable hashes in public artifacts. Private run links and job names are omitted.
- Every dynamic string in the SVG, Markdown and CSV is escaped. CSV cells are protected against spreadsheet formula injection.

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
```

Run an audit locally with a token that can read the organization:

```bash
export DCC_TOKEN=ghp_xxx          # or DCC_APP_ID + DCC_APP_PRIVATE_KEY
python -m src.cli audit --mode audit-only --output build
python -m src.cli validate --source build
```

## Layout

```
src/
  audit_runner.py        orchestration and report assembly
  cli.py                 entry points used by the workflows
  auditors/              workflows, environments, security
  discovery/             repository discovery and redaction
  rulesets/engine.py     ruleset planning and enforcement
  health/                status vocabulary and scoring
  reporting/             SVG, JSON, Markdown, CSV and publisher
  github/                REST client with retries and authentication
config/                  organization configuration
tests/                   offline unit tests (mocked GitHub API)
docs/SETUP_GUIDE.md      GitHub App setup, permissions, troubleshooting
```

See **[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)** for the GitHub App, secrets, first run, and troubleshooting.
