from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://vnss:vnss@localhost:5432/vnss"
    secret_key: str = "change-me-to-a-long-random-string"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Agent writing craft / self-review (server-only)
    agent_craft_mode: Literal["auto", "off", "lite", "full"] = "auto"
    agent_self_review: Literal["auto", "on", "off"] = "auto"

    # Optional separate critic model (empty = reuse writer credentials)
    critic_api_key: str = ""
    critic_api_base_url: str = ""
    critic_api_model: str = ""

    settings_fernet_key: str = ""
    algorithm: str = "HS256"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
