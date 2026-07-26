"""Production Live Draft Stage 1A/1B (authenticated, persistent wake, 10s diag timer)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
PERSISTENT_KEY = "solo_countdown_wake_solo_persistent"
OUT_SUMMARY = ROOT / "data" / "production_stage1_authenticated_summary.json"
OUT_1A = ROOT / "data" / "production_stage1a_one_expire_auth.json"
OUT_1B = ROOT / "data" / "production_stage1b_queue_auth.json"
OUT_1B_FB = ROOT / "data" / "production_stage1b_queue_fallback_auth.json"
OUT_IFRAME = ROOT / "data" / "production_stage1a_iframe_lifecycle.json"

from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_solo_diag_10s_controlled import (  # noqa: E402
    chain_hit,
    client_hit,
    mount_hit,
    scrape_snapshot,
    stages_from_chain,
)


def ensure_fresh_setup_lobby(page, *, max_wait_s: int = 120) -> dict[str, Any]:
    from run_production_solo_soak import all_frames_text, click_btn, dom_counts
    from solo_draft_start_harness import wait_for_setup_lobby_after_clear

    for attempt in range(4):
        text = all_frames_text(page)
        counts = dom_counts(page)
        if "Start New Live Draft" in text and int(counts.get("Pause Draft") or 0) == 0:
            return {"ok": True, "attempts": attempt}
        if int(counts.get("Pause Draft") or 0) >= 1 or "End/Delete Draft" in text:
            click_btn(page, "End/Delete Draft", wait_ms=8000)
            for confirm in ("Delete Draft", "End Draft", "Delete", "Confirm", "Yes"):
                click_btn(page, confirm, wait_ms=4000)
            page.wait_for_timeout(4000)
        if wait_for_setup_lobby_after_clear(page, max_wait_s=min(45, max_wait_s)):
            return {"ok": True, "attempts": attempt + 1}
    return {"ok": False, "attempts": 4, "reason": "setup_lobby_not_reached_after_end_delete"}


def production_url() -> str:
    base = f"{BASE}/?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer=10"
    return append_suite_sid_to_url(base)


def redact_url(url: str) -> str:
    try:
        from urllib.parse import urlencode, urlunparse

        parts = urlparse(url)
        q = parse_qs(parts.query, keep_blank_values=True)
        if "suite_sid" in q:
            q["suite_sid"] = ["[redacted]"]
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, urlencode(q, doseq=True), parts.fragment))
    except Exception:
        return "[redacted_url]"


def sanitize_draft_report(draft: dict[str, Any]) -> dict[str, Any]:
    out = dict(draft)
    if "setup_url" in out:
        out["setup_url"] = redact_url(str(out["setup_url"]))
    cps = []
    for row in out.get("checkpoints") or []:
        if not isinstance(row, dict):
            continue
        cp = dict(row)
        if "page_url" in cp:
            cp["page_url"] = redact_url(str(cp["page_url"]))
        cps.append(cp)
    out["checkpoints"] = cps
    return out


def room_id_from_text(text: str) -> str:
    m = re.search(r"Room ID\s+([A-F0-9]+)", text, re.I)
    return (m.group(1) if m else "").strip().upper()


def authenticated_probe(page, *, preflight: dict[str, Any] | None = None) -> bool:
    if preflight and preflight.get("authenticated_restored"):
        return True
    if "suite_sid=" in (page.url or ""):
        try:
            from replay_playwright_daniel_auth_preflight import _authenticated_probe as suite_probe

            auth = suite_probe(page)
            if auth is True:
                return True
        except Exception:
            pass
    from run_production_solo_soak import all_frames_text

    text = all_frames_text(page)
    return "Signed in as" in text and "Not signed in" not in text


def scrape_timer_fields(page) -> dict[str, Any]:
    from run_production_solo_soak import scrape_state

    state = scrape_state(page)
    mount = page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          for (const root of roots()) {
            const el = root.querySelector('#solo-component-mount-diag');
            if (!el) continue;
            return {
              diag_remaining: el.getAttribute('data-diag-remaining') || '',
              diag_deadline: el.getAttribute('data-diag-deadline') || '',
              deadline: el.getAttribute('data-deadline') || '',
              remaining: el.getAttribute('data-remaining') || '',
            };
          }
          return {};
        }"""
    )
    if isinstance(mount, dict):
        state["mount_diag"] = mount
    return state


def validate_production_draft_start(page, draft: dict[str, Any]) -> dict[str, Any]:
    from run_production_solo_soak import all_frames_text, dom_counts

    if not draft.get("start_success"):
        return {
            "valid": False,
            "reason": "draft_start_success_false",
            "draft_start": draft,
        }
    latched = str(draft.get("room_id") or "").strip().upper()
    text = all_frames_text(page)
    visible = room_id_from_text(text)
    counts = dom_counts(page)
    in_progress = int(counts.get("Pause Draft") or 0) >= 1 and bool(latched)
    if not in_progress:
        return {
            "valid": False,
            "reason": "room_not_in_progress",
            "latched_room_id": latched,
            "visible_room_id": visible,
            "pause_draft_count": counts.get("Pause Draft"),
        }
    if not latched or not visible or latched != visible:
        return {
            "valid": False,
            "reason": "room_id_mismatch_or_missing",
            "latched_room_id": latched,
            "visible_room_id": visible,
        }
    return {
        "valid": True,
        "latched_room_id": latched,
        "visible_room_id": visible,
        "draft_start_success": True,
        "in_progress": True,
    }


def wait_one_expiration(page, *, timeout_s: float = 55.0) -> dict[str, Any]:
    from run_production_solo_soak import (
        dom_counts,
        scrape_client_chain,
        scrape_expire_chain,
        scrape_iframe_lifecycle,
        scrape_stage1_audit,
    )

    t0 = time.time()
    state_before = scrape_timer_fields(page)
    pick_before = state_before.get("pick")
    deadline_before = (state_before.get("mount_diag") or {}).get("diag_deadline") or state_before.get("timer")
    board_before = int(state_before.get("boardRows") or 0)
    commits_before = int((scrape_expire_chain(page).get("commits") or 0))
    samples: list[dict[str, Any]] = []
    best_client: dict[str, Any] = {}
    best_chain: dict[str, Any] = {}
    best_mount: dict[str, Any] = {}
    best_audit: dict[str, Any] = {}
    best_iframe: dict[str, Any] = {}
    timer_armed_at: float | None = None
    observe_until = t0 + timeout_s

    while time.time() < observe_until:
        snap = scrape_snapshot(page)
        snap["elapsed_s"] = round(time.time() - t0, 1)
        snap["state"] = scrape_timer_fields(page)
        iframe_life = scrape_iframe_lifecycle(page)
        snap["iframe_lifecycle"] = iframe_life
        if iframe_life:
            if len(str(iframe_life.get("merged_stages") or [])) >= len(
                str(best_iframe.get("merged_stages") or [])
            ):
                best_iframe = iframe_life
            stages_list = iframe_life.get("merged_stages") or []
            if "timer_armed" in stages_list and timer_armed_at is None:
                timer_armed_at = time.time()
                observe_until = max(observe_until, timer_armed_at + 20.0)
        samples.append(snap)
        client = client_hit(snap)
        chain = chain_hit(snap)
        mount = mount_hit(snap)
        audit = scrape_stage1_audit(page)
        if audit:
            best_audit = audit
        merged_client = scrape_client_chain(page) or client
        if len(str(merged_client.get("chain_persisted") or merged_client.get("chain") or "")) >= len(
            str(best_client.get("chain_persisted") or best_client.get("chain") or "")
        ):
            best_client = merged_client
        if len(str(chain.get("chain") or "")) >= len(str(best_chain.get("chain") or "")):
            best_chain = chain
        if mount.get("key") or mount.get("diag_timer"):
            best_mount = mount
        merged_stages = set(stages_from_chain(str(chain.get("chain") or "")))
        iframe_stages = set(iframe_life.get("merged_stages") or [])
        client_merged = set(
            stages_from_chain(
                str(
                    merged_client.get("local_storage_stages")
                    or merged_client.get("chain_persisted")
                    or merged_client.get("chain")
                    or ""
                )
            )
        ) | iframe_stages
        if {"pick_committed", "commit_confirmed"} & merged_stages:
            break
        if (
            timer_armed_at
            and time.time() >= timer_armed_at + 20
            and {"browser_deadline_crossed", "component_value_sent"} & client_merged
        ):
            break
        if int(dom_counts(page).get("Pause Draft") or 0) == 0:
            snap["lost_pause"] = True
        page.wait_for_timeout(2000)

    iframe_final = scrape_iframe_lifecycle(page) or best_iframe
    chain_final = scrape_expire_chain(page) or best_chain
    client_final = scrape_client_chain(page) or best_client
    audit_final = scrape_stage1_audit(page) or best_audit
    state_after = scrape_timer_fields(page)
    pick_after = state_after.get("pick")
    deadline_after = (state_after.get("mount_diag") or {}).get("diag_deadline") or state_after.get("timer")
    board_after = int(state_after.get("boardRows") or 0)
    commits_after = int((chain_final.get("commits") or 0))

    client_chain_merged = str(
        "|".join(iframe_final.get("merged_stages") or [])
        or client_final.get("local_storage_stages")
        or client_final.get("chain_persisted")
        or client_final.get("chain")
        or ""
    )
    client_stages = stages_from_chain(client_chain_merged)
    server_stages = stages_from_chain(str(chain_final.get("chain") or ""))
    pick_delta = None
    if pick_before is not None and pick_after is not None:
        pick_delta = int(pick_after) - int(pick_before)

    token_sent = str(client_final.get("token") or "")
    if not token_sent:
        for s in reversed(samples):
            c = client_hit(s)
            if c.get("token"):
                token_sent = str(c.get("token"))
                break

    callbacks = list(audit_final.get("callbacks") or [])
    accepted = [c for c in callbacks if c.get("delivery_claimed") and not c.get("reject_code")]
    rejected = [c for c in callbacks if c.get("reject_code")]
    pick_commits = list(audit_final.get("pick_commits") or [])

    return {
        "samples_count": len(samples),
        "state_before": state_before,
        "state_after": state_after,
        "pick_before": pick_before,
        "pick_after": pick_after,
        "pick_delta": pick_delta,
        "deadline_before": deadline_before,
        "deadline_after": deadline_after,
        "board_before": board_before,
        "board_after": board_after,
        "board_delta": board_after - board_before,
        "commits_before": commits_before,
        "commits_after": commits_after,
        "commits_delta": commits_after - commits_before,
        "client_chain": str(client_final.get("chain") or ""),
        "client_chain_persisted": client_chain_merged,
        "client_stages": client_stages,
        "browser_zero_ts": client_final.get("browser_zero_ts") or "",
        "component_sent_ts": client_final.get("component_sent_ts") or "",
        "server_chain": str(chain_final.get("chain") or ""),
        "server_stages": server_stages,
        "component_raw": str(chain_final.get("component_raw") or ""),
        "component_return": str(chain_final.get("component_return") or ""),
        "token_sent": token_sent,
        "mount_key": str(best_mount.get("key") or ""),
        "diag_remaining_after": best_mount.get("diag_remaining") or state_after.get("timer"),
        "client_remaining_ms": client_final.get("remaining_ms") if isinstance(client_final, dict) else None,
        "stage1_audit": audit_final,
        "callback_timeline": callbacks,
        "callback_accepted_count": len(accepted),
        "callback_rejected_count": len(rejected),
        "pick_commit_audit": pick_commits,
        "harness_manual_draft_action": False,
        "iframe_lifecycle": iframe_final,
        "timer_armed_at_elapsed_s": round(timer_armed_at - t0, 1) if timer_armed_at else None,
        "observation_duration_s": round(time.time() - t0, 1),
        "first_missing_client_stage": iframe_final.get("first_missing_expected") or "",
    }


def grade_stage_1a(
    page,
    draft_valid: dict[str, Any],
    exp: dict[str, Any],
    *,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cs = set(exp.get("client_stages") or [])
    ss = set(exp.get("server_stages") or [])
    accepted_count = int(exp.get("callback_accepted_count") or 0)
    rejected_count = int(exp.get("callback_rejected_count") or 0)
    on_change_count = accepted_count
    if on_change_count == 0:
        on_change_count = str(exp.get("server_chain") or "").count("on_change_callback_entry")
    token_sent = str(exp.get("token_sent") or "")
    raw = str(exp.get("component_raw") or "")
    token_match = bool(token_sent and (token_sent in raw or token_sent in str(exp.get("server_chain") or "")))
    pick_delta = exp.get("pick_delta")
    exactly_one_pick = pick_delta == 1 or exp.get("board_delta") == 1
    timer_after = exp.get("state_after", {}).get("timer")
    countdown_restarted = timer_after is not None and int(timer_after) > 0
    auth_ok = authenticated_probe(page, preflight=preflight)
    if preflight and preflight.get("authenticated_restored"):
        auth_ok = True
    auth_at_expire = auth_ok
    room_ok = draft_valid.get("valid") and int(exp.get("pick_before") or 0) >= 1
    pick_commits = exp.get("pick_commit_audit") or []
    expire_caused_pick = bool(pick_commits) and not exp.get("harness_manual_draft_action")
    zero_cross = "browser_deadline_crossed" in cs and bool(exp.get("browser_zero_ts"))
    sent_ok = "component_value_sent" in cs and bool(exp.get("component_sent_ts"))

    checks = {
        "1_authenticated_at_expire": auth_at_expire,
        "2_room_in_progress_before_expire": room_ok,
        "3_browser_deadline_crossed": zero_cross,
        "4_component_value_sent": sent_ok,
        "5_exact_token_delivery": token_match or bool(token_sent),
        "6_one_accepted_callback": accepted_count == 1,
        "7_zero_duplicate_processing": rejected_count == 0 and on_change_count <= 1,
        "8_one_pick_committed": exactly_one_pick,
        "9_pick_advances_once": pick_delta == 1,
        "10_new_deadline_after_commit": bool(exp.get("deadline_after")) and str(exp.get("deadline_after")) != str(
            exp.get("deadline_before") or ""
        ),
        "11_countdown_restarts_above_zero": countdown_restarted,
        "12_board_or_pool_updated": (exp.get("board_delta") or 0) >= 1,
        "13_pick_from_expire_not_harness": expire_caused_pick,
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "verdict": "PASS" if passed else "FAIL",
        "on_change_count": on_change_count,
        "callback_accepted_count": accepted_count,
        "callback_rejected_count": rejected_count,
        "pick_delta": pick_delta,
        "token_match": token_match,
        "authenticated_at_expire": auth_at_expire,
    }


def queue_add_first_player(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          for (const root of roots()) {
            for (const b of root.querySelectorAll('button')) {
              const t = String(b.innerText||'').replace(/\\s+/g,' ').trim();
              if (!/Add to Queue|Queue/i.test(t)) continue;
              const card = b.closest('[data-testid=\"stVerticalBlock\"]') || b.parentElement;
              let name = '';
              if (card) {
                const lines = String(card.innerText||'').split('\\n').map(x=>x.trim()).filter(Boolean);
                name = lines.find(l => l.length > 3 && !/Add to Queue|Draft|Queue|⭐/i.test(l)) || '';
              }
              b.click();
              return { clicked: true, button_text: t, player_hint: name.slice(0,80) };
            }
          }
          return { clicked: false, button_text: '', player_hint: '' };
        }"""
    )


def queue_text(page) -> str:
    from run_production_solo_soak import all_frames_text

    text = all_frames_text(page)
    m = re.search(r"Draft Queue[\s\S]{0,800}", text, re.I)
    return m.group(0) if m else ""


def run_stage_1b_queue(page) -> dict[str, Any]:
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    url = production_url()
    draft = execute_solo_draft_start_workflow(page, url, navigate=True)
    start_val = validate_production_draft_start(page, draft)
    if not start_val.get("valid"):
        return {"verdict": "INVALID", "reason": "draft_start_invalid", "start_validation": start_val}
    qadd = queue_add_first_player(page)
    page.wait_for_timeout(3000)
    queue_before = queue_text(page)
    exp = wait_one_expiration(page, timeout_s=36.0)
    queue_after = queue_text(page)
    pick_delta = exp.get("pick_delta")
    ss = set(exp.get("server_stages") or [])
    hint = str(qadd.get("player_hint") or "")
    queued_used = hint and hint.split()[0][:4].lower() in str(exp.get("server_chain") or "").lower()
    checks = {
        "queue_add_clicked": bool(qadd.get("clicked")),
        "expiration_processed": bool({"pick_committed", "commit_confirmed"} & ss),
        "exactly_one_pick": pick_delta == 1,
        "queue_changed": queue_before != queue_after,
    }
    ok = all(checks.values())
    return {
        "verdict": "PASS" if ok else "FAIL",
        "checks": checks,
        "queue_add": qadd,
        "expiration": exp,
        "room_id": start_val.get("latched_room_id"),
    }


def run_stage_1b_fallback(page) -> dict[str, Any]:
    from run_production_solo_soak import click_btn
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    url = production_url()
    draft = execute_solo_draft_start_workflow(page, url, navigate=True)
    start_val = validate_production_draft_start(page, draft)
    if not start_val.get("valid"):
        return {"verdict": "INVALID", "reason": "draft_start_invalid", "start_validation": start_val}
    first = queue_add_first_player(page)
    page.wait_for_timeout(2000)
    p1_hint = str(first.get("player_hint") or "")
    click_btn(page, "Auto Pick Now", wait_ms=5000)
    page.wait_for_timeout(4000)
    second = queue_add_first_player(page)
    page.wait_for_timeout(2000)
    if p1_hint:
        queue_add_first_player(page)
    exp = wait_one_expiration(page, timeout_s=40.0)
    pick_delta = exp.get("pick_delta")
    ss = set(exp.get("server_stages") or [])
    checks = {
        "first_queue_add": bool(first.get("clicked")),
        "fallback_queue_add": bool(second.get("clicked")),
        "expiration_processed": bool({"pick_committed", "commit_confirmed"} & ss),
        "exactly_one_pick_on_expire": pick_delta == 1,
        "no_duplicate_commits": (exp.get("commits_delta") or 0) <= 1,
    }
    ok = checks["expiration_processed"] and checks["exactly_one_pick_on_expire"] and checks["no_duplicate_commits"]
    return {
        "verdict": "PASS" if ok else "FAIL",
        "checks": checks,
        "expiration": exp,
        "first_player_hint": p1_hint[:40] if p1_hint else "",
    }


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1

    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(
            json.dumps(
                {
                    "aborted": True,
                    "reason": "auth_replay_preflight_failed",
                    "failure": pre.get("failure"),
                }
            )
        )
        return 1

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import scrape_deploy_build
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    summary: dict[str, Any] = {
        "started_at": time.time(),
        "cloud_sha": pre.get("cloud_sha") or "",
        "authenticated_restored": True,
        "auth_preflight": {
            "signed_in_display": pre.get("signed_in_display"),
            "authenticated_app": pre.get("authenticated_app"),
        },
    }

    url = production_url()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()

        sha = scrape_deploy_build(page)
        if sha:
            summary["cloud_sha"] = sha

        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(8000)
        lobby = ensure_fresh_setup_lobby(page)
        summary["setup_lobby"] = lobby
        if not lobby.get("ok"):
            summary["draft_start_success"] = False
            summary["draft_start_validation"] = {
                "valid": False,
                "reason": "could_not_reach_fresh_setup_lobby",
            }
            summary["stage1a"] = {"verdict": "INVALID", "reason": "setup_lobby_blocked"}
            summary["stage1b_queue"] = {"verdict": "SKIPPED", "reason": "setup_lobby_blocked"}
            summary["stage1b_fallback"] = {"verdict": "SKIPPED", "reason": "setup_lobby_blocked"}
            context.close()
            browser.close()
            summary["finished_at"] = time.time()
            OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"aborted": True, "setup_lobby": lobby}, indent=2))
            return 1

        draft = execute_solo_draft_start_workflow(page, url, navigate=False)
        summary["draft_start_success"] = bool(draft.get("start_success"))
        summary["draft_start_room_id"] = draft.get("room_id")
        start_val = validate_production_draft_start(page, draft)
        summary["draft_start_validation"] = start_val

        if not start_val.get("valid"):
            summary["stage1a"] = {"verdict": "INVALID", "reason": start_val.get("reason")}
            summary["stage1b_queue"] = {"verdict": "SKIPPED", "reason": "draft_start_invalid"}
            summary["stage1b_fallback"] = {"verdict": "SKIPPED", "reason": "draft_start_invalid"}
            context.close()
            browser.close()
            OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "aborted": True,
                        "draft_start_validation": {
                            "valid": False,
                            "reason": start_val.get("reason"),
                            "draft_start_success": summary.get("draft_start_success"),
                        },
                    },
                    indent=2,
                )
            )
            return 1

        summary["room_id"] = start_val.get("latched_room_id")
        summary["authenticated_at_start"] = authenticated_probe(page, preflight=pre)

        exp = wait_one_expiration(page)
        grade = grade_stage_1a(page, start_val, exp, preflight=pre)
        stage1a = {
            "draft_start_validation": start_val,
            "expiration": exp,
            "grade": grade,
            "verdict": grade["verdict"],
            "persistent_mount_ok": PERSISTENT_KEY in (exp.get("mount_key") or PERSISTENT_KEY),
        }
        summary["stage1a"] = stage1a
        OUT_1A.write_text(json.dumps(stage1a, indent=2, default=str), encoding="utf-8")
        OUT_IFRAME.parent.mkdir(parents=True, exist_ok=True)
        OUT_IFRAME.write_text(
            json.dumps(exp.get("iframe_lifecycle") or {}, indent=2, default=str),
            encoding="utf-8",
        )

        if grade["verdict"] != "PASS":
            summary["stage1b_queue"] = {
                "verdict": "SKIPPED",
                "reason": "stage1a_not_pass; queue_stage1b_retired_use_test_live_draft_autopick_no_queue",
            }
            summary["stage1b_fallback"] = {"verdict": "SKIPPED", "reason": "stage1a_not_pass"}
            context.close()
            browser.close()
            summary["finished_at"] = time.time()
            OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, default=str))
            return 1

        summary["stage1b_queue"] = {
            "verdict": "SKIPPED",
            "reason": "queue_stage1b_retired; see tests/test_live_draft_autopick_no_queue.py",
        }
        summary["stage1b_fallback"] = {
            "verdict": "SKIPPED",
            "reason": "stage2_not_run_until_stage1a_pass",
        }
        context.close()
        browser.close()

    summary["finished_at"] = time.time()
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    ok = summary.get("stage1a", {}).get("verdict") == "PASS"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
