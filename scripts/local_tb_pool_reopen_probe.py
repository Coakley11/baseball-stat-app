"""Reopen existing in_progress Shared room and sample pool handoff diagnostics."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local_tb_server_manager import http_status  # noqa: E402

OUT = ROOT / "data" / "tb_probe"
DIAG = OUT / "pool_live_diag.jsonl"
REPORT = OUT / "pool_reopen_probe.json"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=25000)
    except Exception:
        return ""


def sample(page, label: str) -> dict:
    text = body(page)
    has_add = False
    try:
        has_add = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count() > 0
    except Exception:
        pass
    return {
        "client": label,
        "ts": time.time(),
        "has_add": has_add,
        "building": bool(re.search(r"still building the player pool", text, re.I)),
        "no_players": "No players left in the pool" in text,
        "rebuild_err": (
            m.group(1).strip()
            if (m := re.search(r"Local pool rebuild:\s*`([^`]+)`", text))
            else None
        ),
        "last_rerun": (
            m.group(1) if (m := re.search(r"last_rerun=`?([^\s)`]+)", text)) else None
        ),
        "status": (m.group(0) if (m := re.search(r"Draft Status:[^\n]+", text)) else None),
        "in_progress": bool(re.search(r"In Progress|0 / \d+ picks", text, re.I)),
    }


def main() -> int:
    from playwright.sync_api import sync_playwright

    if DIAG.is_file():
        DIAG.unlink()
    report: dict = {
        "http": {"host": http_status(8511), "guest": http_status(8512)},
        "timeline": [],
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host = browser.new_context().new_page()
        guest = browser.new_context().new_page()
        host.goto(HOST_URL, wait_until="domcontentloaded", timeout=120000)
        guest.goto(GUEST_URL, wait_until="domcontentloaded", timeout=120000)
        for _ in range(30):
            if len(body(host)) > 100 and len(body(guest)) > 100:
                break
            host.wait_for_timeout(2000)
        try:
            host.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=1500)
        except Exception:
            pass
        try:
            guest.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=1500)
        except Exception:
            pass
        # Navigate to Live Draft if needed
        for page in (host, guest):
            if "IY70DR" not in body(page) and "In Progress" not in body(page):
                try:
                    page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).click(timeout=8000)
                    page.wait_for_timeout(4000)
                except Exception:
                    pass
        report["timeline"].append({"phase": "t0", "host": sample(host, "host"), "guest": sample(guest, "guest")})
        (OUT / "RO01_host.txt").write_text(body(host)[:12000], encoding="utf-8")
        (OUT / "RO02_guest.txt").write_text(body(guest)[:12000], encoding="utf-8")
        t0 = time.time()
        while time.time() - t0 < 180:
            hs = sample(host, "host")
            gs = sample(guest, "guest")
            report["timeline"].append({"elapsed": round(time.time() - t0, 1), "host": hs, "guest": gs})
            if hs.get("has_add") and gs.get("has_add"):
                break
            host.wait_for_timeout(8000)
        (OUT / "RO01_host.txt").write_text(body(host)[:14000], encoding="utf-8")
        (OUT / "RO02_guest.txt").write_text(body(guest)[:14000], encoding="utf-8")
        report["host_final"] = sample(host, "host")
        report["guest_final"] = sample(guest, "guest")
        report["diag"] = DIAG.read_text(encoding="utf-8").splitlines() if DIAG.is_file() else []
        browser.close()
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "host": report["host_final"],
                "guest": report["guest_final"],
                "diag_n": len(report["diag"]),
                "diag_tail": report["diag"][-12:],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
