"""Connectivity check — "are things actually connected?"

Fast and FREE: no Devin session is created, no ACUs spent, no PRs.
  * GitHub: list the labelled issues on the repo (proves repo + token/label).
  * Devin : auth probe against the v3 sessions endpoint (no session created).

This is intentionally SEPARATE from the offline pytest suite (which is mocked
and needs no credentials). This one needs a real .env. Run from repo root:

    conda run --no-capture-output -n devin-takehome \
        python scripts/check_connections.py

Exit 0 = both reachable & authenticated.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.github_client import GitHubClient  # noqa: E402


async def check_github(s) -> bool:
    print(f"GitHub  → repo={s.github_repo} "
          f"token={'set' if s.github_token else 'none (unauth)'} "
          f"label={s.issue_label}")
    gh = GitHubClient(s.github_repo, s.github_token)
    try:
        issues = await gh.list_open_issues(s.issue_label)
        print(f"  ✅ reachable — {len(issues)} open '{s.issue_label}' issue(s)")
        for i in issues[:5]:
            print(f"     #{i['number']} {i.get('title')}")
        return True
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 404:
            hint = "repo not found / no access"
        elif code in (401, 403):
            hint = "bad/expired GITHUB_TOKEN" if s.github_token else "rate limited or repo access denied — set GITHUB_TOKEN"
        else:
            hint = ""
        print(f"  ❌ HTTP {code} {('— ' + hint) if hint else ''}")
        return False
    except httpx.HTTPError as e:
        print(f"  ❌ unreachable: {e}")
        return False
    finally:
        await gh.aclose()


async def check_devin(s) -> bool:
    # Auth probe only: GET the sessions collection. We do NOT create a session.
    url = f"{s.devin_api_base.rstrip('/')}/organizations/{s.devin_org_id}/sessions"
    print(f"Devin   → org={s.devin_org_id} base={s.devin_api_base}")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, headers={"Authorization": f"Bearer {s.devin_api_key}"})
    except httpx.HTTPError as e:
        print(f"  ❌ unreachable: {e}")
        return False
    if r.status_code in (401, 403):
        print(f"  ❌ HTTP {r.status_code} — bad DEVIN_API_KEY / DEVIN_ORG_ID")
        return False
    # Any non-auth response (200/404/405/422…) means we reached an
    # authenticated Devin endpoint without spending anything.
    print(f"  ✅ authenticated (HTTP {r.status_code}, no session created)")
    return True


async def main() -> int:
    try:
        s = get_settings()
    except Exception as e:  # noqa: BLE001
        print(f"❌ Could not load .env/settings: {e}")
        print("   Need DEVIN_API_KEY, DEVIN_ORG_ID, GITHUB_REPO; run from "
              "the project root.")
        return 2

    gh_ok = await check_github(s)
    print()
    dv_ok = await check_devin(s)
    print()
    if gh_ok and dv_ok:
        print("✅ All connections OK. Safe to run check_devin_repo.py / run_once.py.")
        return 0
    print("❌ Fix the failing connection above before the real run.")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
