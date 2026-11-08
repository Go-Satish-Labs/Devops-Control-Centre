# Daily notifications

The `notify` command posts one daily organization-health discussion in the control
repository and synchronizes one centralized issue per repository whose audit status
matches `config/notifications.yml`. Audited repositories are never modified.

```text
python -m src.cli notify --source reports/organization-health.json --output build
```

The workflow requires a token with Discussions and Issues write access. Prefer the
GitHub App secrets `DCC_APP_ID` and `DCC_APP_PRIVATE_KEY`; `DCC_PAT` is supported
as a fallback. Configure the discussion category, issue label, statuses, and the
per-run creation cap in `config/notifications.yml`.
