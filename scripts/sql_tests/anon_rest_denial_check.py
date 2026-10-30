"""Read-only check that the public anon key cannot reach the contained suite and shared-Baseball tables.

Run (Windows, after copying the project's anon public key):
    python -I scripts/sql_tests/anon_rest_denial_check.py
The key is read straight from the clipboard, so nothing has to be pasted into a hidden prompt (in a
Windows console, Ctrl+V does not paste into one: it arrives as a ^V control character). The project
URL comes from the legacy anon key's `ref` claim; pass --url for a publishable key or to override.
--prompt asks for the key instead (not echoed; paste with right-click).

The key is never printed, logged, or written to disk, shell history or the environment. A service-role
or secret key is refused before anything is sent. Output is status and error codes only; response
bodies are parsed for their error code and then discarded.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import re
import sys
import time
import urllib.error
import urllib.request

TABLES = {  # table -> one harmless column to select (suite_user_settings has no id column)
    "suite_users": "id",
    "suite_saved_items": "id",
    "suite_user_settings": "user_id",
    "baseball_shared_draft_rooms": "room_code",  # contained by baseball_shared_containment_stepB_DRAFT.sql
    "baseball_shared_leagues": "league_id",
}
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")
_PROJECT_URL = re.compile(r"https://([a-z0-9]{20})\.supabase\.co")


def normalize_key(raw: str) -> str:
    """Remove what copying and pasting adds around a key; keys contain none of these characters."""
    key = raw.replace("\x1b[200~", "").replace("\x1b[201~", "")  # bracketed-paste markers
    key = "".join(key.split())  # spaces, tabs and line breaks anywhere
    key = key.strip("\"'")
    if key.lower().startswith("bearer"):
        key = key[len("bearer"):]
    return key


def jwt_claims(key: str) -> dict | None:
    parts = key.split(".")
    if len(parts) != 3 or not all(_BASE64URL.fullmatch(p) for p in parts):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return None
    return claims if isinstance(claims, dict) else None


def key_kind(key: str) -> str:
    if key.startswith("sb_publishable_"):
        return "publishable"
    if key.startswith("sb_secret_"):
        return "secret"
    claims = jwt_claims(key)
    if claims is None:
        return "unknown"
    return "anon" if claims.get("role") == "anon" else f"jwt:{claims.get('role')}"


def describe_shape(raw: str) -> str:
    """Why a value is not a key, without revealing any of it."""
    key = normalize_key(raw)
    if not key:
        return "the value is empty (nothing was copied or pasted)"
    if any(ord(c) < 32 or ord(c) == 127 for c in key):
        return ("it contains control characters (Ctrl+V does not paste into a hidden prompt in a Windows "
                "console; copy the key and run without --prompt)")
    half = len(key) // 2
    if len(key) % 2 == 0 and key[:half] == key[half:] and key_kind(key[:half]) != "unknown":
        return "it is the key twice (pasted twice)"
    if key.startswith("eyJ"):
        return f"it starts like a JWT but has {key.count('.') + 1} dot-separated parts instead of 3"
    return f"it is {len(key)} characters and is neither a JWT nor an sb_ key"


def read_clipboard() -> str:
    if sys.platform != "win32":
        raise OSError("clipboard reading is implemented for Windows only; use --prompt")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    cf_unicodetext = 13
    for _ in range(20):  # another program may hold the clipboard for a moment
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("the clipboard is busy; try again")
    try:
        handle = user32.GetClipboardData(cf_unicodetext)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", help="https://<ref>.supabase.co (default: from the anon key's ref claim)")
    parser.add_argument("--prompt", action="store_true", help="type or right-click paste the key instead")
    args = parser.parse_args(argv)

    try:
        raw = getpass.getpass("Anon / publishable key (not echoed): ") if args.prompt else read_clipboard()
    except OSError as exc:
        print(f"Could not read the key: {exc}. Nothing was sent.")
        return 2
    key = normalize_key(raw)
    kind = key_kind(key)
    if kind == "secret" or kind.startswith("jwt:"):
        print(f"Refusing: this is not the public anon key (detected: {kind}). Nothing was sent.")
        return 2
    if kind == "unknown":
        print(f"Refusing: this is not a Supabase API key, because {describe_shape(raw)}. Nothing was sent.")
        return 2
    raw = ""

    ref = str(jwt_claims(key).get("ref") or "") if kind == "anon" else ""
    base = (args.url or "").strip().rstrip("/")
    if not base:
        if not re.fullmatch(r"[a-z0-9]{20}", ref):
            print("Refusing: the key carries no project ref; pass --url https://<ref>.supabase.co")
            return 2
        base = f"https://{ref}.supabase.co"
    match = _PROJECT_URL.fullmatch(base)
    if not match:
        print("Refusing: the URL must be https://<20-character ref>.supabase.co")
        return 2
    if ref and match.group(1) != ref:
        print("Refusing: the key belongs to a different project than --url. Nothing was sent.")
        return 2
    print(f"Key type: {kind}; project: {match.group(1)}")

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
        print(f"{table:28} HTTP {status}{detail}  -> {verdict}")
    key = ""
    print(f"All {len(TABLES)} denied." if failures == 0 else f"{failures} table(s) need investigation (see above).")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
