from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Accessibility Quality API"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    DATABASE_URL: str = "sqlite+aiosqlite:///./a11y_quality.db"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
