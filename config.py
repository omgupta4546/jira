"""
config.py — centralised settings loaded from .env
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


import os
from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent / ".env"),
        extra="ignore"
    )

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"

    # OpenAI (alternative if Gemini quota issues)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # AI Provider: "gemini" or "openai"
    ai_provider: str = "gemini"

    # GitHub
    github_token: str = ""

    # Jira
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    # App
    mock_mode: bool = False
    enable_test_generation: bool = True


def get_settings() -> Settings:
    # Force reload of settings from .env file
    env_path = str(Path(__file__).parent / ".env")
    return Settings(_env_file=env_path)
