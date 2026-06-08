from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    firecrawl_api_key: str
    openrouter_api_key: str
    openrouter_model: str = "openai/gpt-oss-20b:free"
    redis_url: str = "redis://localhost:6379"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
