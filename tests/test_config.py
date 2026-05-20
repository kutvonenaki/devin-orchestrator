import pytest
from pydantic import ValidationError

from app.config import Settings

_REQUIRED = ["DEVIN_API_KEY", "DEVIN_ORG_ID", "GITHUB_REPO"]


def test_missing_required_raises(monkeypatch):
    for k in _REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_loads_and_defaults(monkeypatch):
    monkeypatch.setenv("DEVIN_API_KEY", "k")
    monkeypatch.setenv("DEVIN_ORG_ID", "org")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    s = Settings(_env_file=None)
    assert s.devin_api_base == "https://api.devin.ai/v3"
    assert s.github_token is None  # optional
    assert s.issue_label == "devin"
    assert s.github_owner_repo == ("owner", "repo")
