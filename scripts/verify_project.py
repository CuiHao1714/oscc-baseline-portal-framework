"""Read-only publication-safety checks for the public portal source tree."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".xlsx", ".xls", ".csv", ".parquet"}
FORBIDDEN_DIRECTORIES = {".venv", "graphify-out", "project_memory", "Ledger", "data"}


def main() -> None:
    required = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "DESIGN.md",
        PROJECT_ROOT / "SECURITY.md",
        PROJECT_ROOT / ".gitignore",
        PROJECT_ROOT / "app/main.py",
        PROJECT_ROOT / "app/services.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing required files:\n" + "\n".join(missing))

    violations = []
    for path in PROJECT_ROOT.rglob("*"):
        relative = path.relative_to(PROJECT_ROOT)
        if any(part in FORBIDDEN_DIRECTORIES for part in relative.parts):
            continue
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(str(relative))
    if violations:
        raise SystemExit("Controlled or tabular data must not be published:\n" + "\n".join(violations))

    print("PASS: required public-source files exist")
    print("PASS: no controlled databases or tabular datasets are present")
    print("NOTE: this script does not access, validate, or start any patient dataset")


if __name__ == "__main__":
    main()
