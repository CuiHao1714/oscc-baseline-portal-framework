"""One-way, verified copy from SQLite to an explicitly empty PostgreSQL database."""
import argparse
import sys
from pathlib import Path
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base
from app.models import AuditLog, Patient, ReleaseSnapshot, User

TABLES = [(User, ("id", "username", "password_hash", "role", "is_active", "created_at")), (Patient, ("id", "subject_id", "cohort_year", "age_at_diagnosis", "sex", "diagnosis_date", "primary_site", "ajcc_stage", "survival_status", "record_data", "source_version", "created_at", "updated_at")), (AuditLog, ("id", "actor_id", "action", "entity_type", "entity_id", "before_data", "after_data", "remote_addr", "created_at")), (ReleaseSnapshot, ("id", "snapshot_id", "label", "reason", "storage_path", "storage_sha256", "dataset_sha256", "patient_count", "audit_log_count", "actor_id", "created_at"))]


def count_rows(session, model): return session.scalar(select(func.count()).select_from(model)) or 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--confirm", required=True, help="must equal MIGRATE_EMPTY_POSTGRES")
    args = parser.parse_args()
    if args.confirm != "MIGRATE_EMPTY_POSTGRES": raise SystemExit("Confirmation token rejected")
    source_engine = create_engine(args.source_url, future=True)
    target_engine = create_engine(args.target_url, future=True)
    if source_engine.url.get_backend_name() != "sqlite": raise SystemExit("Source must be SQLite")
    if target_engine.url.get_backend_name() != "postgresql": raise SystemExit("Target must be PostgreSQL")
    Base.metadata.create_all(bind=target_engine)
    SourceSession, TargetSession = sessionmaker(bind=source_engine, future=True), sessionmaker(bind=target_engine, future=True)
    with SourceSession() as source, TargetSession() as target:
        if any(count_rows(target, model) for model, _ in TABLES): raise SystemExit("Target database is not empty; migration refused")
        source_tables = set(inspect(source_engine).get_table_names())
        source_counts = {model.__tablename__: count_rows(source, model) if model.__tablename__ in source_tables else 0 for model, _ in TABLES}
        for model, columns in TABLES:
            if model.__tablename__ not in source_tables: continue
            for row in source.scalars(select(model)).yield_per(200):
                target.add(model(**{column: getattr(row, column) for column in columns}))
            target.flush()
        target.commit()
        target_counts = {model.__tablename__: count_rows(target, model) for model, _ in TABLES}
    if source_counts != target_counts: raise SystemExit(f"Row-count verification failed: {source_counts} != {target_counts}")
    with target_engine.begin() as connection:
        for table, _ in TABLES:
            connection.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.__tablename__}', 'id'), COALESCE((SELECT MAX(id) FROM {table.__tablename__}), 1), true)"))
    print("Migration verified:", target_counts)


if __name__ == "__main__": main()
