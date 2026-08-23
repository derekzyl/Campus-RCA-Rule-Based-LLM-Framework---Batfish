from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_backend: Literal["openai", "ollama", "gemini", "mock"] = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_timeout_s: float = 600.0
    ollama_num_predict: int = 512
    batfish_host: str = "localhost"
    batfish_port: int = 9997
    batfish_network: str = "campus"
    use_batfish: bool = True
    llm_temperature: float = 0.0
    allow_remediation_apply: bool = False
    project_root: Path = ROOT


@lru_cache
def get_settings() -> Settings:
    return Settings()
