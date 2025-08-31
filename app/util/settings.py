from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Reads PORT and CACHE_TTL (default 300).
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    port: int = Field(8000, validation_alias="PORT")
    cache_ttl: int = Field(300, validation_alias="CACHE_TTL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

