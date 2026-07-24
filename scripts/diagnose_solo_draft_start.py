"""Fresh-context Playwright diagnostic: Solo Live Draft start workflow only."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

OUT_DIR = ROOT / "data" / "solo_draft_start_diag"
OUT_JSON = OUT_DIR / "solo_draft_start_diagnostic.json"


def main() -> int:
    from solo_draft_start_harness import (
        DEFAULT_SETUP_URL,
        execute_solo_draft_start_workflow,
        run_fresh_context_start,
    )
    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    console_logs: list[dict[str, Any]] = []

    with sync_playwright() as p:
        from solo_draft_start_harness import BROWSER_LAUNCH_ARGS, VIEWPORT

        browser = p.chromium.launch(headless=True, args=BROWSER_LAUNCH_ARGS)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        page.on(
            "console",
            lambda msg: console_logs.append(
                {"type": msg.type, "text": msg.text[:800], "ts": time.time()}
            ),
        )
        report = execute_solo_draft_start_workflow(page, DEFAULT_SETUP_URL, navigate=True)
        report["draft_start_success"] = report.get("start_success")
        report["console_tail"] = console_logs[-50:]
        context.close()
        browser.close()

    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {"artifact": str(OUT_JSON), "draft_start_success": report.get("draft_start_success")},
            indent=2,
        )
    )
    return 0 if report.get("start_success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
