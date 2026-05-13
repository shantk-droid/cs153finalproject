from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# The Claude Code harness injects `ANTHROPIC_API_KEY=""` (empty) into the env, which would
# beat the .env file under pydantic-settings' default precedence. Load `.env` with override=True
# so the file's values win over env-var blanks. This runs before Settings is instantiated below.
_dotenv_path = Path(__file__).resolve().parents[2] / ".env"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path, override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    llm_daily_usd_budget: float = 10.0

    cors_origins: str = "http://localhost:3000"
    data_dir: str = "./data/datasets"
    m5_artifacts_dir: str = "./m5/artifacts"

    demo_password: str = ""
    sentry_dsn: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).resolve()

    @property
    def m5_artifacts_path(self) -> Path:
        api_dir = Path(__file__).parent
        return (api_dir / self.m5_artifacts_dir).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
