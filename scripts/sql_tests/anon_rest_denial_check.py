"""Read-only check that the public anon key can no longer reach the three contained suite tables.

Run:  python -I scripts/sql_tests/anon_rest_denial_check.py
It asks for the project URL and the anon / publishable key (the key is not echoed, and is never
written to disk, shell history or the environment). It refuses a service / secret key.

Output is status and error codes only. No credential, token or returned record is printed;
response bodies are parsed for their error code and then discarded.
"""

from __future__ import annotations

import base64
import getpass
import json
import sys
import urllib.error
import urllib.request

TABLES = {  # table -> one harmless column to select (suite_user_settings has no id column)
    "suite_users": "id",
    "suite_saved_items": "id",
    "suite_user_settings": "user_id",
}


def key_kind(key: str) -> str:
    if key.startswith("sb_publishable_"):
        return "publishable"
    if key.startswith("sb_secret_"):
        return "secret"
    parts = key.split(".")
    if len(parts) == 3:
        try:
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
            return "anon" if claims.get("role") == "anon" else f"jwt:{claims.get('role')}"
        except ValueError:
            return "unknown"
    return "unknown"


def request(url: str, key: str, kind: str) -> tuple[int, str, str]:
    """(HTTP status, error code, row note). Never returns body content."""
    headers = {"apikey": key, "Accept": "application/json"}
    if kind == "anon":  # legacy anon JWT goes in both headers; a publishable key only in apikey
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status, body = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    code, rows = "", ""
    try:
        parsed = json.loads(body or b"null")
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        code = str(parsed.get("code") or parsed.get("error_code") or parsed.get("error") or "")[:40]
        if not code and isinstance(parsed.get("message"), str):
            code = "message:" + parsed["message"][:60]
    elif isinstance(parsed, list):
        rows = "empty array" if not parsed else "NON-EMPTY array (not printed)"
    del body, parsed
    return status, code, rows


def main() -> int:
    base = input("Supabase project URL (https://<ref>.supabase.co): ").strip().rstrip("/")
    if not base.startswith("https://"):
        print("Refusing: the URL must start with https://")
        return 2
    key = getpass.getpass("Anon / publishable key (not echoed): ").strip()
    kind = key_kind(key)
    if kind not in ("anon", "publishable"):
        print(f"Refusing: this is not the public anon key (detected: {kind}). Nothing was sent.")
        return 2
    print(f"Key type: {kind}")

    # Control: a public Auth endpoint that accepts any valid project key and returns no user data.
    # If this fails, a table "denial" below would only mean the key was rejected.
    status, code, _ = request(f"{base}/auth/v1/settings", key, kind)
    if status != 200:
        print(f"CONTROL FAILED: /auth/v1/settings returned HTTP {status} {code}. The key or URL is wrong; "
              "table results would not prove anything. Stopping.")
        return 2
    print("Control: key accepted by the project (HTTP 200 from /auth/v1/settings)")

    failures = 0
    for table, column in TABLES.items():
        status, code, rows = request(f"{base}/rest/v1/{table}?select={column}&limit=1", key, kind)
        denied = status in (401, 403) and code == "42501"
        verdict = "PASS (permission denied)" if denied else "INVESTIGATE"
        if not denied:
            failures += 1
        detail = f" code={code}" if code else ""
        detail += f" body={rows}" if rows else ""
        print(f"{table:22} HTTP {status}{detail}  -> {verdict}")
    key = ""
    print("All three denied." if failures == 0 else f"{failures} table(s) need investigation (see above).")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
