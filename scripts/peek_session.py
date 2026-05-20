"""Inspect an existing Devin session by ID (no new session created).

    conda run --no-capture-output -n devin-takehome \
        python scripts/peek_session.py <session_id>
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.devin_client import DevinClient  # noqa: E402


async def main() -> int:
    if len(sys.argv) < 2:
        print("usage: peek_session.py <session_id>")
        return 2
    sid = sys.argv[1]
    s = get_settings()
    devin = DevinClient(s.devin_api_base, s.devin_org_id, s.devin_api_key)
    try:
        sess = await devin.get_session(sid)
    finally:
        await devin.aclose()

    print(f"status        : {sess.get('status')}")
    print(f"status_detail : {sess.get('status_detail')}")
    print(f"url           : {sess.get('url')}")
    prs = sess.get("pull_requests") or []
    if prs:
        print(f"pull_requests : {[p.get('url') or p.get('html_url') for p in prs]}")
    out = sess.get("structured_output")
    print("\nstructured_output:")
    print(json.dumps(out, indent=2) if out else "  (none yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
