# Setup guide

Follow these steps once. Everything after that runs on schedule.

## 1. Push the repository

Create `Go-Satish-Labs/DevOps-Control-Center` and push the contents of this project to its default branch (`main`).

In **Settings → Actions → General → Workflow permissions**, leave the default. The report job requests `contents: write` itself.

## 2. Create the GitHub App (recommended)

A GitHub App is preferred over a personal access token because it has least-privilege permissions, an audit trail, and no dependency on one person.

1. Go to the organization **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Name: `devops-control-center` (any unique name). Homepage URL: the repository URL.
3. Uncheck **Webhook → Active**. No webhook is needed.
4. Set the permissions below, then click **Create GitHub App**.
5. Note the **App ID** shown at the top of the app page.
6. Under **Private keys**, click **Generate a private key**. A `.pem` file downloads.
7. Under **Install App**, install it on **Go-Satish-Labs** with **All repositories** selected.

### Required permissions

Repository permissions:

| Permission | Level | Used for |
|---|---|---|
| Metadata | Read | Repository listing (mandatory) |
| Contents | Read | Reading `.github/workflows/` and default-branch checks |
| Actions | Read | Workflow definitions and run history |
| Administration | Read & write | Reading and, in enforce mode only, creating rulesets |
| Environments | Read | Environment protection rules |
| Secrets | Read | Secret **names and counts** only (values are never requested) |
| Dependabot alerts | Read | Open alert counts |
| Code scanning alerts | Read | Open alert counts |
| Secret scanning alerts | Read | Optional, for alert visibility |
| Checks | Read | Detecting status-check names for rulesets |

Organization permissions:

| Permission | Level | Used for |
|---|---|---|
| Administration | Read & write | Organization rulesets (enforce mode, scope `organization`) |
| Secrets | Read | Organization secret counts |
| Members | Read | Optional |

If a permission is not granted, the affected check is recorded as an API limitation and the audit becomes PARTIAL. It never silently passes.

## 3. Add secrets to the repository

**Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `DCC_APP_ID` | The App ID from step 2.5 |
| `DCC_APP_PRIVATE_KEY` | The full contents of the `.pem` file, including the `BEGIN` and `END` lines |

Optional fallback if you cannot use an App: `DCC_PAT`, a fine-grained personal access token with the same repository and organization permissions. The workflows prefer the App token and fall back to `DCC_PAT`, then to `GITHUB_TOKEN`. `GITHUB_TOKEN` only covers the control repository, so a run with it will be PARTIAL and say so.

## 4. Test API access

From your machine, with the App installed, confirm the App can read the organization:

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export DCC_APP_ID=123456
export DCC_APP_PRIVATE_KEY="$(cat path/to/private-key.pem)"
python -m src.cli discover --output build
cat build/discovery.json
```

You should see the discovered and audited counts. An `AuthError` means the App is not installed on the organization or the key is wrong.

## 5. First run

1. **Actions → Organization Audit → Run workflow**, mode `audit-only`.
2. Check the job summary. Then confirm **Report Generation** ran and committed `assets/` and `reports/`.
3. Open `assets/organization-health.svg` in the repository. It is the dashboard.
4. **Actions → Branch Ruleset Enforcement → Run workflow**, mode `dry-run`. Review the plan in the artifact `dcc-rulesets-report`.
5. When you are satisfied, run it again with mode `enforce` and type `ENFORCE` in the confirm field.

Rulesets created by this tool are named `DCC Default Branch Protection` (configurable). They protect `main` and `master` by requiring pull requests with one approval, resolved conversations, no force pushes, and no branch deletion.

## 6. Control-repository protection

`DevOps-Control-Center` is excluded from rulesets by default, because the report job pushes commits to `main`. If you later protect it, add the App as a bypass actor, or the report commits will be rejected.

## 7. Adjusting behaviour

Edit files in `config/` and commit them. No code changes are needed for:

- adding exclusions (`exclusions.yml`),
- changing required approvals or status-check behaviour (`rulesets.yml`),
- changing staleness and failure thresholds (`audit-policy.yml`).

To require specific checks instead of auto-detecting them, set `required_status_checks` to a list such as `[test, build]`. Matrix jobs produce checks named like `test (ubuntu-latest, 3.12)`, so list those names exactly.

## Limitations

- **Repository creation events.** GitHub Actions cannot subscribe to organization-wide repository events directly. The audit runs every six hours, and discovery runs daily. For near-instant detection, relay an organization webhook to this repository's `repository_dispatch` with event type `repository-created`, using a small external forwarder or a GitHub App webhook handler.
- **Plan-dependent features.** Secret scanning, push protection and code scanning on private repositories may need GitHub Advanced Security. Those are reported as limitations, not failures.
- **Organization README.** Integrating the dashboard into `Go-Satish-Labs/.github` is intentionally deferred to a manual step. The raw SVG URL above is what you embed.
- **Image caching.** GitHub caches images for a few minutes, so a new dashboard may take a moment to appear in README embeds.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Audit fails with `GitHub API error 401` | Expired or invalid credentials | Check `DCC_APP_PRIVATE_KEY` includes the full PEM. Regenerate the key if needed |
| `GitHub App is not installed on Go-Satish-Labs` | App not installed, or installed on a subset | Install it with **All repositories** |
| Audit status PARTIAL, many `permission` limitations | App is missing a permission | Add the permission in the App settings. Organization owners must accept the new permissions |
| Report Generation skipped | Audit failed or was cancelled | Only successful audits are published. Check the failed audit run |
| `publish` refuses with "FAILED audit" | No repositories could be audited | Usually a token with no organization access. Re-run discovery locally |
| Ruleset run shows `manual_review` | A ruleset with the same name exists but does not cover the branch | Inspect it in repository settings, then fix or rename it. The tool will not overwrite it |
| `enforce mode requires confirmation` | `ENFORCE` was not typed in the confirm input | Re-run with `ENFORCE` exactly |
| Report commit push rejected | Branch protection on `DevOps-Control-Center` | See section 6 |
| Dashboard shows `UNKNOWN` for environments | Environment metadata not accessible or unsupported on the plan | Grant Environments read, or accept it as a limitation |
| SVG looks stale in README | Image cache | Wait a few minutes and reload |
| Local tests fail on import | Python below 3.12 | Use Python 3.12 or newer |
