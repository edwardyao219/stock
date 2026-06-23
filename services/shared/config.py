from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "stock-research-system"
    database_url: str = "postgresql+psycopg://stock:stock@localhost:5432/stock_research"
    redis_url: str = "redis://localhost:6379/0"
    timezone: str = "Asia/Shanghai"
    enable_ai: bool = False
    data_start_date: str = "20240101"
    notification_channels: str = ""
    dingtalk_webhook_url: str | None = None
    dingtalk_secret: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
