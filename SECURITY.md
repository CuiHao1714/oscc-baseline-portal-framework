# Security and data-governance notice

This repository contains application source code only. It does **not** include
patient-level data, linkage tables, controlled dictionaries, credentials,
database snapshots, audit logs, or deployment secrets.

Before publishing a change, run:

```bash
python scripts/verify_project.py
git status --ignored
git diff --cached --name-only
```

Never commit `data/`, a SQLite/PostgreSQL dump, `.env`, backups, exports, or a
screenshot that displays patient information. Configure dataset paths and
secrets only through the deployment environment or an approved secret manager.

If sensitive content was committed or pushed, immediately revoke access as
appropriate, rotate affected credentials, contact the repository host to purge
cached copies, and follow your institution's incident-response process.
