"""Guard for QA-only tooling: load .streamlit/secrets.toml only if it is marked as the QA project.

Required in the file:
    [qa]
    is_qa_project = true
    project_ref = "<the Reference ID shown in the QA project's Settings -> General>"
and [suite_activity] supabase_url must be https://<project_ref>.supabase.co, with both keys set and
suite_auth_enabled = true. Nothing here prints a key or the URL.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ROOT / ".streamlit" / "secrets.toml"


def load_qa_config(path: Path = SECRETS) -> tuple[dict, list[str]]:
    """(suite_activity block, problems). Problems empty means the file targets the marked QA project."""
    if not path.is_file():
        return {}, [f"no secrets file at {path}"]
    try:
        data = tomllib.load(open(path, "rb"))
    except Exception as exc:  # noqa: BLE001
        return {}, [f"secrets file does not parse ({type(exc).__name__})"]
    qa = data.get("qa") or {}
    sa = data.get("suite_activity") or {}
    problems: list[str] = []
    if qa.get("is_qa_project") is not True:
        problems.append("[qa] is_qa_project = true is missing")
    ref = str(qa.get("project_ref") or "").strip().lower()
    if not ref:
        problems.append("[qa] project_ref is missing")
    host = (urlparse(str(sa.get("supabase_url") or "")).hostname or "").lower()
    if ref and host != f"{ref}.supabase.co":
        problems.append("supabase_url does not belong to [qa] project_ref")
    for key in ("supabase_url", "supabase_key", "supabase_anon_key"):
        if not str(sa.get(key) or "").strip():
            problems.append(f"[suite_activity] {key} is empty")
    for key in ("supabase_key", "supabase_anon_key"):
        value = str(sa.get(key) or "")
        if value and value.count(".") != 2:
            problems.append(f"[suite_activity] {key} is not a legacy JWT key (use the Legacy API keys tab)")
    if sa.get("suite_auth_enabled") is not True:
        problems.append("[suite_activity] suite_auth_enabled = true is missing")
    return sa, problems


def main() -> int:
    _sa, problems = load_qa_config()
    if problems:
        print("QA guard: NOT OK")
        for p in problems:
            print("  -", p)
        return 2
    print("QA guard: OK (marked QA project; URL matches project_ref; keys present; sign-in on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
