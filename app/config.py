from functools import lru_cache

from pydantic import BaseSettings


class Settings(BaseSettings):
    env_name: str = "local"
    base_url: str = "http://localhost:8000"
    db_url: str = "sqlite:///./cantera-papers.db"
    github_client_id: str
    github_client_secret: str
    cookie_secret: str
    secret_state: str

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
