"""Run the real pipeline ONCE — no uvicorn, no 60s poll loop.

Two modes:
  * no args      -> one poll cycle: list labelled issues, process the new ones
  * --issue N    -> process exactly issue #N

It still waits for the Devin session(s) to finish (that polling is inherent),
then prints the resulting task JSON and exits. Run from the project root:

    conda run --no-capture-output -n devin-takehome \
        python scripts/run_once.py --issue 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.devin_client import DevinClient  # noqa: E402
from app.github_client import GitHubClient  # noqa: E402
from app.orchestrator import process_issue  # noqa: E402
from app.poller import poll_once  # noqa: E402
from app.store import Store  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", type=int, help="process only this issue number")
    args = ap.parse_args()

    s = get_settings()
    store = Store(s.data_dir)
    devin = DevinClient(s.devin_api_base, s.devin_org_id, s.devin_api_key)
    github = GitHubClient(s.github_repo, s.github_token)
    print(f"→ repo={s.github_repo}  data_dir={Path(s.data_dir).resolve()}\n")

    try:
        if args.issue is not None:
            issue = await github.get_issue(args.issue)
            print(f"Processing issue #{args.issue}: {issue.get('title')}")
            await process_issue(issue, store, devin, github, s)
            ids = [f"issue-{args.issue}"]
        else:
            sem = asyncio.Semaphore(3)
            tasks = await poll_once(store, github, devin, s, sem)
            if not tasks:
                print("No new labelled issues to process. Done.")
                return 0
            print(f"Launched {len(tasks)} issue(s); waiting for completion…")
            await asyncio.gather(*tasks)
            ids = [t["internal_id"] for t in store.load_all()]
    finally:
        await devin.aclose()
        await github.aclose()

    print("\n--- results ---")
    for iid in ids:
        t = store.load_task(iid)
        if not t:
            continue
        print(f"\n[{t['status']}] {iid} — {t.get('issue_title')}")
        print(f"  pr_url: {t.get('pr_url')}")
        if t.get("error"):
            print(f"  error: {t['error']}")
        if t.get("structured_output"):
            print("  structured_output:")
            print(json.dumps(t["structured_output"], indent=2)[:2000])
    print(f"\nArtifacts in {Path(s.data_dir).resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
