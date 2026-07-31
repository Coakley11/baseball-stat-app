"""Poll Streamlit Cloud until binding deploy readiness (Playwright — urllib 303 unsafe)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

URL = (
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    "?active_page=Live%20Draft%20Room&solo_component_diag=1"
)


def main() -> int:
    from p8_canary_build_gate import local_deploy_pin, poll_live_cloud_sha

    target_pin = (sys.argv[1] if len(sys.argv) > 1 else local_deploy_pin()).strip()[:7]
    max_attempts = int(sys.argv[2]) if len(sys.argv) > 2 else 45
    print(
        json.dumps(
            {
                "mode": "playwright_binding_readiness",
                "target_deploy_pin": target_pin,
                "note": "urllib poll disabled — Streamlit Cloud returns 303 redirect loops",
            }
        ),
        flush=True,
    )
    report = poll_live_cloud_sha(
        max_attempts=max_attempts,
        sleep_s=20.0,
        require_canary_impl=False,
        wait_for_binding_readiness=True,
    )
    ready = report.get("binding_readiness") or {}
    print(json.dumps({"ok": report.get("ok"), "readiness": ready}, indent=2), flush=True)
    if report.get("ok") and ready.get("ok"):
        print("DEPLOY_READY", flush=True)
        return 0
    print("DEPLOY_TIMEOUT", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
