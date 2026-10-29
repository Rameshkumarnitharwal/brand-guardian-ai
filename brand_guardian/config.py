"""Centralised settings loaded from environment variables (.env supported)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    # Azure OpenAI
    openai_endpoint: str
    openai_api_key: str
    openai_api_version: str
    chat_deployment: str
    embedding_deployment: str
    # Azure AI Search
    search_endpoint: str
    search_api_key: str
    search_index_name: str
    retrieval_top_k: int
    # Azure Storage
    storage_connection_string: str
    storage_container: str
    # Azure Video Indexer
    subscription_id: str
    resource_group: str
    vi_account_name: str
    vi_account_id: str
    vi_location: str
    vi_poll_interval: int
    vi_timeout: int
    max_video_minutes: float
    ytdlp_cookies_browser: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        openai_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
        openai_api_key=_env("AZURE_OPENAI_API_KEY"),
        openai_api_version=_env("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        chat_deployment=_env("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"),
        embedding_deployment=_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        search_endpoint=_env("AZURE_SEARCH_ENDPOINT"),
        search_api_key=_env("AZURE_SEARCH_API_KEY"),
        search_index_name=_env("AZURE_SEARCH_INDEX_NAME", "compliance-rules"),
        retrieval_top_k=int(_env("RETRIEVAL_TOP_K", "8")),
        storage_connection_string=_env("AZURE_STORAGE_CONNECTION_STRING"),
        storage_container=_env("AZURE_STORAGE_CONTAINER", "videos"),
        subscription_id=_env("AZURE_SUBSCRIPTION_ID"),
        resource_group=_env("AZURE_RESOURCE_GROUP"),
        vi_account_name=_env("AZURE_VI_ACCOUNT_NAME"),
        vi_account_id=_env("AZURE_VI_ACCOUNT_ID"),
        vi_location=_env("AZURE_VI_LOCATION", "eastus"),
        vi_poll_interval=int(_env("VI_POLL_INTERVAL_SECONDS", "15")),
        vi_timeout=int(_env("VI_TIMEOUT_SECONDS", "1800")),
        max_video_minutes=float(_env("MAX_VIDEO_MINUTES", "5")),
        ytdlp_cookies_browser=os.getenv("YTDLP_COOKIES_BROWSER", ""),
    )
