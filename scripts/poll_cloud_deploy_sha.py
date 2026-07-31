"""Poll Cloud until binding readiness (deploy pin marker + runtime git + implementation)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

TARGET_PIN = (sys.argv[1] if len(sys.argv) > 1 else "").strip()[:7]
URL = (
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    "?active_page=Live%20Draft%20Room&solo_delivery_diag=1&solo_component_diag=1"
)


def main() -> int:
    from p8_canary_build_gate import local_deploy_pin, poll_live_cloud_sha

    pin = TARGET_PIN or local_deploy_pin()
    for i in range(12):
        report = poll_live_cloud_sha(
            max_attempts=1,
            sleep_s=0,
            require_canary_impl=False,
            wait_for_binding_readiness=True,
        )
        ready = report.get("binding_readiness") or {}
        print(
            f"attempt={i} runtime={ready.get('runtime_git_head_short')} "
            f"marker={ready.get('marker_sha')} build={ready.get('marker_build')} ok={ready.get('ok')}",
            flush=True,
        )
        if report.get("ok") and ready.get("ok"):
            print(json.dumps(ready, indent=2))
            return 0
        time.sleep(20)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
