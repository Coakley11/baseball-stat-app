"""Read-only: what the public (anon) Supabase key can see in the QA project.

For each table, one HTTP GET with the anon key asking only for a row count (limit=0: no row is
returned). Compares with the service-role count. Writes nothing; prints no key, URL or row.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

from qa_guard import load_qa_config  # noqa: E402

TABLES = [
    "suite_users", "suite_app_current_state", "suite_user_settings", "suite_activity_events",
    "suite_resume_items", "suite_saved_items", "baseball_shared_draft_rooms", "baseball_shared_leagues",
    "subscriptions",
]


def _count(base: str, key: str, table: str) -> str:
    r = requests.get(f"{base}/rest/v1/{table}?select=*&limit=0", timeout=15,
                     headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"})
    if r.status_code in (200, 206):
        return (r.headers.get("Content-Range") or "*/?").split("/")[-1]
    if r.status_code in (401, 403):
        return f"denied ({r.status_code})"
    return f"http {r.status_code}"


def main() -> int:
    sa, problems = load_qa_config()
    if problems:
        print("QA guard: NOT OK — nothing was sent.")
        return 2
    base = str(sa["supabase_url"]).rstrip("/")
    print(f"{'table':30s} {'service_role rows':>18s} {'anon can count':>16s}")
    for t in TABLES:
        print(f"{t:30s} {_count(base, str(sa['supabase_key']), t):>18s} {_count(base, str(sa['supabase_anon_key']), t):>16s}")
    print("Nothing was written; no rows were returned (limit=0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
