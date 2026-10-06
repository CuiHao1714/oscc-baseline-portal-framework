import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./portal.db")
    secret_key: str = os.getenv("APP_SECRET_KEY", "development-only-change-me")
    # No dataset is distributed with this repository. Operators must point
    # these settings at an institutionally approved, de-identified package.
    schema_path: str = os.getenv("DATASET_SCHEMA_PATH", "./data/schema.json")
    dataset_path: str = os.getenv("DATASET_PACKAGE_PATH", "./data/dataset.json")
    session_https_only: bool = os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true"

    def validate(self) -> None:
        if self.app_env == "production" and self.secret_key == "development-only-change-me":
            raise RuntimeError("APP_SECRET_KEY must be configured in production")


settings = Settings()
