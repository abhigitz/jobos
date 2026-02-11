from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    jwt_refresh_secret_key: str
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    app_url: str = ""
    n8n_api_key: str = ""
    admin_api_key: str = ""
    n8n_secret: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
