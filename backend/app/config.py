from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://excon:excon@localhost:5432/excon"
    mlx_base_url: str = "http://127.0.0.1:8080"
    mlx_model: str = "mlx-community/Qwen3-8B-4bit"
    tavily_api_key: str = ""
    prospeo_api_key: str = ""
    http_timeout_seconds: float = 20
    website_max_bytes: int = 2_000_000
    website_max_pages: int = 8
    prospeo_page_size: int = 10
    prospeo_enrich_limit: int = 5
    prospeo_enrich_mobile: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_reload: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
