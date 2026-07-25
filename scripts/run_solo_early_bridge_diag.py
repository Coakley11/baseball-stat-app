"""Early-route persistent active-draft bridge confirmation (one Cloud run)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
BRIDGE_SETUP_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_delivery_diag=1"
    "&solo_early_bridge=1"
    "&solo_component_diag=1"
    "&solo_diag_timer=10"
)
OUT = ROOT / "data" / "solo_early_bridge_diag.json"
WAIT_EXPIRE_S = 28
EXPECTED_STAGES = (
    "component_declaration_loaded",
    "on_change_callback_entry",
    "session_state_raw_received",
)


BRIDGE_SCRAPE_JS = """() => {
  function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
  let bridge=null;
  const text = roots().map(x=>x.body?x.body.innerText:'').join('\\n');
  for (const x of roots()) {
    const b = x.querySelector('#solo-early-bridge-diag');
    if (b) bridge = {
      present: b.getAttribute('data-present')||'',
      key_before: b.getAttribute('data-key-before')||'',
      key_after: b.getAttribute('data-key-after')||'',
      key_current: b.getAttribute('data-key-current')||'',
      run_before: b.getAttribute('data-run-before')||'',
      run_after: b.getAttribute('data-run-after')||'',
      mount_run: b.getAttribute('data-mount-run')||'',
      expire_run: b.getAttribute('data-expire-run')||'',
      phase: b.getAttribute('data-phase')||'',
      room_active: b.getAttribute('data-room-active')||'',
      room_id: b.getAttribute('data-room-id')||'',
      token: b.getAttribute('data-token')||'',
      stages: b.getAttribute('data-stages')||'',
      reruns: b.getAttribute('data-reruns')||'',
      rerun_log: b.getAttribute('data-rerun-log')||'',
      complete: b.getAttribute('data-complete')||'',
      on_change: b.getAttribute('data-on-change')||'',
      raw_received: b.getAttribute('data-raw-received')||'',
      same_key: b.getAttribute('data-same-key')||'',
    };
  }
  return {
    bridge,
    has_pause: /Pause Draft/i.test(text),
    has_start_setup: /Start New Live Draft/i.test(text),
    room_id: (text.match(/Room ID\\s+([A-F0-9]+)/i)||[])[1]||'',
  };
}"""


def _widget_ids_from_ws(ws_frames: list[dict[str, Any]], key_sub: str) -> tuple[str, str]:
    mount_id = ""
    send_id = ""
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\\s]+)", snippet):
            wid = f"$$ID-{match.group(1)}-{match.group(2)}"
            if key_sub in wid.lower():
                if not mount_id:
                    mount_id = wid
                send_id = wid
        if "DIAGBRIDGE" in snippet and key_sub in snippet.lower():
            for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\\s]+)", snippet):
                wid = f"$$ID-{match.group(1)}-{match.group(2)}"
                send_id = wid
    if mount_id and not send_id:
        send_id = mount_id
    return mount_id, send_id


def _tokens_from_ws(ws_frames: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for frame in ws_frames:
        snip = str(frame.get("snippet") or "")
        for match in re.finditer(r"DIAGBRIDGE\|0\|[0-9.]+", snip):
            out.append(match.group(0))
    return list(dict.fromkeys(out))


def _first_missing_stage(stages: str) -> str:
    for stage in EXPECTED_STAGES:
        if stage not in stages:
            return stage
    return ""


def _parse_rerun_log(raw: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def classify_bridge(
    *,
    draft_ok: bool,
    probe: dict[str, Any],
    ws_frames: list[dict[str, Any]],
) -> tuple[str, str, str]:
    """Returns (verdict, invalid_reason, production_fix_hint)."""
    stages = str(probe.get("stages") or "")
    raw = stages.count("session_state_raw_received")
    oc = stages.count("on_change_callback_entry")
    tokens = _tokens_from_ws(ws_frames)
    mounted = bool(probe.get("key_current") or probe.get("token"))
    room_active = probe.get("room_active") in ("1", "true", True) or bool(probe.get("room_id"))

    fix_if_pass = (
        "Move Solo expiration wake to stable early LDR entry (ldr_page_entry_early_bridge); "
        "keep one persistent widget key across setup→active-draft reruns; let active UI render below."
    )
    fix_if_valid_fail = (
        "Early mount survives active-draft reruns but Python still misses delivery — "
        "inspect on_change wiring at early route before moving production timer."
    )
    fix_if_invalid_rerun = (
        "Active-draft full-page reruns drop early widget registration — "
        "use rerun_log to find the first script_run after bridge_room_became_active where "
        "mount widget ID disappears from WS registration frames."
    )

    if not draft_ok:
        return "invalid", "draft_start_failed", ""
    if not mounted:
        return "invalid", "bridge_probe_never_mounted", ""
    if raw == 1 and oc == 1:
        return "pass", "", fix_if_pass
    if tokens and raw == 0 and oc == 0:
        if room_active:
            return "fail", "", fix_if_valid_fail
        return "invalid", "tokens_without_active_room", ""
    if room_active and mounted and not tokens:
        return "invalid", "active_room_no_outbound_token", fix_if_invalid_rerun
    return "invalid", "inconclusive", ""


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    ws_frames: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": time.time(),
        "setup_url": BRIDGE_SETUP_URL,
        "test": "early_route_persistent_active_draft_bridge",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)
        ws_baseline = len(ws_frames)

        draft = execute_solo_draft_start_workflow(page, BRIDGE_SETUP_URL, navigate=True)
        report["draft_start"] = draft
        report["deploy_sha"] = scrape_live_sha(page)
        draft_ok = bool(draft.get("start_success"))

        pre = page.evaluate(BRIDGE_SCRAPE_JS)
        timeline.append({"ts": time.time(), "phase": "after_draft_start", **pre})

        poll_deadline = time.time() + 90
        last_probe: dict[str, Any] = {}
        while time.time() < poll_deadline:
            snap = page.evaluate(BRIDGE_SCRAPE_JS)
            bridge = dict(snap.get("bridge") or {})
            timeline.append({"ts": time.time(), "phase": "post_start_poll", **snap})
            if bridge.get("token") and bridge.get("key_current"):
                last_probe = bridge
            if bridge.get("room_active") in ("1", "true") and bridge.get("key_after"):
                break
            page.wait_for_timeout(1000)

        expire_deadline = time.time() + WAIT_EXPIRE_S
        while time.time() < expire_deadline:
            snap = page.evaluate(BRIDGE_SCRAPE_JS)
            bridge = dict(snap.get("bridge") or {})
            timeline.append({"ts": time.time(), "phase": "expire_wait", **snap})
            if bridge:
                last_probe = bridge
            stages = str(bridge.get("stages") or "")
            if "on_change_callback_entry" in stages or bridge.get("complete") in ("1", "true"):
                break
            page.wait_for_timeout(1000)

        final_snap = page.evaluate(BRIDGE_SCRAPE_JS)
        probe = dict((final_snap.get("bridge") or last_probe or {}))
        new_ws = ws_frames[ws_baseline:]
        mount_wid, send_wid = _widget_ids_from_ws(new_ws, "micro_bridge")
        tokens = _tokens_from_ws(new_ws)
        stages = str(probe.get("stages") or "")
        reruns = _parse_rerun_log(str(probe.get("rerun_log") or ""))

        verdict, invalid_reason, fix_hint = classify_bridge(
            draft_ok=draft_ok,
            probe=probe,
            ws_frames=new_ws,
        )

        key_before = probe.get("key_before") or ""
        key_after = probe.get("key_after") or probe.get("key_current") or ""
        report["timeline"] = timeline[-40:]
        report["ws_frames"] = new_ws
        report["outbound_tokens"] = tokens
        report["widget_registration"] = {
            "component_key_before_draft_start": key_before,
            "component_key_after_draft_start": key_after,
            "component_key_at_expiration": probe.get("key_current") or "",
            "same_key_before_after": bool(key_before and key_after and key_before == key_after),
            "widget_id_at_registration": mount_wid,
            "widget_id_in_expiration_frame": send_wid,
            "same_widget_registered_inferred": bool(
                mount_wid and send_wid and mount_wid == send_wid
            ),
            "script_run_before_activation": probe.get("run_before") or "",
            "script_run_after_activation": probe.get("run_after") or "",
            "mount_script_run": probe.get("mount_run") or "",
            "expire_script_run": probe.get("expire_run") or "",
        }
        report["reruns_between_mount_and_expiration"] = reruns
        report["session_state_raw_received"] = stages.count("session_state_raw_received")
        report["on_change_callback_count"] = stages.count("on_change_callback_entry")
        report["first_missing_stage"] = _first_missing_stage(stages)
        report["summary"] = {
            "verdict": verdict,
            "invalid_reason": invalid_reason,
            "room_id": draft.get("room_id") or probe.get("room_id") or final_snap.get("room_id") or "",
            "deploy_sha": report.get("deploy_sha") or "",
            "raw_token": probe.get("token") or "",
            "room_active_at_probe": probe.get("room_active") in ("1", "true"),
            "has_pause_ui": final_snap.get("has_pause"),
            "outbound_ws_frame_count": len(new_ws),
            "outbound_token_count": len(tokens),
            "smallest_supported_production_fix": fix_hint,
            "artifact_path": str(OUT),
        }
        browser.close()

    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "summary": report["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
