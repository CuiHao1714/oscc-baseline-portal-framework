"""Create a consistent full-database snapshot and append its manifest."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import AuditLog, Patient, ReleaseSnapshot, User


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="e.g. pre-batch-20260925")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor", help="portal username creating this snapshot")
    parser.add_argument("--backup-dir", default=os.getenv("PORTAL_BACKUP_DIR", "./backups"))
    args = parser.parse_args()
    backup_dir = Path(args.backup_dir).resolve(); backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = f"{args.label}-{timestamp}-{uuid4().hex[:8]}"
    driver = engine.url.get_backend_name()
    suffix = ".sqlite3" if driver == "sqlite" else ".dump"
    backup_path = backup_dir / f"{snapshot_id}{suffix}"
    if driver == "sqlite":
        source = Path(engine.url.database or "")
        if not source.is_file(): raise SystemExit("SQLite database file not found")
        with sqlite3.connect(source) as source_db, sqlite3.connect(backup_path) as target_db:
            source_db.backup(target_db)
    elif driver == "postgresql":
        if not shutil.which("pg_dump"): raise SystemExit("pg_dump is required for PostgreSQL snapshots")
        subprocess.run(["pg_dump", "--format=custom", f"--file={backup_path}", settings.database_url], check=True)
    else:
        raise SystemExit(f"Unsupported database backend: {driver}")
    Base.metadata.create_all(bind=engine)
    dataset_path = Path(settings.dataset_path)
    with SessionLocal() as db:
        actor = db.query(User).filter(User.username == args.actor).one_or_none() if args.actor else None
        snapshot = ReleaseSnapshot(snapshot_id=snapshot_id, label=args.label, reason=args.reason, storage_path=str(backup_path), storage_sha256=sha256(backup_path), dataset_sha256=sha256(dataset_path) if dataset_path.is_file() else None, patient_count=db.query(Patient).count(), audit_log_count=db.query(AuditLog).count(), actor_id=actor.id if actor else None)
        db.add(snapshot); db.commit()
    manifest = {"snapshot_id": snapshot_id, "created_at": timestamp, "database_backend": driver, "storage_path": str(backup_path), "storage_sha256": sha256(backup_path), "reason": args.reason}
    backup_path.with_suffix(backup_path.suffix + ".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(snapshot_id)


if __name__ == "__main__": main()
