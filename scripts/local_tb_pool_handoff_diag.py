"""Diagnose SHARED_POOL_HANDOFF — Create → Join (same room) → Start → sample pool.

Requires durable host:8511 / guest:8512 already up. Restarts not performed here.
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
REPORT = OUT / "pool_handoff_diag.json"
DIAG = OUT / "pool_live_diag.jsonl"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"

_CODE_DENY = frozenset(
    {"SHARED", "DRAFTS", "PLAYER", "BEFORE", "STATUS", "SELECT", "BUTTON", "TEAMSA", "TEAMSB", "WAITING"}
)


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
    (OUT / f"{name}.txt").write_text(text[:14000], encoding="utf-8")
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
            page.wait_for_timeout(4000)
            break
        except Exception:
            try:
                page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).click(timeout=8000)
                page.wait_for_timeout(4000)
                break
            except Exception:
                try:
                    page.locator("label", has_text=re.compile(r"Live Draft Room", re.I)).first.click(timeout=8000)
                    page.wait_for_timeout(4000)
                    break
                except Exception:
                    pass
    return bool(
        re.search(r"Draft Mode|Waiting for Start|Room\s+[A-Z0-9]{6}|Create Shared|Add to Queue", body(page), re.I)
    )


def leave_any_room(page) -> None:
    for _ in range(4):
        text = body(page)
        if "Create Shared Draft Room" in text and "Waiting for Start" not in text:
            return
        clicked = False
        for lab in (
            "Back to Draft Setup",
            "Return to Live Draft Lobby",
            "Leave This Room",
            "Leave Room",
            "End/Delete Draft",
            "End Draft",
            "Confirm End/Delete",
            "Confirm",
        ):
            try:
                page.get_by_role("button", name=re.compile(rf"^{re.escape(lab)}$", re.I)).first.click(timeout=2500)
                page.wait_for_timeout(1500)
                clicked = True
            except Exception:
                continue
        if not clicked:
            page.reload(wait_until="domcontentloaded", timeout=120000)
            open_live_draft(page)
            page.wait_for_timeout(2000)


def select_shared(page) -> bool:
    for lab in (r"Shared Multiplayer Draft Room", r"Shared Multiplayer", r"^Shared$"):
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
            page.wait_for_timeout(1500)
            return True
        except Exception:
            continue
    return False


def click_btn(page, label: str, timeout: int = 12000) -> bool:
    try:
        page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I)).first.click(timeout=timeout)
        page.wait_for_timeout(2000)
        return True
    except Exception:
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=timeout)
            page.wait_for_timeout(2000)
            return True
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
    if not code or code not in text:
        return False
    return bool(re.search(r"Waiting for Start|Join code:|Shared Draft Room Ready|Waiting to Start", text, re.I))


def room_participants(code: str) -> list[str]:
    p = ROOM_DIR / f"{code}.json"
    if not p.is_file():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return list((raw.get("participants") or {}).keys())


def sample_handoff(page, label: str) -> dict:
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
        "rebuild_err_caption": (
            m.group(1).strip()
            if (m := re.search(r"Local pool rebuild:\s*`([^`]+)`", text))
            else None
        ),
        "last_rerun": (
            m.group(1) if (m := re.search(r"last_rerun=`?([^\s)`]+)", text)) else None
        ),
        "ldr_steps": re.findall(r"⏱ LDR step[^\n]+", text)[:6],
        "on_clock": bool(re.search(r"On (the )?clock|in_progress|0 / \d+ picks", text, re.I)),
        "starting": bool(re.search(r"Starting…|Starting\.\.\.", text)),
        "status_snip": (
            m.group(0) if (m := re.search(r"Draft Status:[^\n]+", text)) else None
        ),
        "room_code_ui": extract_code(text),
    }


def read_ws_diag(ws: str) -> dict:
    p = ROOT / "data" / "workspaces" / ws / "baseball_user_state.json"
    out: dict = {"workspace": ws}
    if not p.is_file():
        return out
    st = json.loads(p.read_text(encoding="utf-8")).get("state") or {}
    for k in (
        "_shared_local_pool_rebuild_error",
        "_shared_local_pool_rebuild_rows",
        "_shared_local_pool_rebuild_source",
        "_live_draft_shared_rec_pool_pending",
        "_live_draft_shared_rec_pool_ready_rerun_attempted",
        "_live_draft_last_rerun_source",
        "active_shared_draft_room_code",
    ):
        if k in st:
            out[k] = st[k]
    out["has_draft_room_player_pool_key"] = "draft_room_player_pool" in st
    room = st.get("live_draft_room")
    if isinstance(room, dict):
        out["room_status"] = room.get("status")
        out["room_has_pool_key"] = "pool" in room
        out["room_pool_records_len"] = len(room.get("pool_records") or [])
        out["scoring_diag_present"] = bool(room.get("_live_draft_pool_scoring_diag"))
    return out


def main() -> int:
    from playwright.sync_api import sync_playwright

    for f in ROOM_DIR.glob("*.json"):
        f.unlink()
    wipe_ws("daniel")
    wipe_ws("guest")
    if DIAG.is_file():
        DIAG.unlink()

    report: dict = {
        "git_head": "92afe49",
        "http_host": http_status(8511),
        "http_guest": http_status(8512),
        "timeline": [],
        "product_edit": False,
    }
    if not (report["http_host"].get("ok") and report["http_guest"].get("ok")):
        report["verdict"] = "SERVERS_DOWN"
        REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host = browser.new_context().new_page()
        guest = browser.new_context().new_page()

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
                n = inputs.count()
                for i in range(min(n, 8)):
                    el = inputs.nth(i)
                    val = el.input_value()
                    if val in ("4", "5", "6", "8", "10", "12"):
                        el.fill("15")
                        report["host_picks_set"] = True
                        host.wait_for_timeout(1000)
                        break
            except Exception:
                pass
        host.wait_for_timeout(2000)
        snap(host, "HD01_host_setup")
        report["create_click"] = click_btn(host, "Create Shared Draft Room", timeout=20000)

        code = ""
        for i in range(60):
            ht = body(host)
            code = extract_code(ht)
            files = sorted(ROOM_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if files and (not code or code != files[0].stem.upper()):
                # Prefer authoritative disk code once create wrote a file.
                disk_code = files[0].stem.upper()
                if disk_code and any(ch.isdigit() for ch in disk_code):
                    code = disk_code
            starting = bool(re.search(r"Starting…|Starting\.\.\.", ht))
            if code and (ROOM_DIR / f"{code}.json").is_file() and in_lobby(ht, code) and not starting:
                break
            if code and (ROOM_DIR / f"{code}.json").is_file() and i > 20 and in_lobby(ht, code):
                # Sticky Starting… after ready — still proceed if lobby chrome present.
                if "Shared Draft Room Ready" in ht or "Join code:" in ht:
                    break
            host.wait_for_timeout(3000)
            if i % 5 == 0:
                report["timeline"].append(
                    {"t": time.time(), "phase": "host_create_wait", **sample_handoff(host, "host")}
                )
        report["code"] = code
        report["room_file"] = bool(code and (ROOM_DIR / f"{code}.json").is_file())
        ht = snap(host, "HD02_host_lobby")
        report["host_in_lobby"] = in_lobby(ht, code) if code else False
        report["host_create_validation"] = (
            m.group(0)
            if (m := re.search(r"Draft picks per team must[^\n]+|Could not create[^\n]+", ht, re.I))
            else None
        )
        if not report["room_file"]:
            report["verdict"] = "BLOCKED_CREATE"
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(
                json.dumps(
                    {k: report[k] for k in ("verdict", "code", "host_create_validation", "host_picks_set") if k in report},
                    indent=2,
                )
            )
            browser.close()
            return 3

        # Guest must join THIS code — leave any accidental self-room first.
        wait_app(guest, GUEST_URL)
        report["guest_live"] = open_live_draft(guest)
        leave_any_room(guest)
        guest.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(guest, GUEST_URL)
        open_live_draft(guest)
        leave_any_room(guest)
        report["guest_shared"] = select_shared(guest)
        guest.wait_for_timeout(2000)
        # Never click Create on guest.
        gt = snap(guest, "HD03_guest_shared")
        report["guest_join_ui"] = "Join Shared Draft Room" in gt or "Join Room" in gt
        if not report["guest_join_ui"]:
            # Expand join panel if collapsed
            click_btn(guest, "Join Shared Draft Room", timeout=8000)
            gt = body(guest)
            report["guest_join_ui"] = "Join Room" in gt or "ABC123" in gt
        try:
            guest.get_by_placeholder("ABC123").fill(code, timeout=8000)
            guest.wait_for_timeout(2000)
            report["guest_code_filled"] = code
        except Exception as exc:
            report["guest_code_fill_err"] = f"{type(exc).__name__}:{exc}"[:160]
        join_ok = click_btn(guest, "Join Room", timeout=15000) or click_btn(guest, "Join as Guest", timeout=8000)
        report["guest_join_click"] = join_ok
        for _ in range(25):
            guest.wait_for_timeout(2000)
            gt2 = body(guest)
            if in_lobby(gt2, code) and extract_code(gt2) == code:
                break
        gt2 = snap(guest, "HD04_guest_lobby")
        report["guest_in_lobby"] = in_lobby(gt2, code)
        report["guest_lobby_code"] = extract_code(gt2)
        report["disk_participants_after_join"] = room_participants(code)

        if report.get("guest_lobby_code") != code or len(report["disk_participants_after_join"]) < 2:
            report["verdict"] = "BLOCKED_GUEST_JOIN_SAME_ROOM"
            report["host_final"] = sample_handoff(host, "host")
            report["guest_final"] = sample_handoff(guest, "guest")
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "verdict": report["verdict"],
                        "code": code,
                        "guest_lobby_code": report.get("guest_lobby_code"),
                        "parts": report["disk_participants_after_join"],
                    },
                    indent=2,
                )
            )
            browser.close()
            return 4

        # Host Start — require enabled button (2 owners)
        host.bring_to_front()
        host.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(host, HOST_URL)
        open_live_draft(host)
        host.wait_for_timeout(4000)
        report["timeline"].append({"phase": "pre_start", **sample_handoff(host, "host")})
        report["timeline"].append({"phase": "pre_start", **sample_handoff(guest, "guest")})
        started = False
        try:
            btn = host.get_by_role("button", name=re.compile(r"^Start Live Draft$", re.I)).first
            # Wait until enabled
            for _ in range(20):
                if btn.is_enabled():
                    break
                host.wait_for_timeout(1500)
            btn.click(timeout=15000)
            host.wait_for_timeout(4000)
            started = True
        except Exception as exc:
            report["start_click_err"] = f"{type(exc).__name__}:{exc}"[:240]
            started = click_btn(host, "Start Live Draft", timeout=15000) or click_btn(
                host, "Start Draft", timeout=10000
            )
        report["host_start_click"] = started

        for i in range(40):
            if code and (ROOM_DIR / f"{code}.json").is_file():
                raw = json.loads((ROOM_DIR / f"{code}.json").read_text(encoding="utf-8"))
                stt = str(raw.get("status") or (raw.get("room") or {}).get("status") or "")
                report["timeline"].append(
                    {
                        "phase": "start_wait",
                        "i": i,
                        "disk_status": stt,
                        **sample_handoff(host, "host"),
                    }
                )
                if stt == "in_progress":
                    report["host_start_disk_in_progress"] = True
                    break
            host.wait_for_timeout(2000)
        else:
            report["host_start_disk_in_progress"] = False
        snap(host, "HD05_host_after_start")
        report["timeline"].append({"phase": "post_start_0s", **sample_handoff(host, "host")})

        t0 = time.time()
        while time.time() - t0 < 210:
            hs = sample_handoff(host, "host")
            gs = sample_handoff(guest, "guest")
            report["timeline"].append(
                {"phase": "wait", "elapsed": round(time.time() - t0, 1), "host": hs, "guest": gs}
            )
            if hs.get("has_add") and gs.get("has_add"):
                break
            host.wait_for_timeout(10000)

        snap(host, "HD06_host_final")
        snap(guest, "HD07_guest_final")
        report["host_final"] = sample_handoff(host, "host")
        report["guest_final"] = sample_handoff(guest, "guest")
        report["host_ws"] = read_ws_diag("daniel")
        report["guest_ws"] = read_ws_diag("guest")
        report["pool_live_diag_lines"] = (
            DIAG.read_text(encoding="utf-8").splitlines() if DIAG.is_file() else []
        )[-40:]

        if code and (ROOM_DIR / f"{code}.json").is_file():
            raw = json.loads((ROOM_DIR / f"{code}.json").read_text(encoding="utf-8"))
            room = raw.get("room") or {}
            report["room_doc"] = {
                "status": raw.get("status") or room.get("status"),
                "revision": raw.get("revision"),
                "participants": list((raw.get("participants") or {}).keys()),
                "has_pool": "pool" in room,
                "pool_records_len": len(room.get("pool_records") or []),
                "scoring_diag": bool(room.get("_live_draft_pool_scoring_diag")),
            }

        h_ok = bool(report["host_final"].get("has_add"))
        g_ok = bool(report["guest_final"].get("has_add"))
        if h_ok and g_ok:
            report["verdict"] = "POOL_HANDOFF_BROWSER_PASS"
        elif not report.get("host_start_disk_in_progress"):
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — START_NOT_IN_PROGRESS"
            report["classification"] = "START_NOT_IN_PROGRESS"
        else:
            herr = report["host_final"].get("rebuild_err_caption") or report["host_ws"].get(
                "_shared_local_pool_rebuild_error"
            )
            gerr = report["guest_final"].get("rebuild_err_caption") or report["guest_ws"].get(
                "_shared_local_pool_rebuild_error"
            )
            hrows = report["host_ws"].get("_shared_local_pool_rebuild_rows")
            grows = report["guest_ws"].get("_shared_local_pool_rebuild_rows")
            if herr or gerr:
                report["classification"] = "POOL_REBUILD_EXCEPTION"
            elif hrows or grows:
                report["classification"] = "POOL_REBUILD_SUCCEEDS_NOT_ADOPTED"
            elif report["host_final"].get("building") or report["guest_final"].get("building"):
                report["classification"] = "POOL_HANDOFF_STUCK_BUILDING"
            else:
                report["classification"] = "SHARED_POOL_HANDOFF"
            report["verdict"] = f"LOCAL SHARED DRAFT BLOCKED — {report['classification']}"

        REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "verdict": report.get("verdict"),
                    "classification": report.get("classification"),
                    "code": report.get("code"),
                    "parts": report.get("disk_participants_after_join"),
                    "host_start_click": report.get("host_start_click"),
                    "in_progress": report.get("host_start_disk_in_progress"),
                    "host_final": report.get("host_final"),
                    "guest_final": report.get("guest_final"),
                    "diag_tail": (report.get("pool_live_diag_lines") or [])[-8:],
                },
                indent=2,
                default=str,
            )
        )
        browser.close()
        return 0 if h_ok and g_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
