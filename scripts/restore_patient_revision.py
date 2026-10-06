"""Restore one patient to the state preceding a selected audit event."""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import User
from app.services import restore_patient_from_audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-id", required=True, type=int)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True, help="record in the terminal/SOP ticket before execution")
    args = parser.parse_args()
    with SessionLocal() as db:
        actor = db.query(User).filter(User.username == args.actor, User.role == "admin").one_or_none()
        if actor is None: raise SystemExit("An active admin actor is required")
        patient = restore_patient_from_audit(db, args.audit_id, actor.id, "cli-rollback")
        db.commit()
    print(f"Restored audit event {args.audit_id}; patient={'deleted' if patient is None else patient.subject_id}; reason={args.reason}")


if __name__ == "__main__": main()
