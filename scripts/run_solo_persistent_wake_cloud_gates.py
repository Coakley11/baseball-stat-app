"""Cloud verification gates for production persistent Solo wake."""

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
PROD_URL = f"{BASE}/?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer=10"
OUT_STAGE1 = ROOT / "data" / "solo_persistent_wake_stage1_one_expire.json"
OUT_STAGE2 = ROOT / "data" / "solo_persistent_wake_stage2_four_expire.json"
OUT_STAGE3 = ROOT / "data" / "solo_persistent_wake_stage3_interactions.json"
OUT_SUMMARY = ROOT / "data" / "solo_persistent_wake_cloud_gates.json"
PERSISTENT_KEY = "solo_countdown_wake_solo_persistent"


def _scrape(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
          let mount=null, chain=null, client=null;
          const text = roots().map(x=>x.body?x.body.innerText:'').join('\\n');
          for (const x of roots()) {
            const m = x.querySelector('#solo-component-mount-diag');
            if (m) mount = {
              key: m.getAttribute('data-key')||'',
              mounted: m.getAttribute('data-mounted')||'',
              diag_timer: m.getAttribute('data-diag-timer')||'',
              token: m.getAttribute('data-token')||'',
            };
            const c = x.querySelector('#solo-expire-chain');
            if (c) chain = {
              owner: c.getAttribute('data-owner')||'',
              chain: c.getAttribute('data-chain')||'',
              commits: c.getAttribute('data-commits')||'',
            };
            for (const cl of x.querySelectorAll('#solo-expire-client')) {
              client = {
                chain: cl.getAttribute('data-chain')||'',
                token: cl.getAttribute('data-token')||'',
                remounts: cl.getAttribute('data-remounts')||'',
              };
            }
          }
          const perPick = (text.match(/solo_countdown_wake_[A-F0-9]+_\\d+/gi)||[]);
          return {
            mount, chain, client, text_len: text.length,
            has_pause: /Pause Draft/i.test(text),
            room_id: (text.match(/Room ID\\s+([A-F0-9]+)/i)||[])[1]||'',
            pick_line: (text.match(/Pick\\s+(\\d+)/i)||[])[1]||'',
            per_pick_keys_in_dom: perPick.slice(0,6),
          };
        }"""
    )


def _chain_stages(chain: dict[str, Any] | None) -> list[str]:
    raw = str((chain or {}).get("chain") or "")
    return [s for s in raw.split("|") if s]


def _start_solo(page, ws_frames: list, baseline: int) -> dict[str, Any]:
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    return execute_solo_draft_start_workflow(page, PROD_URL, navigate=True)


def stage_one(page, ws_frames: list, baseline: int) -> dict[str, Any]:
    draft = _start_solo(page, ws_frames, baseline)
    snap0 = _scrape(page)
    deadline = time.time() + 28
    last = snap0
    commits_before = int((last.get("chain") or {}).get("commits") or 0)
    while time.time() < deadline:
        last = _scrape(page)
        stages = _chain_stages(last.get("chain"))
        if "pick_committed" in stages or "commit_confirmed" in stages:
            break
        if "on_change_callback_entry" in stages or "session_state_raw_received" in stages:
            break
        page.wait_for_timeout(1000)
    stages = _chain_stages(last.get("chain"))
    commits_after = int((last.get("chain") or {}).get("commits") or 0)
    mount = last.get("mount") or {}
    row = {
        "draft_start_ok": bool(draft.get("start_success")),
        "room_id": draft.get("room_id") or last.get("room_id"),
        "mount_key": mount.get("key") or "",
        "persistent_key_ok": (mount.get("key") or "") == PERSISTENT_KEY or PERSISTENT_KEY in str(last.get("per_pick_keys_in_dom")),
        "legacy_per_pick_mount_absent": not any(
            re.search(r"solo_countdown_wake_[A-F0-9]{6,}_\\d+", k, re.I)
            for k in (last.get("per_pick_keys_in_dom") or [])
        ),
        "on_change_seen": "on_change_callback_entry" in stages or "session_state_raw_received" in stages,
        "pick_committed": "pick_committed" in stages or commits_after > commits_before,
        "new_deadline": "new_deadline_installed" in stages,
        "chain_stages": stages[-30:],
        "commits_delta": commits_after - commits_before,
        "client_crossed_zero": "browser_deadline_crossed" in str((last.get("client") or {}).get("chain") or ""),
    }
    ok = (
        row["draft_start_ok"]
        and row["persistent_key_ok"]
        and row["legacy_per_pick_mount_absent"]
        and row["on_change_seen"]
        and row["pick_committed"]
        and row["commits_delta"] <= 1
    )
    row["verdict"] = "pass" if ok else "fail"
    return row


def stage_two(page) -> dict[str, Any]:
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    draft = execute_solo_draft_start_workflow(page, PROD_URL, navigate=True)
    tokens: list[str] = []
    callbacks = 0
    picks = 0
    last_pick = ""
    for cycle in range(4):
        deadline = time.time() + 28
        while time.time() < deadline:
            snap = _scrape(page)
            chain = snap.get("chain") or {}
            stages = _chain_stages(chain)
            if "on_change_callback_entry" in stages:
                callbacks += stages.count("on_change_callback_entry")
            if "pick_committed" in stages:
                picks += 1
            for stg in stages:
                if "token_processed" in stg:
                    pass
            client_tok = str((snap.get("client") or {}).get("token") or "")
            if client_tok and client_tok not in tokens:
                tokens.append(client_tok)
            if picks > cycle:
                last_pick = str(snap.get("pick_line") or last_pick)
                break
            page.wait_for_timeout(1000)
        page.wait_for_timeout(1500)
    row = {
        "draft_start_ok": bool(draft.get("start_success")),
        "callbacks_observed": callbacks,
        "picks_observed": picks,
        "unique_client_tokens": tokens,
        "last_pick_line": last_pick,
        "mount_key": (_scrape(page).get("mount") or {}).get("key") or "",
    }
    row["verdict"] = (
        "pass"
        if row["draft_start_ok"]
        and row["picks_observed"] >= 4
        and len(row["unique_client_tokens"]) >= 4
        and row["mount_key"] == PERSISTENT_KEY
        else "fail"
    )
    return row


def stage_three(page) -> dict[str, Any]:
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    execute_solo_draft_start_workflow(page, PROD_URL, navigate=True)
    notes: list[str] = []
    ok = True

    def click_text(pat: str) -> bool:
        return bool(
            page.evaluate(
                f"""() => {{
                  function roots(){{const o=[document]; for(const f of document.querySelectorAll('iframe')){{try{{o.push(f.contentDocument)}}catch(e){{}}}} return o.filter(Boolean)}}
                  for (const x of roots()) {{
                    for (const b of x.querySelectorAll('button')) {{
                      const t = String(b.innerText||'').replace(/\\s+/g,' ').trim();
                      if (/{pat}/i.test(t) && !b.disabled) {{ b.click(); return true; }}
                    }}
                  }}
                  return false;
                }}"""
            )
        )

    if click_text("Pause Draft"):
        notes.append("pause_clicked")
        page.wait_for_timeout(3000)
        snap = _scrape(page)
        if not snap.get("has_pause"):
            ok = False
            notes.append("pause_ui_missing")
    if click_text("Resume Draft"):
        notes.append("resume_clicked")
        page.wait_for_timeout(4000)
    click_text("Live Draft Room")
    notes.append("sidebar_ldr_reclick")
    page.wait_for_timeout(5000)
    snap = _scrape(page)
    mount = snap.get("mount") or {}
    row = {
        "notes": notes,
        "room_id_after_nav": snap.get("room_id") or "",
        "mount_key": mount.get("key") or "",
        "has_pause_after": snap.get("has_pause"),
        "verdict": "pass" if ok and mount.get("key") == PERSISTENT_KEY else "fail",
    }
    return row


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {"started_at": time.time(), "prod_url": PROD_URL}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)
        baseline = len(ws_frames)
        report["deploy_sha"] = scrape_live_sha(page)
        s1 = stage_one(page, ws_frames, baseline)
        OUT_STAGE1.write_text(json.dumps(s1, indent=2), encoding="utf-8")
        s2 = stage_two(page)
        OUT_STAGE2.write_text(json.dumps(s2, indent=2), encoding="utf-8")
        s3 = stage_three(page)
        OUT_STAGE3.write_text(json.dumps(s3, indent=2), encoding="utf-8")
        report["stage1_one_expire"] = s1
        report["stage2_four_expire"] = s2
        report["stage3_interactions"] = s3
        report["supabase_egress"] = {"note": "idle_egress_not_instrumented_in_gate_script"}
        report["finished_at"] = time.time()
        browser.close()
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
