from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "航班节点匹配仿真验证系统"
    database_url: str = "sqlite+aiosqlite:///./flight_simulator.db"
    cors_origins: str = "http://localhost:5178,http://127.0.0.1:5178"
    airport_code: str = "XIY"
    timezone: str = "Asia/Shanghai"
    celery_broker_url: str = "redis://localhost:6380/0"
    celery_result_backend: str = "redis://localhost:6380/1"
    task_always_eager: bool = True
    external_auth_url: str | None = None
    external_object_store_url: str | None = None
    outbound_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

