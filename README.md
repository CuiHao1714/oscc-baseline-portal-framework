# OSCC Baseline Portal Framework

FastAPI reference implementation for a controlled clinical-research portal.
It demonstrates role-based access, searchable patient records, structured
JSON-Schema validation, append-only audit events, database snapshots, and a
SQLite-to-PostgreSQL migration path.

## Public-source boundary

This repository intentionally contains **no patient data** and cannot be used
as a clinical system without an institutionally governed, de-identified data
package. Do not add cohort exports, UUID-to-name linkage files, database files,
value dictionaries derived from controlled data, audit logs, backups, or
credentials.

The data package and its schema are supplied at deployment time through
`DATASET_PACKAGE_PATH` and `DATASET_SCHEMA_PATH`. They remain outside Git.

## Included technical components

- FastAPI, SQLAlchemy, Jinja2, server-side sessions, CSRF controls, and bcrypt.
- Viewer/editor/admin permissions with write-event auditing.
- Indexed relational core fields plus a JSON/JSONB clinical-record document.
- Structured list filtering, clinically grouped review screens, and guided entry.
- SQLite development support; PostgreSQL/JSONB migration and rollback scripts.
- Public-release safety check: `python scripts/verify_project.py`.

## Local setup with your own approved de-identified package

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Set the values in .env through your approved local secret/configuration process.
set -a; . ./.env; set +a
.venv/bin/python -m app.import_dataset \
  --dataset "$DATASET_PACKAGE_PATH" \
  --admin-user admin \
  --admin-password 'use-a-unique-12-plus-character-password'
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

For production, use TLS behind a reverse proxy, a managed PostgreSQL instance,
organization identity management, secrets management, backup/restore drills,
and a formal governance review. This reference implementation does not claim
compliance with any clinical, privacy, or electronic-record regulation.

## Before publishing

```bash
python scripts/verify_project.py
git status --ignored
git diff --cached --name-only
```

Choose and add a license before creating a public repository. No license is
included here because licensing must be decided by the project owner.
