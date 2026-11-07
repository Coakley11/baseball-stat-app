"""Read-only screenshots of the seeded preview: navigates and scrolls, never clicks draft actions.

    python ci/shoot.py <base_url> <out_dir>

Writes <out_dir>/<view>_<desktop|phone>.png (viewport) and <view>_<device>_tall.png (a taller
viewport, since Streamlit scrolls inside its own container), plus report.md / report.json.
Exit 1 if any view never became ready or showed a Python traceback.
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

# (view, query, text that proves the view rendered, open the sidebar first, texts to click (view
# controls only: tabs and expanders), optional = absent on branches without that feature)
VIEWS = [
    ("solo_draft", "mode=solo", "On the clock", False, (), False),
    ("shared_draft_host", "mode=host", "On the clock", False, (), False),
    ("draft_strategy_page", "mode=solo&page=" + quote("Draft Strategy Assistant"), "Strateg", False, (), False),
    ("sidebar_navigation", "mode=solo", "Account & Workspace", True, (), False),
    ("solo_strategy_panel_open", "mode=solo", "Draft Strategy ·", False, ("Draft Strategy ·",), True),
    ("shared_strategy_panel_open", "mode=host", "Draft Strategy ·", False, ("Draft Strategy ·",), True),
    ("simulator_strategy_panel", "mode=solo&page=" + quote("Draft Room Simulator"), "Draft Room Simulator", False,
     ("Board", "Draft Strategy ·"), True),
]
DEVICES = [("desktop", 1366, 900, 2400), ("phone", 390, 844, 2600)]
CHECKS = ("On the clock", "Up next", "Your next pick", "Recent picks", "Draft strategy", "Team rosters")
BAD = ("Traceback (most recent call last)", "StreamlitAPIException", "ModuleNotFoundError")


def wait_for(page, needle, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if needle in page.inner_text("body"):
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


results = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for view, query, needle, sidebar, clicks, optional in VIEWS:
        for device, width, height, tall in DEVICES:
            ctx = browser.new_context(viewport={"width": width, "height": height},
                                      is_mobile=device == "phone", has_touch=device == "phone")
            page = ctx.new_page()
            page.goto(f"{base}/?{query}", wait_until="domcontentloaded", timeout=180000)
            ready = wait_for(page, needle)
            time.sleep(8)  # let the last rerun paint
            for text in clicks:
                try:
                    page.get_by_text(text).first.click(timeout=8000)
                    time.sleep(4)
                except Exception:
                    pass
            if sidebar:
                try:
                    if device == "phone":
                        page.locator('[data-testid="stExpandSidebarButton"], '
                                     '[data-testid="stSidebarCollapsedControl"] button').first.click(timeout=5000)
                        time.sleep(2)
                    page.get_by_text("Account & Workspace").first.click(timeout=5000)
                    time.sleep(3)
                except Exception:
                    pass
            body = page.inner_text("body")
            page.screenshot(path=str(out / f"{view}_{device}.png"))
            if sidebar:
                try:
                    page.locator('[data-testid="stSidebar"]').first.screenshot(
                        path=str(out / f"{view}_{device}_panel.png"), timeout=10000)
                except Exception:
                    pass
            else:
                page.set_viewport_size({"width": width, "height": tall})
                time.sleep(4)
                page.screenshot(path=str(out / f"{view}_{device}_tall.png"))
            row = {"view": view, "device": device, "ready": ready, "optional": optional,
                   "errors": [b for b in BAD if b in body],
                   "landmarks": {c: c in body for c in CHECKS}}
            results.append(row)
            print(json.dumps(row))
            ctx.close()
    browser.close()

lines = ["| View | Device | Ready | Errors | " + " | ".join(CHECKS) + " |",
         "|---|---|---|---|" + "---|" * len(CHECKS)]
for r in results:
    marks = " | ".join("yes" if r["landmarks"][c] else "-" for c in CHECKS)
    lines.append(f"| {r['view']} | {r['device']} | {'yes' if r['ready'] else 'NO'} | "
                 f"{', '.join(r['errors']) or '-'} | {marks} |")
(out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
(out / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
sys.exit(0 if all((r["ready"] or r["optional"]) and not r["errors"] for r in results) else 1)
