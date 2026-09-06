"""Browser-prove Guest Join route using durable two-process launcher.

Requires product Join route fix (8df3dfe). Does not redesign that fix.
Creates a room through host UI, joins from guest UI, asserts Shared lobby.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from local_tb_server_manager import (  # noqa: E402
    http_status,
    process_alive,
    start_host_guest,
    status_snapshot,
    stop_all,
)

OUT = ROOT / "data" / "tb_probe"
ROOM_DIR = ROOT / "data" / "draft_rooms"
REPORT = OUT / "join_route_browser_proof.json"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"

_CODE_DENY = frozenset({"SHARED", "DRAFTS", "PLAYER", "WAITING", "STATUS", "SELECT", "BUTTON", "TEAMSA", "TEAMSB"})


def wipe_workspace_live_draft(ws: str) -> None:
    p = ROOT / "data" / "workspaces" / ws / "baseball_user_state.json"
    if not p.is_file():
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    st = data.get("state") or {}
    for k in (
        "active_shared_draft_room_code",
        "live_draft_room",
        "live_draft_state",
        "draft_room_shared_meta",
        "draft_room_participant_membership",
        "draft_room_participant_state",
        "draft_room_participant_team",
        "draft_room_participant_id",
        "_live_draft_force_setup_after_delete",
        "_live_draft_deleting",
    ):
        st.pop(k, None)
    bws = st.get("baseball_workspace_state")
    if isinstance(bws, dict):
        bws.pop("live_draft", None)
        bws.pop("live_draft_room", None)
    pf = st.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Live Draft Room")
        if isinstance(block, dict):
            for k in ("live_draft_room", "live_draft_state", "active_shared_draft_room_code"):
                block.pop(k, None)
    data["state"] = st
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=25000)
    except Exception:
        return ""


def snap(page, name: str, report: dict) -> str:
    text = body(page)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    (OUT / f"{name}.txt").write_text(text[:9000], encoding="utf-8")
    report[f"{name}_snip"] = text[:450]
    return text


def extract_code(text: str) -> str:
    for pat in (
        r"Join code:\s*([A-Z0-9]{6})",
        r"Room Code[:\s]+`?([A-Z0-9]{6})",
        r"Room\s+([A-Z0-9]{6})\b",
        r"share this code[^A-Z0-9]*([A-Z0-9]{6})",
        r"Draft Room Code\s+\*\*([A-Z0-9]{6})\*\*",
    ):
        m = re.search(pat, text, re.I)
        if m:
            c = m.group(1).upper()
            if c not in _CODE_DENY:
                return c
    for mm in re.finditer(r"\b([A-Z0-9]{6})\b", text.upper()):
        tok = mm.group(1)
        if tok in _CODE_DENY:
            continue
        if any(ch.isdigit() for ch in tok) and any(ch.isalpha() for ch in tok):
            return tok
    return ""


def goto_live_draft(page, url: str, report: dict, label: str) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(5000)
    text = body(page)
    if "Draft Mode" in text or "Draft Setup" in text or "Waiting for Start" in text:
        report[f"{label}_nav"] = "query_ok"
        return text
    # Sidebar page radio / list
    for sel in (
        lambda: page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).click(timeout=6000),
        lambda: page.locator("label").filter(has_text=re.compile(r"Live Draft Room", re.I)).first.click(timeout=6000),
        lambda: page.get_by_text(re.compile(r"📡\s*Live Draft Room")).click(timeout=6000),
        lambda: page.get_by_text("Live Draft Room", exact=False).nth(1).click(timeout=6000),
    ):
        try:
            sel()
            page.wait_for_timeout(5000)
            text = body(page)
            if "Draft Mode" in text or "Draft Setup" in text or "Waiting for Start" in text or "Create Shared" in text:
                report[f"{label}_nav"] = "sidebar_ok"
                return text
        except Exception as exc:
            report[f"{label}_nav_try"] = f"{type(exc).__name__}:{exc}"[:160]
    report[f"{label}_nav"] = "failed"
    return text


def end_or_leave(page, report: dict, label: str) -> None:
    text = body(page)
    if "Waiting for Start" not in text and "incomplete" not in text.lower() and "Join code:" not in text:
        return
    for pat in (
        r"Leave This Room",
        r"Leave Room",
        r"End.?Delete Draft for Everyone",
        r"Back to Draft Setup",
    ):
        try:
            btn = page.get_by_role("button", name=re.compile(pat, re.I))
            if not btn.count():
                continue
            btn.first.click(timeout=6000)
            page.wait_for_timeout(2000)
            conf = page.get_by_role(
                "button", name=re.compile(r"Confirm End.?Delete|Leave This Room", re.I)
            )
            if conf.count():
                conf.first.click(timeout=6000)
                page.wait_for_timeout(4000)
            report[f"{label}_cleared"] = pat
            return
        except Exception as exc:
            report[f"{label}_clear_err"] = f"{type(exc).__name__}:{exc}"[:180]


def select_shared(page) -> bool:
    for lab in (
        r"Shared Multiplayer Draft Room",
        r"Shared Multiplayer",
        r"^Shared$",
    ):
        try:
            page.get_by_text(re.compile(lab, re.I)).first.click(timeout=5000)
            page.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    try:
        page.get_by_role("radio", name=re.compile(r"Shared", re.I)).click(timeout=5000)
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def click_create(page) -> bool:
    try:
        btns = page.get_by_role("button", name=re.compile(r"Create Shared Draft Room", re.I))
        for i in range(btns.count()):
            b = btns.nth(i)
            if b.is_enabled():
                b.click(timeout=15000)
                page.wait_for_timeout(3000)
                return True
        if btns.count():
            btns.first.click(timeout=15000, force=True)
            page.wait_for_timeout(3000)
            return True
    except Exception:
        return False
    return False


def wait_host_lobby(page, before_codes: set[str], timeout_s: float = 120.0) -> tuple[str, str]:
    deadline = time.time() + timeout_s
    code = ""
    text = ""
    while time.time() < deadline:
        text = body(page)
        code = extract_code(text)
        fresh = {p.stem.upper() for p in ROOM_DIR.glob("*.json")} - before_codes
        if fresh:
            code = sorted(fresh)[-1]
        if code and (
            "Waiting for Start" in text
            or "Join code:" in text
            or f"Room {code}" in text
            or (ROOM_DIR / f"{code}.json").is_file()
        ):
            if "incomplete" in text.lower() and not (ROOM_DIR / f"{code}.json").is_file():
                page.wait_for_timeout(3000)
                continue
            return code, text
        page.wait_for_timeout(3000)
    return code, text


def in_lobby(text: str, code: str) -> bool:
    if not code or code not in text:
        return False
    if "Waiting for Start" in text or "Join code:" in text or f"Room {code}" in text:
        return True
    if "Shared Draft Room Ready" in text:
        return True
    return False


def main() -> int:
    from playwright.sync_api import sync_playwright

    report: dict = {
        "verdict": "BLOCKED",
        "git_head": os.popen("git rev-parse HEAD").read().strip(),
        "product_fix_touched": False,
    }
    # Fresh state
    for f in ROOM_DIR.glob("*.json"):
        try:
            f.unlink()
        except Exception:
            pass
    wipe_workspace_live_draft("daniel")
    wipe_workspace_live_draft("guest")

    # Prefer existing stable servers; else start via manager.
    need_start = not (http_status(8511).get("ok") and http_status(8512).get("ok"))
    handles = None
    if need_start:
        handles = start_host_guest(out_dir=OUT / "server_manager", wait_ready_s=90.0)
        report["servers_started"] = True
    else:
        report["servers_started"] = False
        report["servers_reused"] = True

    before_codes = {p.stem.upper() for p in ROOM_DIR.glob("*.json")}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            host = browser.new_context().new_page()
            guest = browser.new_context().new_page()

            goto_live_draft(host, HOST_URL, report, "host")
            end_or_leave(host, report, "host")
            snap(host, "JP01_host_setup", report)
            report["host_shared_ok"] = select_shared(host)
            host.wait_for_timeout(2500)
            snap(host, "JP02_host_shared", report)
            report["create_clicked"] = click_create(host)
            code, host_text = wait_host_lobby(host, before_codes, timeout_s=130.0)
            snap(host, "JP03_host_after_create", report)
            report["code"] = code
            report["room_file"] = bool(code and (ROOM_DIR / f"{code}.json").is_file())
            report["host_in_lobby"] = in_lobby(host_text, code) or (
                bool(code)
                and report["room_file"]
                and ("Waiting for Start" in host_text or "Join code:" in host_text)
            )
            report["host_create_ui"] = bool(report["create_clicked"] and report["room_file"] and report["host_in_lobby"])

            goto_live_draft(guest, GUEST_URL, report, "guest")
            end_or_leave(guest, report, "guest")
            snap(guest, "JP04_guest_setup", report)
            report["guest_shared_ok"] = select_shared(guest)
            guest.wait_for_timeout(2500)
            gtext = snap(guest, "JP05_guest_shared", report)
            report["guest_join_ui"] = "Join Shared Draft Room" in gtext
            report["join_attempted"] = False

            if code and report["guest_join_ui"]:
                report["join_attempted"] = True
                guest.get_by_placeholder("ABC123").fill(code, timeout=8000)
                guest.wait_for_timeout(3500)
                snap(guest, "JP06_guest_filled", report)
                btn = guest.get_by_role("button", name=re.compile(r"^Join( Room| as )", re.I)).first
                report["join_enabled"] = btn.is_enabled()
                btn.click(timeout=10000)
                report["join_click"] = True
                guest.wait_for_timeout(16000)
                after = snap(guest, "JP07_guest_after_join", report)
                report["guest_in_lobby"] = in_lobby(after, code)
                report["guest_still_setup"] = (
                    "Join Shared Draft Room" in after and not report["guest_in_lobby"]
                )
                report["guest_has_code"] = code in after
                report["guest_team_b"] = "Team B" in after

                # Refresh guest once
                guest.reload(wait_until="domcontentloaded", timeout=120000)
                guest.wait_for_timeout(10000)
                goto_live_draft(guest, GUEST_URL, report, "guest_refresh")
                refreshed = snap(guest, "JP08_guest_refresh", report)
                report["guest_refresh_in_lobby"] = in_lobby(refreshed, code)

            if code and (ROOM_DIR / f"{code}.json").is_file():
                raw = json.loads((ROOM_DIR / f"{code}.json").read_text(encoding="utf-8"))
                parts = raw.get("participants") or {}
                report["participants"] = parts
                report["guest_membership"] = "workspace:guest" in parts
                report["host_membership"] = "workspace:daniel" in parts
                report["revision"] = raw.get("revision")
                report["participant_ids"] = list(parts.keys()) if isinstance(parts, dict) else []

            host_after = snap(host, "JP09_host_after_guest", report)
            report["host_sees_guest_hint"] = (
                "guest" in host_after.lower() or "Team B" in host_after or "2 /" in host_after
            )
            report["server_status"] = {
                "8511": http_status(8511),
                "8512": http_status(8512),
            }

            # Offline guest disk lifecycle
            try:
                gstate = json.loads(
                    (ROOT / "data" / "workspaces" / "guest" / "baseball_user_state.json").read_text(
                        encoding="utf-8"
                    )
                ).get("state") or {}
                from live_draft_completion import resolve_live_draft_lifecycle

                report["guest_disk_code"] = gstate.get("active_shared_draft_room_code")
                report["guest_disk_lifecycle"] = resolve_live_draft_lifecycle(gstate)
                report["guest_route_contract"] = gstate.get("_shared_room_join_route_contract")
            except Exception as exc:
                report["guest_disk_err"] = f"{type(exc).__name__}:{exc}"[:200]

            if (
                report.get("host_create_ui")
                and report.get("join_attempted")
                and report.get("guest_membership")
                and report.get("guest_in_lobby")
            ):
                report["verdict"] = "GUEST_JOIN_ROUTE_BROWSER_PASS"
            elif report.get("join_attempted") and report.get("guest_membership") and not report.get(
                "guest_in_lobby"
            ):
                report["verdict"] = "GUEST_MEMBERSHIP_CREATED_ROUTE_NOT_ENTERED"
            else:
                report["verdict"] = "LOCAL_SHARED_DRAFT_BLOCKED"

            browser.close()
    finally:
        # Keep servers up on Join pass for handoff continuation; stop only on hard fail
        # if we started them and join never started.
        if handles and report.get("verdict") not in (
            "GUEST_JOIN_ROUTE_BROWSER_PASS",
            "GUEST_MEMBERSHIP_CREATED_ROUTE_NOT_ENTERED",
        ):
            # still leave running for debugging unless processes already dead
            pass

    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "GUEST_JOIN_ROUTE_BROWSER_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
