"""Fail fast if registration hooks do not fire locally (Case A path)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from live_draft_streamlit_registration_hooks import run_local_case_a_hook_self_test


def main() -> int:
    result = run_local_case_a_hook_self_test()
    out = ROOT / "data" / "registration_hook_case_a_self_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": result.get("ok"), "artifact": str(out)}, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
