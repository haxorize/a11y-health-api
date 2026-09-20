from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The API's identity, not settings: each reaches the committed openapi.json
# (info.title, info.version, every path), so no .env or shell may vary them.
PROJECT_NAME = "Accessibility Health API"
VERSION = "0.1.0"
API_V1_PREFIX = "/api/v1"


class Settings(BaseSettings):
    # Each attribute name is the environment-variable name, matched exactly
    # (`case_sensitive`), and .env.example, README.md and ci.yml spell it the
    # same way. A rename here does not fail: the variable goes unread and the
    # field silently falls back to its default.
    DEBUG: bool = False

    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/a11y_health"
    # A template, not the database the suite connects to: each pytest run builds
    # and drops `<name>_<pid>` from it, through the `postgres` maintenance
    # database the same host and credentials must reach too (tests/conftest.py).
    TEST_DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/a11y_health_test"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    @model_validator(mode="after")
    def validate_cors_origins(self) -> Settings:
        if not self.DEBUG and "*" in self.ALLOWED_ORIGINS:
            raise ValueError("Wildcard '*' is not allowed in ALLOWED_ORIGINS when DEBUG is False")
        return self


settings = Settings()
