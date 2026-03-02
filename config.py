from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Database
    database_url: str = "postgresql://user:pass@localhost:5432/stock_monitor"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Polygon.io
    polygon_api_key: str = ""

    # JWT
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 1440
    jwt_algorithm: str = "HS256"

    # SMTP (keep existing names)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # App
    alert_cooldown_minutes: int = 30
    max_stocks_per_user: int = 5
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout: int = 30


settings = Settings()
