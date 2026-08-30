"""Application configuration loaded from environment variables.

Secrets are never hard-coded. Populate them via the environment (see
``.env.example``). In local development a ``.env`` file in this directory is
loaded automatically.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent

# Load environment variables from backend/.env into the process environment so
# both os.getenv(...) and the typed Settings below resolve identical values.
load_dotenv(ROOT_DIR / ".env", override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Supabase (PostgreSQL storage only) ---
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")
    # Optional direct Postgres URI for running SQL migrations (Supabase → Database → URI).
    database_url: str = Field(default="", alias="DATABASE_URL")

    # --- Auth (FastAPI-issued JWT) ---
    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expires_minutes: int = Field(default=60 * 24 * 365, alias="JWT_EXPIRES_MINUTES")

    # --- Email (Resend) ---
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    resend_from_email: str = Field(
        default="Eduspace <eduspace@nextforms.in>",
        alias="RESEND_FROM_EMAIL",
    )

    # --- Legacy SMTP (optional fallback; prefer Resend) ---
    email_user: str = Field(default="", alias="EMAIL_USER")
    email_password: str = Field(default="", alias="EMAIL_PASSWORD")
    email_host: str = Field(default="smtp.gmail.com", alias="EMAIL_HOST")
    email_port: int = Field(default=587, alias="EMAIL_PORT")
    email_from: str = Field(default="", alias="EMAIL_FROM")

    # --- Payment credential encryption ---
    # Optional Fernet key (url-safe base64 32-byte). If empty, derived from JWT_SECRET.
    payment_credentials_key: str = Field(default="", alias="PAYMENT_CREDENTIALS_KEY")

    # --- Eddy AI (Groq) ---
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")

    # --- App ---
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def cors_origin_list(self) -> List[str]:
        raw = self.cors_origins.strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def mail_from_address(self) -> str:
        """Canonical From address for all transactional emails."""
        value = (self.resend_from_email or "").strip()
        if value:
            return value
        if self.email_from:
            return self.email_from
        if self.email_user:
            return self.email_user
        return "Eduspace <eduspace@nextforms.in>"

    def require_supabase(self) -> None:
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key),
                ("JWT_SECRET", self.jwt_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
