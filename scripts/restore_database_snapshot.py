"""Destructive full-database restore; requires an explicit confirmation token."""
import argparse
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--confirm-restore", required=True, help="must equal the snapshot file name")
    args = parser.parse_args()
    source = Path(args.snapshot).resolve()
    if not source.is_file() or args.confirm_restore != source.name:
        raise SystemExit("Snapshot missing or confirmation token does not equal its file name")
    target = create_engine(args.target_url, future=True).url
    if target.get_backend_name() == "sqlite":
        target_path = Path(target.database or "").resolve()
        if target_path == source: raise SystemExit("Snapshot and target must differ")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            preserved = target_path.with_name(target_path.name + ".pre_restore_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".db")
            with sqlite3.connect(target_path) as old_db, sqlite3.connect(preserved) as preserved_db: old_db.backup(preserved_db)
        with sqlite3.connect(source) as source_db, sqlite3.connect(target_path) as target_db: source_db.backup(target_db)
    elif target.get_backend_name() == "postgresql":
        if not shutil.which("pg_restore"): raise SystemExit("pg_restore is required for PostgreSQL restore")
        subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", f"--dbname={args.target_url}", str(source)], check=True)
    else:
        raise SystemExit(f"Unsupported database backend: {target.get_backend_name()}")
    print("Restore completed; run scripts/verify_project.py and application smoke tests before reopening access.")


if __name__ == "__main__": main()
