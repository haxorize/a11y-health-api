from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Accessibility Quality API"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/a11y_quality"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/a11y_quality_test"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    @model_validator(mode="after")
    def validate_cors_origins(self) -> Settings:
        if not self.DEBUG and "*" in self.ALLOWED_ORIGINS:
            raise ValueError("Wildcard '*' is not allowed in ALLOWED_ORIGINS when DEBUG is False")
        return self


settings = Settings()
