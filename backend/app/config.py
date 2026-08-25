"""Configuración de la aplicación, leída del entorno."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Entorno
    app_env: str = "development"
    log_level: str = "info"
    api_port: int = 8000

    # Infraestructura
    database_url: str = "postgresql+asyncpg://zonepark:zonepark_dev@db:5432/zonepark"
    redis_url: str = "redis://redis:6379/0"

    # Seguridad
    jwt_secret: str = "dev_secret_cambiar_en_produccion"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: str = ""
    max_failed_attempts: int = 5
    lockout_minutes: int = 15
    pin_length: int = 6

    # Reglas de negocio por defecto (cada tenant puede sobrescribirlas)
    tenant_mode: str = "path"
    default_timezone: str = "America/Bogota"
    default_currency: str = "COP"
    default_rounding_step: int = 50

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
