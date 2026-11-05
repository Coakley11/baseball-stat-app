"""Read-only probe of the QA Supabase project (HTTP GET only; nothing is written).

Runs only when scripts/qa/qa_guard.py accepts .streamlit/secrets.toml. Prints table existence and row
counts, the auth settings that matter for the tests, the number of auth users, and whether any row looks
copied from production (known production usernames or the real Danny-Barry league id). Prints no key,
URL, email or row content.
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
PRODUCTION_MARKERS = {  # existence counts only, never values
    "suite_users": ("external_id", ["daniel", "coakley11", "user_coakley11", "ariel"]),
    "baseball_shared_leagues": ("league_id", ["league:f6e324c5f85617f76d1fa2d4"]),
}


def _count(base: str, key: str, table: str, extra: str = "") -> tuple[str, str]:
    r = requests.get(f"{base}/rest/v1/{table}?select=*&limit=1{extra}", timeout=15,
                     headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"})
    if r.status_code in (200, 206):  # 206: exists, more rows than the 1 requested
        total = (r.headers.get("Content-Range") or "*/?").split("/")[-1]
        return "exists", total
    if r.status_code in (404, 400) and ("PGRST205" in r.text or "does not exist" in r.text or "schema cache" in r.text):
        return "MISSING", "-"
    return f"http {r.status_code}", "-"


def main() -> int:
    sa, problems = load_qa_config()
    if problems:
        print("QA guard: NOT OK — nothing was sent.")
        for p in problems:
            print("  -", p)
        return 2
    base = str(sa["supabase_url"]).rstrip("/")
    service, anon = str(sa["supabase_key"]), str(sa["supabase_anon_key"])

    print("== Tables (service role, GET with count)")
    for t in TABLES:
        state, total = _count(base, service, t)
        print(f"  {t:30s} {state:10s} rows={total}")

    print("== Rows that look copied from production (counts only)")
    for t, (col, values) in PRODUCTION_MARKERS.items():
        state, total = _count(base, service, t, f"&{col}=in.({','.join(values)})")
        print(f"  {t:30s} {state:10s} matching={total}")

    print("== Auth settings (anon key)")
    r = requests.get(f"{base}/auth/v1/settings", headers={"apikey": anon}, timeout=15)
    if r.ok:
        s = r.json()
        ext = s.get("external") or {}
        enabled = sorted(k for k, v in ext.items() if v is True)
        print(f"  email provider enabled : {bool(ext.get('email'))}")
        print(f"  sign-ups disabled      : {s.get('disable_signup')}")
        print(f"  email auto-confirm     : {s.get('mailer_autoconfirm')}")
        print(f"  enabled providers      : {', '.join(enabled) or 'none'}")
    else:
        print(f"  settings: http {r.status_code}")

    print("== Auth users (service role; count only)")
    r = requests.get(f"{base}/auth/v1/admin/users?page=1&per_page=1000", timeout=15,
                     headers={"apikey": service, "Authorization": f"Bearer {service}"})
    if r.ok:
        users = (r.json() or {}).get("users") or []
        confirmed = sum(1 for u in users if u.get("email_confirmed_at"))
        print(f"  users={len(users)} confirmed={confirmed}")
    else:
        print(f"  users: http {r.status_code}")
    print("== What is already there (GET; no keys, no row contents)")
    hdr = {"apikey": service, "Authorization": f"Bearer {service}"}
    known = {"daniel", "coakley11", "user_coakley11", "ariel"}
    r = requests.get(f"{base}/rest/v1/suite_users?select=external_id,created_at&order=created_at", headers=hdr, timeout=15)
    for row in (r.json() if r.ok else []):
        ext = str(row.get("external_id") or "")
        label = ext if ext in known or ext in ("default",) else "other"
        print(f"  suite_users: username={label:16s} created={str(row.get('created_at') or '')[:10]}")
    r = requests.get(f"{base}/rest/v1/suite_app_current_state?select=app,updated_at,user_id", headers=hdr, timeout=15)
    for row in (r.json() if r.ok else []):
        app = str(row.get("app") or "")
        print(f"  app_state: app={app.split('__')[0] + ('__<workspace>' if '__' in app else ''):20s} updated={str(row.get('updated_at') or '')[:16]} has_user={bool(row.get('user_id'))}")
    r = requests.get(f"{base}/rest/v1/subscriptions?select=*&limit=5", headers=hdr, timeout=15)
    for row in (r.json() if r.ok else []):
        print(f"  subscriptions: columns={sorted(row)[:12]} status={row.get('status')}")
    r = requests.get(f"{base}/auth/v1/admin/users?page=1&per_page=50", headers=hdr, timeout=15)
    for u in ((r.json() or {}).get("users") or [] if r.ok else []):
        email = str(u.get("email") or "")
        masked = (email[:2] + "***@" + email.split("@")[-1]) if "@" in email else "-"
        print(f"  auth user: {masked:28s} created={str(u.get('created_at') or '')[:10]} last_sign_in={str(u.get('last_sign_in_at') or '')[:10]}")
    print("Nothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
