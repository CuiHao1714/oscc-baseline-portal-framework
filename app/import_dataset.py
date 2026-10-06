"""One-time import of the validated V0.1 package; refuses a non-empty database."""
import argparse
import json
from pathlib import Path
from .database import Base, SessionLocal, engine
from .models import Patient, User
from .security import hash_password
from .services import upsert_patient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--admin-user", required=True)
    parser.add_argument("--admin-password", required=True)
    args = parser.parse_args()
    package = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if package.get("dataset", {}).get("dataset_id") != "xjkq-oscc-baseline-v0.1":
        raise SystemExit("Unexpected dataset package")
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.query(User).filter(User.username == args.admin_user).first():
            raise SystemExit("Admin username already exists")
        if db.query(Patient).count():
            raise SystemExit("Database already contains patients; refusing to import")
        admin = User(username=args.admin_user, password_hash=hash_password(args.admin_password), role="admin")
        db.add(admin); db.flush()
        for record in package["records"]:
            upsert_patient(db, record, package["dataset"]["version"], admin.id, "dataset-import")
        db.commit()
    print(f"Imported {len(package['records'])} patients and created admin {args.admin_user}")


if __name__ == "__main__":
    main()
