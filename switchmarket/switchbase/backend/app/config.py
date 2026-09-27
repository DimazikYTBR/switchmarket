from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "SwitchMarket"
    telegram_bot_token: str = "CHANGE_ME_BOT_TOKEN"
    jwt_secret: str = "CHANGE_ME_JWT_SECRET"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    database_url: str = "sqlite+aiosqlite:///./switchmarket.db"
    hold_period_hours: int = 24
    telegram_init_data_max_age_seconds: int = 86400
    platform_wallet_address: str = "CHANGE_ME_PLATFORM_TON_WALLET"
    withdrawal_min_amount: float = 1.0
    cors_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
