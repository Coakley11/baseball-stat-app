"""Poll until live Cloud #solo-deploy-build SHA equals target exactly."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

TARGET = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()[:7]
if not TARGET:
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    TARGET = line.split("#", 1)[0].strip().lower()[:7]

URL = (
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    "?active_page=Live%20Draft%20Room&solo_component_diag=1"
)
OUT = ROOT / "data" / "cloud_deploy_exact_sha_wait.json"


def main() -> int:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake
    from verify_cloud_deploy_playwright import scrape_deploy

    deadline = time.time() + 900
    attempts: list[dict] = []
    ready = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        while time.time() < deadline:
            row: dict = {"ts": time.time()}
            try:
                goto_and_wake(page, URL, timeout_s=240)
                page.wait_for_timeout(8000)
                probe = scrape_deploy(page)
                sha = str(probe.get("sha") or "").strip().lower()[:7]
                row["sha"] = sha
                row["build"] = probe.get("build") or ""
                attempts.append(row)
                print(json.dumps({"attempt": len(attempts), "sha": sha, "build": row["build"]}))
                if sha == TARGET:
                    ready = True
                    break
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}:{exc}"
                attempts.append(row)
                print(json.dumps(row))
            time.sleep(25)
        browser.close()

    payload = {"target": TARGET, "ready": ready, "attempts": attempts}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"ready": ready, "target": TARGET, "artifact": str(OUT)}))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
