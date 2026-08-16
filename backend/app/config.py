from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        # utf-8-sig strips BOM so Windows editors don't break DATABASE_URL key
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    # Host port matches docker-compose.yml (54102:5432)
    database_url: str = "postgresql+asyncpg://vnss:vnss@localhost:54102/vnss"
    secret_key: str = "change-me-to-a-long-random-string"
    access_token_expire_minutes: int = 60 * 24 * 7
    refresh_token_expire_days: int = 30
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # openai (default, e.g. DeepSeek) | ollama (local model via Ollama OpenAI endpoint)
    llm_provider: str = "openai"

    # Agent writing craft / self-review (server-only)
    agent_craft_mode: Literal["auto", "off", "lite", "full"] = "auto"
    agent_self_review: Literal["auto", "on", "off"] = "auto"

    # Optional separate critic model (empty = reuse writer credentials)
    critic_api_key: str = ""
    critic_api_base_url: str = ""
    critic_api_model: str = ""

    settings_fernet_key: str = ""
    algorithm: str = "HS256"

    # Moegirlpedia (萌娘百科) lore lookup — self-use; respect CC BY-NC-SA
    moegirl_enabled: bool = True
    moegirl_api_base: str = "https://zh.moegirl.org.cn/api.php"
    moegirl_user_agent: str = (
        "VNScriptStudio/0.1 (self-use writing aid; "
        "+https://github.com/Saltedfish20060409/vn-script-studio)"
    )

    # LLM usage accounting / quota. 0 = unlimited (soft cap per user per day).
    llm_daily_token_cap: int = 0

    # Optional Redis URL (redis://host:6379/0). When set and reachable, the
    # collab SSE event bus bridges workers via Redis pub/sub so multi-worker
    # deployments see live lock/member/comment events. Leave empty for
    # single-worker (in-process) broadcasts.
    redis_url: str = ""

    # Optional embedding endpoint for pgvector semantic search (OpenAI
    # compatible). Leave empty to keep heuristic keyword retrieval.
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


_DEFAULT_SECRET = "change-me-to-a-long-random-string"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Hard-fail on the publicly-known default or an obviously weak key: a
    # guessable JWT signing secret allows forging any user's tokens.
    if settings.secret_key == _DEFAULT_SECRET or len(settings.secret_key) < 32:
        raise RuntimeError(
            "SECRET_KEY 未配置为强随机值：请在 backend/.env 设置 "
            "SECRET_KEY=$(openssl rand -hex 64)（至少 32 字符），"
            "并轮换所有已签发令牌。"
        )
    return settings
