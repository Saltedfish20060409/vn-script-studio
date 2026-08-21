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
    deepseek_model: str = "deepseek-v4-flash"
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

    # LLM usage accounting / quota. 0 = unlimited.
    # Applies to users bringing their own Key (BYOK). We do not bill for that.
    llm_daily_token_cap: int = 0
    # Cap only when the request falls through to the *server* DeepSeek key.
    # 0 = also unlimited. Default 200k so a shared key cannot be drained.
    llm_shared_key_daily_cap: int = 200_000

    # Soft storage caps (generous — anti-abuse, not a product paywall).
    max_projects_per_user: int = 80

    # Kill switch: set ALLOW_REGISTRATION=false to stop new sign-ups.
    allow_registration: bool = True

    # Comma-separated usernames that may call /api/v1/admin/* (ban/unban).
    # Empty = no HTTP admin surface; use `python -m app ban` on the host instead.
    admin_usernames: str = ""

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

    # Auth rate limiting (login/register per-IP). Set false to disable (e.g.
    # in tests or single-user local setups behind a proxy that already limits).
    rate_limit_enabled: bool = True

    # Test/e2e only: skip Resend and mark new accounts verified.
    auth_auto_verify: bool = False

    # Resend transactional email (verify / password reset). Empty = email auth off.
    resend_api_key: str = ""
    resend_from_email: str = "noreply@send.studio.nexesr.top"
    public_app_url: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_username_set(self) -> set[str]:
        return {u.strip() for u in self.admin_usernames.split(",") if u.strip()}


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
