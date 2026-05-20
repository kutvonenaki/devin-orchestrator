"""Preflight: does Devin's API work AND can Devin see our GitHub repo?

Creates one READ-ONLY Devin session that just inspects the repo and reports
back via structured output. It does NOT change code or open a PR.

Run from the project root (so .env is picked up):

    conda run --no-capture-output -n devin-takehome \
        python scripts/check_devin_repo.py

Exit code 0 = Devin reported it can access the repo.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# allow running as `python scripts/check_devin_repo.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.devin_client import DevinAPIError, DevinClient  # noqa: E402

POLL_SECONDS = 15
MAX_WAIT_MINUTES = 25

SCHEMA = {
    "type": "object",
    "properties": {
        "can_access": {"type": "boolean"},
        "repo": {"type": "string"},
        "default_branch": {"type": "string"},
        "top_level_paths": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["can_access", "repo", "notes"],
}


def _prompt(repo: str) -> str:
    return (
        "Connectivity preflight only. Do NOT modify code, run tests, or open "
        f"a pull request.\n\nConfirm you can access the GitHub repository "
        f"`{repo}`. Inspect it and report: whether you can access it "
        "(can_access), its default branch, and up to 15 top-level paths in "
        "the repository root. If you cannot access it, set can_access=false "
        "and explain why in notes. Once you have produced the structured "
        "output, you are done — finish and end the session."
    )


async def main() -> int:
    try:
        s = get_settings()
    except Exception as e:  # noqa: BLE001
        print(f"❌ Could not load settings/.env: {e}")
        print("   Ensure .env has DEVIN_API_KEY, DEVIN_ORG_ID, GITHUB_REPO "
              "and run from the project root.")
        return 2

    repo = s.github_repo
    print(f"→ Devin org: {s.devin_org_id}")
    print(f"→ Target repo: {repo}")
    print(f"→ API base: {s.devin_api_base}\n")

    devin = DevinClient(s.devin_api_base, s.devin_org_id, s.devin_api_key)
    try:
        try:
            session = await devin.create_session(
                prompt=_prompt(repo),
                structured_output_schema=SCHEMA,
                title="Preflight: repo access check",
                tags=["preflight"],
                repos=[repo],
            )
        except DevinAPIError as e:
            print(f"❌ Devin API rejected create_session: {e}")
            print("   → Check DEVIN_API_KEY / DEVIN_ORG_ID.")
            return 2

        sid = session.get("session_id")
        print(f"✓ Session created: {sid}")
        print(f"  Watch live: {session.get('url')}\n")

        deadline = time.monotonic() + MAX_WAIT_MINUTES * 60
        last = None
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                session = await devin.get_session(sid)
            except DevinAPIError as e:
                print(f"  (transient poll error, retrying: {e})")
                if time.monotonic() > deadline:
                    print("\n❌ Timed out waiting for the session.")
                    return 1
                continue
            st = (session.get("status"), session.get("status_detail"))
            if st != last:
                print(f"  status={st[0]} detail={st[1]}")
                last = st
            if devin.is_done(session):  # terminal OR structured_output ready
                break
            if time.monotonic() > deadline:
                print("\n❌ Timed out waiting for the session.")
                return 1

        out = session.get("structured_output") or {}
        print("\n--- Devin structured_output ---")
        print(json.dumps(out, indent=2))
        if out.get("can_access") is True:
            print("\n✅ Devin CAN see the repo. Preflight passed.")
            return 0
        print("\n❌ Devin reports it CANNOT access the repo.")
        print("   → In Devin, connect GitHub and grant access to "
              f"`{repo}` (org: {s.devin_org_id}).")
        return 1
    finally:
        await devin.aclose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130)
