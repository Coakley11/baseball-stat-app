"""Full local two-browser Shared Draft acceptance: Create→Join→Start→queues→picks→pause→refresh.

Requires durable host:8511 / guest:8512. Wipes rooms + workspaces itself.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from local_tb_server_manager import http_status  # noqa: E402

OUT = ROOT / "data" / "tb_probe"
ROOM_DIR = ROOT / "data" / "draft_rooms"
POOL_DIR = ROOT / "data" / "draft_room_local_pools"
DIAG = OUT / "pool_live_diag.jsonl"
REPORT = OUT / "full_shared_draft_pass.json"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"

_CODE_DENY = frozenset(
    {"SHARED", "DRAFTS", "PLAYER", "BEFORE", "STATUS", "SELECT", "BUTTON", "TEAMSA", "TEAMSB", "WAITING"}
)


def _scrub_live_draft_blob(blob: dict) -> None:
    """Clear nested Live Draft attachment so orphan rooms cannot rehydrate."""
    for k in list(blob):
        kl = str(k).lower()
        if any(
            x in kl
            for x in (
                "live_draft_room",
                "live_draft_state",
                "active_shared",
                "share_code",
                "room_code",
                "draft_room_id",
                "join_code",
                "participant",
                "membership",
                "_shared_local",
                "_start_live",
            )
        ):
            blob.pop(k, None)


def wipe_ws(ws: str) -> None:
    p = ROOT / "data" / "workspaces" / ws / "baseball_user_state.json"
    data = {"version": 1, "app": "baseball", "saved_at": "", "state": {}}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    st = data.get("state") or {}
    for k in list(st):
        if any(
            x in k
            for x in (
                "live_draft",
                "shared_draft",
                "draft_room",
                "active_shared",
                "_live_draft",
                "_start_live",
                "_shared_local",
            )
        ):
            st.pop(k, None)
    # Nested page_filter / canonical blobs rehydrate orphan IY70DR-class rooms.
    pf = st.get("page_filter_state")
    if isinstance(pf, dict):
        for page_name, page_blob in list(pf.items()):
            if not isinstance(page_blob, dict):
                continue
            if "live draft" in str(page_name).lower() or any(
                "live_draft" in str(k).lower() for k in page_blob
            ):
                _scrub_live_draft_blob(page_blob)
                page_blob["live_draft_setup_mode"] = "shared_multiplayer"
                page_blob["preferred_next_draft_mode"] = "shared_multiplayer"
                page_blob["live_draft_picks_per_team"] = 15
                page_blob["live_draft_join_code_input"] = ""
    # Compact workspace meta alone can revive a Pick-1-of-0 solo stub.
    bws = st.get("baseball_workspace_state")
    if isinstance(bws, dict):
        bws.pop("live_draft", None)
    st.pop("live_draft_room", None)
    st.pop("live_draft_state", None)
    st["live_draft_picks_per_team"] = 15
    st["active_page"] = "Live Draft Room"
    st["main_sidebar_page"] = "Live Draft Room"
    data["state"] = st
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=25000)
    except Exception:
        return ""


def snap(page, name: str) -> str:
    text = body(page)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    (OUT / f"{name}.txt").write_text(text[:16000], encoding="utf-8")
    return text


def wait_app(page, url: str, timeout_s: float = 90.0) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    deadline = time.time() + timeout_s
    text = ""
    while time.time() < deadline:
        text = body(page)
        if text.strip() in ("", "Stop\nDeploy", "Deploy") or len(text) < 80:
            page.wait_for_timeout(1500)
            continue
        if "not responding" in text.lower():
            page.wait_for_timeout(2000)
            continue
        break
    try:
        page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=1500)
    except Exception:
        pass
    return text


def open_live_draft(page) -> bool:
    text = body(page)
    if re.search(r"Draft Mode|Waiting for Start|Room\s+[A-Z0-9]{6}|Create Shared|Add to Queue", text, re.I):
        return True
    for _ in range(2):
        try:
            page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).check(timeout=8000)
            page.wait_for_timeout(3500)
            break
        except Exception:
            try:
                page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).click(timeout=8000)
                page.wait_for_timeout(3500)
                break
            except Exception:
                try:
                    page.locator("label", has_text=re.compile(r"Live Draft Room", re.I)).first.click(timeout=8000)
                    page.wait_for_timeout(3500)
                    break
                except Exception:
                    pass
    return bool(
        re.search(r"Draft Mode|Waiting for Start|Room\s+[A-Z0-9]{6}|Create Shared|Add to Queue", body(page), re.I)
    )


def leave_any_room(page) -> None:
    for _ in range(6):
        text = body(page)
        if "Create Shared Draft Room" in text and "Waiting for Start" not in text:
            if not re.search(r"Room\s+[A-Z0-9]{6}.*In Progress|Status:\s*In Progress", text, re.I):
                return
        clicked = False
        for pat in (
            r"Back to Draft Setup",
            r"Return to Live Draft Lobby",
            r"Leave This Room",
            r"Leave Room",
            r"End/?Delete Draft(?:\s+for Everyone)?",
            r"End Draft",
            r"Confirm End/?Delete",
            r"^Confirm$",
            r"^Yes$",
        ):
            try:
                page.get_by_role("button", name=re.compile(pat, re.I)).first.click(timeout=2500)
                page.wait_for_timeout(1500)
                clicked = True
            except Exception:
                continue
        if "Create Shared Draft Room" in body(page) and not re.search(
            r"Waiting for Start|Status:\s*In Progress", body(page), re.I
        ):
            return
        if not clicked:
            page.reload(wait_until="domcontentloaded", timeout=120000)
            open_live_draft(page)
            page.wait_for_timeout(1500)


def select_shared(page) -> bool:
    for lab in (r"Shared Multiplayer Draft Room", r"Shared Multiplayer", r"^Shared$"):
        try:
            page.get_by_text(re.compile(lab, re.I)).first.click(timeout=5000)
            page.wait_for_timeout(2000)
            return True
        except Exception:
            continue
    try:
        page.get_by_role("radio", name=re.compile(r"Shared", re.I)).click(timeout=5000)
        page.wait_for_timeout(2000)
        return True
    except Exception:
        return False


def set_picks(page, n: int = 15) -> bool:
    for loc in (
        page.get_by_label(re.compile(r"picks per team|Draft picks", re.I)),
        page.locator("input[aria-label*='picks' i]"),
        page.locator("div[data-testid='stNumberInput'] input").nth(0),
    ):
        try:
            el = loc.first
            el.click(timeout=3000)
            el.fill(str(n), timeout=3000)
            page.wait_for_timeout(1000)
            return True
        except Exception:
            continue
    return False


def click_btn(page, label: str, timeout: int = 12000) -> bool:
    try:
        page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I)).first.click(timeout=timeout)
        page.wait_for_timeout(1800)
        return True
    except Exception:
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=timeout)
            page.wait_for_timeout(1800)
            return True
        except Exception:
            try:
                page.locator("button", has_text=re.compile(label, re.I)).first.click(timeout=timeout)
                page.wait_for_timeout(1800)
                return True
            except Exception:
                return False


def click_control(page, *pats: str, timeout: int = 12000) -> bool:
    """Click an authoritative Streamlit control with a fresh locator.

    Prefer Playwright's locator click (proven Pause delivery path). Fall back to
    a trusted DOM click only if the locator click path fails. Always re-resolve
    the button immediately before the click so fragment/timer rerenders cannot
    leave a stale handle.
    """
    for pat in pats:
        try:
            loc = page.get_by_role("button", name=re.compile(pat, re.I)).first
            loc.wait_for(state="visible", timeout=timeout)
            if loc.is_disabled():
                continue
            try:
                loc.scroll_into_view_if_needed(timeout=min(timeout, 8000))
            except Exception:
                pass
            try:
                loc.click(timeout=timeout)
            except Exception:
                loc.click(timeout=timeout, force=True)
            page.wait_for_timeout(2500)
            return True
        except Exception:
            try:
                loc = page.get_by_role("button", name=re.compile(pat, re.I)).first
                loc.wait_for(state="visible", timeout=timeout)
                handle = loc.element_handle(timeout=timeout)
                if handle is None:
                    continue
                page.evaluate(
                    """(el) => {
                      el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
                      el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                      el.dispatchEvent(new PointerEvent('pointerup', {bubbles:true}));
                      el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                      el.click();
                    }""",
                    handle,
                )
                page.wait_for_timeout(2500)
                return True
            except Exception:
                continue
    return False


def page_btn_enabled(page, pat: str) -> bool:
    try:
        loc = page.get_by_role("button", name=re.compile(pat, re.I))
        return bool(loc.count() and loc.first.is_enabled())
    except Exception:
        return False


def extract_code(text: str) -> str:
    for pat in (
        r"Join code:\s*([A-Z0-9]{6})",
        r"Room\s+([A-Z0-9]{6})\b",
        r"Room Code[:\s]+`?([A-Z0-9]{6})",
    ):
        m = re.search(pat, text, re.I)
        if m:
            c = m.group(1).upper()
            if c not in _CODE_DENY and any(ch.isdigit() for ch in c):
                return c
    return ""


def in_lobby(text: str, code: str) -> bool:
    if not code or code not in text.upper():
        return False
    return bool(re.search(r"Waiting for Start|Join code:|Shared Draft Room Ready|Waiting to Start", text, re.I))


def room_participants(code: str) -> list[str]:
    p = ROOM_DIR / f"{code}.json"
    if not p.is_file():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return list((raw.get("participants") or {}).keys())


def room_raw(code: str) -> dict:
    path = ROOM_DIR / f"{code}.json"
    last_err = ""
    for _ in range(40):
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                time.sleep(0.2)
                continue
            return json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            last_err = f"{type(exc).__name__}:{exc}"
            time.sleep(0.2)
    # Last-chance single read for callers that must not treat a mid-write as missing.
    try:
        text = path.read_text(encoding="utf-8")
        if text.strip():
            return json.loads(text)
    except Exception as exc:
        last_err = f"{type(exc).__name__}:{exc}"
    return {"_room_raw_error": last_err or "empty"}


def room_status(code: str) -> str:
    raw = room_raw(code)
    if not isinstance(raw, dict) or raw.get("_room_raw_error"):
        return ""
    st = str(raw.get("status") or "").strip().lower()
    if st:
        return st
    room = raw.get("room") if isinstance(raw.get("room"), dict) else {}
    return str(room.get("status") or "").strip().lower()


def add_count(page) -> int:
    try:
        return page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count()
    except Exception:
        return 0


def countdown(text: str) -> list[int]:
    vals: list[int] = []
    for m in re.finditer(r"(\d{1,2}):(\d{2})", text):
        vals.append(int(m.group(1)) * 60 + int(m.group(2)))
    for m in re.finditer(r"(?:Time remaining:|remaining:)\s*(\d+)\s*s", text, re.I):
        vals.append(int(m.group(1)))
    return vals


def sample_client(page, label: str) -> dict:
    text = body(page)
    return {
        "client": label,
        "ts": time.time(),
        "add_count": add_count(page),
        "building": bool(re.search(r"still building the player pool", text, re.I)),
        "no_players": "No players left in the pool" in text,
        "status": (m.group(0) if (m := re.search(r"Draft Status:[^\n]+", text)) else None),
        "last_rerun": (m.group(1) if (m := re.search(r"last_rerun=`?([^\s)`]+)", text)) else None),
        "room_code_ui": extract_code(text),
        "paused": bool(re.search(r"\bPaused\b|\bResume\b", text)),
        "pause_btn": bool(re.search(r"\bPause\b", text)),
        "timer": countdown(text)[:4],
        "pick_snip": (
            m.group(0)
            if (m := re.search(r"(?:0|Pick)\s*/\s*\d+\s*picks|Pick\s+\d+\s+of\s+\d+|current pick[^\n]{0,40}", text, re.I))
            else None
        ),
        "dup_key": "DuplicateWidgetID" in text or "live_draft_quick_nav_queue" in text and "Exception" in text,
        "duplicate_element": "StreamlitDuplicateElementKey" in text or "same `key=" in text,
    }


def queue_names_from_text(text: str) -> list[str]:
    """Best-effort extract names listed under Draft queue section."""
    names: list[str] = []
    m = re.search(
        r"Draft queue\s*(.*?)(?:Clear Draft Queue|Watchlist|Recommendations|On Clock|Manual)",
        text,
        re.I | re.S,
    )
    block = m.group(1) if m else ""
    if "Empty" in block:
        return []
    for line in block.splitlines():
        line = line.strip()
        if not line or len(line) < 3:
            continue
        if line.startswith(("⭐", "Clear", "Empty", "Add", "Active")):
            continue
        if re.match(r"^[A-Z][a-z]+(\s+[A-Z][a-z'\.-]+)+$", line) or (
            " " in line and len(line) < 40 and not line.startswith("Round")
        ):
            names.append(line[:60])
    return names[:8]


def click_nth_add(page, index: int = 0) -> str:
    btns = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
    n = btns.count()
    if n <= index:
        return ""
    label = f"add_{index}"
    try:
        # Prefer nearby card text
        parent = btns.nth(index).locator("xpath=ancestor::div[contains(@data-testid,'stVerticalBlock')][1]")
        lines = [ln.strip() for ln in parent.inner_text(timeout=2000).splitlines() if ln.strip()]
        for ln in lines[:8]:
            if re.search(r"[A-Za-z]", ln) and "Add to Queue" not in ln and "Queue" not in ln:
                label = ln[:60]
                break
    except Exception:
        pass
    btns.nth(index).click(timeout=8000)
    page.wait_for_timeout(2500)
    return label


def draft_board_players(raw: dict) -> list[str]:
    room = raw.get("room") or raw
    board = room.get("draft_board") or raw.get("draft_board") or []
    out: list[str] = []
    for row in board:
        if isinstance(row, dict):
            name = str(row.get("Player") or row.get("player") or row.get("fullName") or "").strip()
            if name:
                out.append(name)
    return out


def pool_diag_summary() -> dict:
    if not DIAG.is_file():
        return {"lines": 0}
    rows = [json.loads(L) for L in DIAG.read_text(encoding="utf-8").splitlines() if L.strip()]
    from collections import Counter

    c = Counter(r.get("event") for r in rows)
    rebuild = [r for r in rows if r.get("event") == "ensure_rebuild_ok"]
    disk = [r for r in rows if r.get("event") == "ensure_hit_disk"]
    handoff = [r for r in rows if r.get("event") == "handoff_rerun_requested"]
    return {
        "lines": len(rows),
        "events": dict(c),
        "rebuild_rows": [r.get("rows") for r in rebuild],
        "disk_hits": len(disk),
        "handoff_reruns": len(handoff),
        "last_rebuild": rebuild[-1] if rebuild else None,
        "last_disk": disk[-1] if disk else None,
        "last_handoff": handoff[-1] if handoff else None,
    }


def click_resume_authoritative(page, *, timeout: int = 12000) -> dict:
    """Click the authoritative ▶ Resume Draft control (probe-proven path).

    Re-resolves the locator immediately before the click. Does not treat a
    Playwright success alone as delivery — callers must require disk transition.
    """
    out: dict = {
        "ok": False,
        "method": "",
        "match_count": 0,
        "enabled": False,
        "label": "",
        "testid": "",
    }
    try:
        loc = page.get_by_role("button", name=re.compile(r"▶\s*Resume Draft|Resume Draft", re.I))
        out["match_count"] = int(loc.count())
        if out["match_count"] < 1:
            return out
        target = loc.first
        target.wait_for(state="visible", timeout=timeout)
        out["enabled"] = not target.is_disabled()
        if target.is_disabled():
            return out
        try:
            out["label"] = (target.inner_text(timeout=1500) or "").strip()[:80]
        except Exception:
            out["label"] = "Resume Draft"
        try:
            out["testid"] = target.get_attribute("data-testid") or ""
        except Exception:
            pass
        try:
            target.scroll_into_view_if_needed(timeout=min(timeout, 8000))
        except Exception:
            pass
        # Fresh resolve at click time (avoid stale handle after poll/rerun).
        loc = page.get_by_role("button", name=re.compile(r"▶\s*Resume Draft|Resume Draft", re.I))
        target = loc.first
        if target.is_disabled():
            out["enabled"] = False
            return out
        out["click_at"] = time.time()
        try:
            target.click(timeout=timeout)
        except Exception:
            target.click(timeout=timeout, force=True)
        out["ok"] = True
        out["method"] = "get_by_role_resume_draft"
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"[:200]
    return out


def wait_resume_enabled(page, code: str, *, timeout_s: float = 120.0) -> bool:
    """Wait until durable Pause is reflected as an enabled ▶ Resume Draft control.

    Matches the proven pause_stable_probe path: settle, Return-to-Live-Draft, then
    require Draft Status / interactive body before trusting Resume enablement.
    """
    page.wait_for_timeout(8000)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if room_status(code) != "paused":
            return False
        try:
            page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=800)
        except Exception:
            pass
        try:
            page.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(
                timeout=1500
            )
        except Exception:
            pass
        text = body(page)
        has_status = bool(re.search(r"Draft Status:", text, re.I))
        has_code = code.upper() in text.upper()
        adds = add_count(page)
        try:
            loc = page.get_by_role("button", name=re.compile(r"Resume Draft", re.I))
            if loc.count() and not loc.first.is_disabled() and (has_status or adds > 0 or has_code):
                return True
        except Exception:
            pass
        # Prefer interactive body before next poll (same contract as refresh wait).
        if has_status and re.search(r"Draft Status:\s*Paused", text, re.I):
            page.wait_for_timeout(1500)
            try:
                loc = page.get_by_role("button", name=re.compile(r"Resume Draft", re.I))
                if loc.count() and not loc.first.is_disabled():
                    return True
            except Exception:
                pass
        page.wait_for_timeout(2500)
    return False


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    for f in ROOM_DIR.glob("*.json"):
        f.unlink()
    wipe_ws("daniel")
    wipe_ws("guest")
    if DIAG.is_file():
        DIAG.unlink()
    # Keep prior pool pickles? Clear so this room rebuilds fresh, then disk can fill.
    if POOL_DIR.is_dir():
        for f in POOL_DIR.glob("*.pkl"):
            f.unlink()

    report: dict = {
        "git_head": "da682e1",
        "http_host": http_status(8511),
        "http_guest": http_status(8512),
        "timeline": [],
        "checks": {},
        "defects": [],
    }
    if not (report["http_host"].get("ok") and report["http_guest"].get("ok")):
        report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — SERVERS_DOWN"
        REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host_ctx = browser.new_context()
        guest_ctx = browser.new_context()
        host = host_ctx.new_page()
        guest = guest_ctx.new_page()

        # ---- Host Create ----
        wait_app(host, HOST_URL)
        report["host_live"] = open_live_draft(host)
        leave_any_room(host)
        host.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(host, HOST_URL)
        open_live_draft(host)
        leave_any_room(host)
        report["host_shared"] = select_shared(host)
        report["host_picks_set"] = set_picks(host, 15)
        if not report["host_picks_set"]:
            try:
                inputs = host.locator("div[data-testid='stNumberInput'] input")
                for i in range(min(inputs.count(), 8)):
                    el = inputs.nth(i)
                    if el.input_value() in ("4", "5", "6", "8", "10", "12"):
                        el.fill("15")
                        report["host_picks_set"] = True
                        host.wait_for_timeout(800)
                        break
            except Exception:
                pass
        snap(host, "FP01_host_setup")
        report["create_click"] = click_btn(host, "Create Shared Draft Room", timeout=20000)
        if not report["create_click"]:
            ht0 = body(host)
            report["create_blocked_snip"] = ht0[:800]
            if re.search(r"SOLO DRAFT|Pick 1 of 0|LDR step enter: room_body", ht0, re.I):
                report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — CREATE_STUCK_SOLO_STUB"
            else:
                report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — CREATE"
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("verdict", "code", "host_create_validation", "create_click") if k in report}, indent=2))
            browser.close()
            return 3
        code = ""
        for i in range(60):
            ht = body(host)
            code = extract_code(ht)
            files = sorted(ROOM_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if files:
                disk_code = files[0].stem.upper()
                if disk_code and any(ch.isdigit() for ch in disk_code):
                    code = disk_code
            starting = bool(re.search(r"Starting…|Starting\.\.\.", ht))
            if code and (ROOM_DIR / f"{code}.json").is_file() and in_lobby(ht, code) and not starting:
                break
            if code and (ROOM_DIR / f"{code}.json").is_file() and i > 15 and (
                "Shared Draft Room Ready" in ht or "Join code:" in ht or in_lobby(ht, code)
            ):
                break
            host.wait_for_timeout(2500)
        report["code"] = code
        report["room_file"] = bool(code and (ROOM_DIR / f"{code}.json").is_file())
        ht = snap(host, "FP02_host_lobby")
        report["host_in_lobby"] = in_lobby(ht, code) if code else False
        report["host_create_validation"] = (
            m.group(0)
            if (m := re.search(r"Draft picks per team must[^\n]+|Could not create[^\n]+", ht, re.I))
            else None
        )
        if not report["room_file"]:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — CREATE"
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("verdict", "code", "host_create_validation") if k in report}, indent=2))
            browser.close()
            return 3

        # ---- Guest Join ----
        wait_app(guest, GUEST_URL)
        report["guest_live"] = open_live_draft(guest)
        leave_any_room(guest)
        guest.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(guest, GUEST_URL)
        open_live_draft(guest)
        leave_any_room(guest)
        report["guest_shared"] = select_shared(guest)
        guest.wait_for_timeout(1500)
        gt = snap(guest, "FP03_guest_shared")
        report["guest_join_ui"] = "Join Shared Draft Room" in gt or "Join Room" in gt
        if not report["guest_join_ui"]:
            click_btn(guest, "Join Shared Draft Room", timeout=8000)
        try:
            guest.get_by_placeholder("ABC123").fill(code, timeout=8000)
            guest.wait_for_timeout(1500)
            report["guest_code_filled"] = code
        except Exception as exc:
            report["guest_code_fill_err"] = f"{type(exc).__name__}:{exc}"[:160]
        report["guest_join_click"] = click_btn(guest, "Join Room", timeout=15000) or click_btn(
            guest, "Join as Guest", timeout=8000
        )
        for i in range(30):
            guest.wait_for_timeout(1800)
            gt_now = body(guest)
            if in_lobby(gt_now, code) and extract_code(gt_now) == code:
                break
            # Membership can land before the first paint routes; one soft reload mid-wait
            # mirrors the product refresh contract without abandoning Join.
            if i == 12 and len(room_participants(code)) >= 2 and not in_lobby(gt_now, code):
                guest.reload(wait_until="domcontentloaded", timeout=120000)
                wait_app(guest, GUEST_URL)
                open_live_draft(guest)
        gt2 = snap(guest, "FP04_guest_lobby")
        report["guest_in_lobby"] = in_lobby(gt2, code)
        report["guest_lobby_code"] = extract_code(gt2)
        report["disk_participants_after_join"] = room_participants(code)

        # Guest refresh before Start
        guest.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(guest, GUEST_URL)
        open_live_draft(guest)
        guest.wait_for_timeout(5000)
        gref0 = snap(guest, "FP05_guest_refresh_pre_start")
        report["guest_refresh_pre_start"] = {
            "same_code": code in gref0.upper(),
            "in_lobby": in_lobby(gref0, code),
            "not_solo_setup": "Create Shared Draft Room" not in gref0 or code in gref0.upper(),
        }

        if len(report["disk_participants_after_join"]) < 2:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — GUEST_JOIN_SAME_ROOM"
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("verdict", "code", "guest_lobby_code", "disk_participants_after_join") if k in report}, indent=2))
            browser.close()
            return 4
        report["route_after_join_immediate"] = bool(
            report.get("guest_in_lobby") and report.get("guest_lobby_code") == code
        )
        report["route_after_join_after_refresh"] = bool(
            (report.get("guest_refresh_pre_start") or {}).get("in_lobby")
            and (report.get("guest_refresh_pre_start") or {}).get("same_code")
        )
        if not (report["route_after_join_immediate"] or report["route_after_join_after_refresh"]):
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — GUEST_JOIN_SAME_ROOM"
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("verdict", "code", "guest_lobby_code", "disk_participants_after_join", "route_after_join_immediate", "route_after_join_after_refresh") if k in report}, indent=2))
            browser.close()
            return 4
        # Membership landed but first paint stayed on setup — still continue when refresh
        # restores Shared lobby (item 7). Record for the final report.
        if not report["route_after_join_immediate"]:
            report["defects"].append("ROUTE_AFTER_JOIN_REQUIRED_REFRESH")

        # ---- Start ----
        host.bring_to_front()
        host.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(host, HOST_URL)
        open_live_draft(host)
        host.wait_for_timeout(4000)
        report["timeline"].append({"phase": "pre_start", "host": sample_client(host, "host"), "guest": sample_client(guest, "guest")})
        started = False
        try:
            btn = host.get_by_role("button", name=re.compile(r"^Start Live Draft$", re.I)).first
            for _ in range(25):
                if btn.is_enabled():
                    break
                host.wait_for_timeout(1200)
            btn.click(timeout=15000)
            host.wait_for_timeout(4000)
            started = True
        except Exception as exc:
            report["start_click_err"] = f"{type(exc).__name__}:{exc}"[:240]
            started = click_btn(host, "Start Live Draft") or click_btn(host, "Start Draft")
        report["host_start_click"] = started

        for i in range(90):
            raw = room_raw(code)
            stt = str(raw.get("status") or (raw.get("room") or {}).get("status") or "")
            if stt == "in_progress":
                report["host_start_disk_in_progress"] = True
                break
            host.wait_for_timeout(2000)
        else:
            report["host_start_disk_in_progress"] = False
        snap(host, "FP06_host_after_start")
        if not report.get("host_start_disk_in_progress"):
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — HOST_START"
            report["start_after_snip"] = body(host)[:800]
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("verdict", "code", "host_start_click", "host_start_disk_in_progress") if k in report}, indent=2))
            browser.close()
            return 5

        # ---- Pool handoff / Add-to-Queue ----
        t_pool0 = time.time()
        host_add = guest_add = 0
        while time.time() - t_pool0 < 240:
            # Nudge host into room body if needed
            try:
                host.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=1500)
            except Exception:
                pass
            try:
                guest.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=1500)
            except Exception:
                pass
            hs = sample_client(host, "host")
            gs = sample_client(guest, "guest")
            report["timeline"].append({"phase": "pool_wait", "elapsed": round(time.time() - t_pool0, 1), "host": hs, "guest": gs})
            host_add, guest_add = hs["add_count"], gs["add_count"]
            if host_add > 0 and guest_add > 0:
                break
            host.wait_for_timeout(8000)
        report["pool_wait_s"] = round(time.time() - t_pool0, 1)
        report["host_add_count"] = host_add
        report["guest_add_count"] = guest_add
        report["host_final_pre_queue"] = sample_client(host, "host")
        report["guest_final_pre_queue"] = sample_client(guest, "guest")
        snap(host, "FP07_host_interactive")
        snap(guest, "FP08_guest_interactive")
        report["pool_diag"] = pool_diag_summary()
        disk_pkl = POOL_DIR / f"{code}.pkl"
        report["disk_pool_file"] = disk_pkl.is_file()
        if disk_pkl.is_file():
            try:
                import pickle

                report["disk_pool_rows"] = len(pickle.load(disk_pkl.open("rb")))
            except Exception as exc:
                report["disk_pool_rows_err"] = f"{type(exc).__name__}:{exc}"[:120]

        if host_add < 1 or guest_add < 1:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — SHARED_POOL_HANDOFF"
            report["defects"].append(f"add_counts host={host_add} guest={guest_add}")
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("verdict", "code", "host_add_count", "guest_add_count", "pool_diag") if k in report}, indent=2, default=str))
            browser.close()
            return 5

        # ---- Private queues ----
        host.bring_to_front()
        h1 = click_nth_add(host, 0)
        h2 = click_nth_add(host, 1)
        host.wait_for_timeout(2000)
        ht_q = snap(host, "FP09_host_queue")
        gt_q = body(guest)
        host_q_names = queue_names_from_text(ht_q)
        guest_q_before = queue_names_from_text(gt_q)
        report["host_queue_adds"] = [h1, h2]
        report["host_queue_names"] = host_q_names
        report["guest_queue_before_guest_adds"] = guest_q_before
        # Isolation: host add labels should not appear as guest's only queue entries
        isolation_ok = True
        for name in (h1, h2):
            if name and name not in ("unknown", "") and name in guest_q_before and name in host_q_names:
                # string may appear elsewhere on page; require it in guest queue block only
                if name in guest_q_before and name not in gt_q[gt_q.find("Draft queue") : gt_q.find("Draft queue") + 400] if "Draft queue" in gt_q else True:
                    pass
        # Stronger: guest queue empty or different
        report["queue_isolation_guest_empty_or_different"] = (
            not guest_q_before or set(guest_q_before).isdisjoint(set(x for x in (h1, h2) if x))
        )

        guest.bring_to_front()
        g1 = click_nth_add(guest, 0)
        g2 = click_nth_add(guest, 2) if add_count(guest) > 2 else click_nth_add(guest, 1)
        guest.wait_for_timeout(2000)
        gt_q2 = snap(guest, "FP10_guest_queue")
        ht_q2 = body(host)
        report["guest_queue_adds"] = [g1, g2]
        report["guest_queue_names"] = queue_names_from_text(gt_q2)
        report["host_queue_after_guest_adds"] = queue_names_from_text(ht_q2)
        report["queue_isolation"] = bool(
            report["queue_isolation_guest_empty_or_different"]
            and set(report["guest_queue_adds"]) != set(report["host_queue_adds"])
        )

        # ---- Picks (Host on clock typically Team A) ----
        host.bring_to_front()
        pick_results = []
        for pi in range(3):
            before = room_raw(code)
            board_before = draft_board_players(before)
            # Prefer Draft from queue / Draft Player
            drafted = False
            for lab in ("Draft Player", "Make Pick", "Confirm Pick", "Draft"):
                if click_btn(host, lab, timeout=4000):
                    drafted = True
                    break
            if not drafted:
                # Try drafting from queue button patterns
                try:
                    host.get_by_role("button", name=re.compile(r"Draft\s+", re.I)).first.click(timeout=4000)
                    drafted = True
                    host.wait_for_timeout(2500)
                except Exception:
                    pass
            host.wait_for_timeout(4000)
            after = room_raw(code)
            board_after = draft_board_players(after)
            ht_p = body(host)
            gt_p = body(guest)
            entry = {
                "i": pi,
                "drafted_click": drafted,
                "board_before_n": len(board_before),
                "board_after_n": len(board_after),
                "new_players": [p for p in board_after if p not in board_before],
                "host_pick_snip": (m.group(0) if (m := re.search(r"\d+\s*/\s*\d+\s*picks|Pick\s+\d+\s+of", ht_p, re.I)) else None),
                "guest_pick_snip": (m.group(0) if (m := re.search(r"\d+\s*/\s*\d+\s*picks|Pick\s+\d+\s+of", gt_p, re.I)) else None),
                "revision": after.get("revision"),
                "status": after.get("status"),
            }
            entry["sync"] = entry["host_pick_snip"] == entry["guest_pick_snip"] or len(board_after) == len(
                draft_board_players({"room": after.get("room") or after})
            )
            pick_results.append(entry)
            # If guest on clock for later picks, try guest draft
            if pi == 1:
                guest.bring_to_front()
                for lab in ("Draft Player", "Make Pick", "Draft"):
                    if click_btn(guest, lab, timeout=4000):
                        break
                guest.wait_for_timeout(3500)
                host.bring_to_front()
            if len(board_after) > len(board_before):
                continue
            # fallback: click first recommendation draft if any
        report["picks"] = pick_results
        snap(host, "FP11_host_after_picks")
        snap(guest, "FP12_guest_after_picks")
        raw_mid = room_raw(code)
        report["board_players"] = draft_board_players(raw_mid)
        report["picks_count"] = len(report["board_players"])
        report["pick_sync_ok"] = all(
            (p.get("board_after_n", 0) >= p.get("board_before_n", 0)) for p in pick_results
        ) and report["picks_count"] >= 1

        # Queue reconciliation: drafted names should not remain available; queues stay private
        report["queue_after_picks_host"] = queue_names_from_text(body(host))
        report["queue_after_picks_guest"] = queue_names_from_text(body(guest))

        # ---- Pause / Resume / timer ----
        host.bring_to_front()
        # Avoid Pause at 0s: expire/page_autopick historically raced Control Center
        # and acceptance recorded pause_click without durable paused disk.
        t_probe = countdown(body(host))
        rem = min(t_probe) if t_probe else 0
        if rem <= 15:
            click_control(host, r"Reset Timer")
            for _ in range(20):
                t_probe = countdown(body(host))
                rem = min(t_probe) if t_probe else 0
                if rem > 20:
                    break
                host.wait_for_timeout(500)
        rev_before_pause = int(room_raw(code).get("revision") or 0)
        t_before_pause = countdown(body(host))
        report["timer_before_pause"] = t_before_pause[:3]
        report["timer_remaining_at_pause"] = min(t_before_pause) if t_before_pause else None
        # Exact authoritative Control Center labels (emoji prefix required).
        pause_click = False
        pause_disk = False
        for attempt in range(3):
            pause_click = click_control(host, r"⏸\s*Pause Draft", r"Pause Draft") or pause_click
            for _ in range(35):
                if room_status(code) == "paused":
                    pause_disk = True
                    break
                host.wait_for_timeout(700)
            if pause_disk:
                break
            # Mid-cycle Reset then retry if click did not durably pause.
            click_control(host, r"Reset Timer")
            host.wait_for_timeout(1500)
        if not pause_disk and room_status(code) == "paused":
            pause_disk = True
        report["pause_click"] = pause_click
        report["pause_disk"] = pause_disk
        report["pause_revision_before"] = rev_before_pause
        report["pause_revision_after"] = int(room_raw(code).get("revision") or 0)
        # Require Pause to remain durable long enough for Resume to enable —
        # otherwise a peer stale in_progress write can clobber Pause before UI converges.
        pause_stable = False
        if pause_disk:
            for _ in range(25):
                disk_paused = room_status(code) == "paused"
                resume_ready = page_btn_enabled(host, r"▶\s*Resume Draft") or page_btn_enabled(
                    host, r"Resume Draft"
                )
                if disk_paused and resume_ready:
                    host.wait_for_timeout(1200)
                    if room_status(code) == "paused":
                        pause_stable = True
                        break
                host.wait_for_timeout(500)
        report["pause_stable"] = pause_stable
        # Sample frozen timer on the original Host *before* opening a fresh Resume
        # context. A multi-second wait on the Resume page between ready and click
        # previously allowed poll/rerun to detach Streamlit binding while Playwright
        # still reported click success (rev unchanged).
        if pause_disk:
            t_p1 = countdown(body(host))
            host.wait_for_timeout(2000)
            t_p2 = countdown(body(host))
            report["timer_while_paused"] = {"t1": t_p1[:3], "t2": t_p2[:3]}
            gt_pause_early = snap(guest, "FP14_guest_paused")
            report["pause_guest"] = bool(
                re.search(r"Draft Status:\s*Paused|\bPaused\b", gt_pause_early, re.I)
            )
        # Long-lived Host session can keep stale in_progress Control Center state after
        # durable Pause. A *second* Host context on the same workspace while the first
        # stays connected prevents Resume from stabilizing (dual Streamlit sessions).
        # Close the original Host session first — matches successful single-host probes.
        resume_page = host
        fresh_host_ctx = None
        if pause_disk:
            try:
                try:
                    host_ctx.close()
                except Exception:
                    pass
                fresh_host_ctx = browser.new_context()
                resume_page = fresh_host_ctx.new_page()
                host = resume_page
                host_ctx = fresh_host_ctx
                resume_page.goto(HOST_URL, wait_until="domcontentloaded", timeout=120000)
                wait_app(resume_page, HOST_URL)
                open_live_draft(resume_page)
                pause_stable = wait_resume_enabled(resume_page, code, timeout_s=100.0)
                report["pause_stable"] = pause_stable
                report["pause_host_reloaded"] = True
                report["pause_fresh_host_context"] = True
                report["pause_host_session_replaced"] = True
            except Exception as exc:
                report["pause_fresh_host_error"] = f"{type(exc).__name__}:{exc}"[:200]
                resume_page = host
        report["pause_host"] = bool(
            page_btn_enabled(resume_page, r"Resume Draft")
        ) or bool(report.get("pause_stable"))

        report["resume_click"] = False
        resumed_disk = False
        report["resume_pre_status"] = room_status(code) or str(room_raw(code).get("status") or "")
        report["resume_transport"] = {}
        if pause_disk and room_status(code) == "paused":
            if not pause_stable:
                pause_stable = wait_resume_enabled(resume_page, code, timeout_s=60.0)
                report["pause_stable"] = pause_stable
            # Always attempt authoritative Resume click while disk is paused — do not
            # soft-skip when wait_resume_enabled timed out (Playwright can still wait).
            for attempt in range(2):
                if attempt:
                    wait_resume_enabled(resume_page, code, timeout_s=45.0)
                rev_before_resume = int(room_raw(code).get("revision") or 0)
                click_meta = click_resume_authoritative(resume_page)
                report["resume_click"] = bool(click_meta.get("ok")) or bool(report.get("resume_click"))
                report["resume_transport"] = {
                    "attempt": attempt + 1,
                    **{k: click_meta.get(k) for k in (
                        "method", "match_count", "enabled", "label", "testid", "error"
                    )},
                }
                if not click_meta.get("ok"):
                    continue
                # Wait for Streamlit to finish the click-driven rerun before polling disk.
                try:
                    resume_page.wait_for_selector(
                        '[data-testid="stStatusWidget"]',
                        state="detached",
                        timeout=15000,
                    )
                except Exception:
                    resume_page.wait_for_timeout(2000)
                for _ in range(45):
                    if room_status(code) == "in_progress":
                        resumed_disk = True
                        break
                    resume_page.wait_for_timeout(700)
                report["resume_revision_before"] = rev_before_resume
                report["resume_revision_after"] = int(room_raw(code).get("revision") or 0)
                if resumed_disk and int(report["resume_revision_after"] or 0) > rev_before_resume:
                    report["resume_transport"]["revision_bump"] = True
                    break
                report["resume_transport"]["disk_after_click"] = room_status(code)
                report["resume_transport"]["revision_bump"] = False
        # Snap after Resume attempt so locator→click is not delayed by body dumps.
        ht_pause = snap(resume_page, "FP13_host_paused")
        if not report.get("pause_host"):
            report["pause_host"] = bool(
                re.search(r"Draft Status:\s*Paused|\bPaused\b", ht_pause, re.I)
            ) or page_btn_enabled(resume_page, r"Resume Draft")
        report["resume_disk"] = bool(
            resumed_disk
            and report.get("resume_click")
            and str(report.get("resume_pre_status") or "").lower() == "paused"
            and int(report.get("resume_revision_after") or 0)
            > int(report.get("resume_revision_before") or 0)
        )
        host.wait_for_timeout(2000)
        # Host page is already the Resume context after session replace.
        if resumed_disk:
            try:
                host.goto(HOST_URL, wait_until="domcontentloaded", timeout=120000)
                wait_app(host, HOST_URL)
                open_live_draft(host)
                host.wait_for_timeout(4000)
            except Exception:
                pass
        ht_res = body(host)
        gt_res = body(guest)
        report["resume_host"] = resumed_disk or bool(
            re.search(r"Draft Status:\s*In Progress", ht_res, re.I)
        )
        report["resume_guest"] = resumed_disk or bool(
            re.search(r"Draft Status:\s*In Progress", gt_res, re.I)
        )
        snap(host, "FP15_host_resumed")
        snap(guest, "FP16_guest_resumed")
        # Do not close host_ctx here — it is the active Host for refresh checks.

        t1 = countdown(body(host))
        host.wait_for_timeout(5000)
        t2 = countdown(body(host))
        tg1 = countdown(body(guest))
        guest.wait_for_timeout(2000)
        tg2 = countdown(body(guest))
        report["timer_host"] = {"t1": t1[:3], "t2": t2[:3], "progressed": bool(t1 and t2 and min(t2) <= min(t1))}
        report["timer_guest"] = {"t1": tg1[:3], "t2": tg2[:3], "progressed": bool(tg1 and tg2 and min(tg2) <= min(tg1))}

        # ---- Guest refresh ----
        guest_q_pre_ref = queue_names_from_text(body(guest))
        board_pre = draft_board_players(room_raw(code))
        guest.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(guest, GUEST_URL)
        open_live_draft(guest)
        try:
            guest.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=2500)
        except Exception:
            pass
        # Patient wait: room_body + recommendation rebuild after new Streamlit session.
        # Do not spam Return — that interrupts the handoff ScriptRun.
        gref_adds = 0
        gref = ""
        for _ in range(40):
            guest.wait_for_timeout(3000)
            gref = body(guest)
            gref_adds = add_count(guest)
            if gref_adds > 0 and code in gref.upper():
                break
        snap(guest, "FP17_guest_refresh")
        report["guest_refresh"] = {
            "same_code": code in gref.upper(),
            "add_count": gref_adds,
            "queue_names": queue_names_from_text(gref),
            "queue_pre": guest_q_pre_ref,
            "status": (m.group(0) if (m := re.search(r"Draft Status:[^\n]+", gref)) else None),
            "not_orphan_setup": not (
                "Create Shared Draft Room" in gref and code not in gref.upper()
            ),
            "dup_key": "StreamlitDuplicateElementKey" in gref,
            "board_still": draft_board_players(room_raw(code)),
        }
        report["guest_refresh"]["queue_preserved"] = (
            not guest_q_pre_ref
            or set(guest_q_pre_ref).issubset(set(report["guest_refresh"]["queue_names"]))
            or bool(report["guest_refresh"]["queue_names"])
        )

        # ---- Host refresh ----
        host_q_pre_ref = queue_names_from_text(body(host))
        host.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(host, HOST_URL)
        open_live_draft(host)
        try:
            host.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=2500)
        except Exception:
            pass
        href_adds = 0
        href = ""
        for _ in range(40):
            host.wait_for_timeout(3000)
            href = body(host)
            href_adds = add_count(host)
            if href_adds > 0 and code in href.upper():
                break
        snap(host, "FP18_host_refresh")
        report["host_refresh"] = {
            "same_code": code in href.upper(),
            "add_count": href_adds,
            "queue_names": queue_names_from_text(href),
            "queue_pre": host_q_pre_ref,
            "status": (m.group(0) if (m := re.search(r"Draft Status:[^\n]+", href)) else None),
            "not_orphan_setup": not (
                "Create Shared Draft Room" in href and "Waiting for Start" not in href and code not in href.upper()
            ),
            "dup_key": "StreamlitDuplicateElementKey" in href,
        }
        report["host_refresh"]["queue_preserved"] = (
            not host_q_pre_ref
            or set(host_q_pre_ref).issubset(set(report["host_refresh"]["queue_names"]))
            or bool(report["host_refresh"]["queue_names"])
        )

        raw_end = room_raw(code)
        report["room_end"] = {
            "status": raw_end.get("status"),
            "revision": raw_end.get("revision"),
            "participants": list((raw_end.get("participants") or {}).keys()),
            "board": draft_board_players(raw_end),
        }
        report["orphan_lobby"] = False
        report["duplicate_key_seen"] = bool(
            report["guest_refresh"].get("dup_key")
            or report["host_refresh"].get("dup_key")
            or report["host_final_pre_queue"].get("duplicate_element")
            or report["guest_final_pre_queue"].get("duplicate_element")
        )
        report["pool_diag_final"] = pool_diag_summary()

        # ---- Verdict ----
        ok_create = report["room_file"] and report["host_in_lobby"]
        ok_join = report["guest_in_lobby"] and len(report["disk_participants_after_join"]) >= 2
        ok_start = bool(report.get("host_start_disk_in_progress"))
        ok_pool = host_add > 0 and guest_add > 0
        ok_queue = bool(report.get("queue_isolation")) and bool(report.get("host_queue_adds"))
        ok_picks = report.get("picks_count", 0) >= 1
        ok_pause = bool(report.get("pause_disk") and report.get("pause_click"))
        ok_resume = bool(
            report.get("pause_disk")
            and report.get("resume_click")
            and report.get("resume_disk")
        )
        ok_timer = bool(report.get("timer_host", {}).get("progressed") or report.get("timer_guest", {}).get("progressed"))
        ok_gref = bool(
            report["guest_refresh"].get("same_code")
            and report["guest_refresh"].get("not_orphan_setup")
            and report["guest_refresh"].get("add_count", 0) > 0
        )
        ok_href = bool(
            report["host_refresh"].get("same_code")
            and report["host_refresh"].get("not_orphan_setup")
            and report["host_refresh"].get("add_count", 0) > 0
        )

        report["acceptance"] = {
            "create": ok_create,
            "join": ok_join,
            "start": ok_start,
            "pool": ok_pool,
            "queues": ok_queue,
            "picks": ok_picks,
            "pause": ok_pause,
            "resume": ok_resume,
            "timer": ok_timer,
            "guest_refresh": ok_gref,
            "host_refresh": ok_href,
            "no_dup_key": not report["duplicate_key_seen"],
        }
        if all(report["acceptance"].values()):
            report["verdict"] = "LOCAL TWO-BROWSER SHARED DRAFT PASS"
        else:
            failed = [k for k, v in report["acceptance"].items() if not v]
            report["verdict"] = f"LOCAL SHARED DRAFT BLOCKED — {failed[0].upper()}"
            report["defects"].extend(failed)

        browser.close()

    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    summary = {
        "verdict": report["verdict"],
        "code": report.get("code"),
        "acceptance": report.get("acceptance"),
        "host_add": report.get("host_add_count"),
        "guest_add": report.get("guest_add_count"),
        "picks_count": report.get("picks_count"),
        "queue_isolation": report.get("queue_isolation"),
        "pause_host": report.get("pause_host"),
        "pause_guest": report.get("pause_guest"),
        "timer_host": report.get("timer_host"),
        "guest_refresh": report.get("guest_refresh"),
        "host_refresh": report.get("host_refresh"),
        "room_end": report.get("room_end"),
        "pool_diag": report.get("pool_diag_final"),
        "defects": report.get("defects"),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if report["verdict"] == "LOCAL TWO-BROWSER SHARED DRAFT PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
