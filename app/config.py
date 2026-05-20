"""Environment-based settings.

Required vars raise on construction (fail-fast). The pytest suite never
constructs real Settings, so it needs no credentials.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Devin (required) ---
    devin_api_key: str
    devin_org_id: str
    devin_api_base: str = "https://api.devin.ai/v3"

    # --- GitHub ---
    github_repo: str  # owner/repo
    github_token: Optional[str] = None  # optional: unauth reads + skip comments
    issue_label: str = "devin"

    # --- timing ---
    # GitHub-facing polls are slow on purpose: the fork is public and we run
    # token-free, so we stay well under the unauthenticated rate limit.
    poll_interval_seconds: int = 180  # issue poll (GitHub)
    pr_comment_poll_interval_seconds: int = 180  # PR-comment poll (GitHub)
    devin_poll_interval_seconds: int = 60  # session poll (Devin, not GitHub)
    max_poll_minutes: int = 60

    # --- app ---
    data_dir: str = "./data"
    port: int = 8000

    @property
    def github_owner_repo(self) -> tuple[str, str]:
        owner, _, repo = self.github_repo.partition("/")
        return owner, repo


@lru_cache
def get_settings() -> Settings:
    """Cached Settings. Raises ValidationError if a required var is missing."""
    return Settings()
