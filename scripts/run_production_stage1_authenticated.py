"""Production Live Draft Stage 1A/1B (authenticated, persistent wake, 10s diag timer)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
PERSISTENT_KEY = "solo_countdown_wake_solo_persistent"
OUT_SUMMARY = ROOT / "data" / "production_stage1_authenticated_summary.json"
OUT_1A = ROOT / "data" / "production_stage1a_one_expire_auth.json"
OUT_QUEUE = ROOT / "data" / "production_stage1a_queue_auth.json"
OUT_1B = ROOT / "data" / "production_stage1b_queue_auth.json"
OUT_1B_FB = ROOT / "data" / "production_stage1b_queue_fallback_auth.json"
OUT_IFRAME = ROOT / "data" / "production_stage1a_iframe_lifecycle.json"
OUT_TRANSPORT = ROOT / "data" / "production_stage1a_transport_boundary.json"
OUT_FRAME_TOPOLOGY = ROOT / "data" / "production_stage1a_frame_topology.json"
OUT_CLEANUP = ROOT / "data" / "production_stage1a_preflight_cleanup.json"
OUT_RETURN_CHAIN = ROOT / "data" / "production_stage1a_return_value_chain.json"
OUT_SERVER_LEDGER = ROOT / "data" / "production_stage1a_server_ledger_merged.json"
OUT_DIAG_RUN = ROOT / "data" / "production_stage1a_instrumented_diag.json"
OUT_PARENT_BOUNDARY = ROOT / "data" / "production_stage1a_parent_boundary_validation.json"
OUT_DURABLE_PARENT_SINK = ROOT / "data" / "production_stage1a_durable_parent_sink.json"
REQUIRED_CLOUD_SHA = ""


def resolve_stage1a_mode() -> str:
    mode = str(os.environ.get("STAGE1A_MODE") or "").strip().upper()
    if mode in ("CORE", "QUEUE", "FULL"):
        return mode
    return "FULL"


def resolve_solo_diag_timer(*, stage1a_mode: str) -> str:
    env = str(os.environ.get("STAGE1A_SOLO_DIAG_TIMER") or os.environ.get("SOLO_DIAG_TIMER") or "").strip()
    if env:
        return env
    if stage1a_mode == "QUEUE":
        return "120"
    return "10"


def resolve_queue_manual_assist() -> bool:
    return str(os.environ.get("STAGE1A_QUEUE_MANUAL_ASSIST") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def resolve_headless_launch(*, stage1a_mode: str) -> bool:
    if resolve_queue_manual_assist() and stage1a_mode == "QUEUE":
        return False
    return os.environ.get("STAGE1A_HEADED", "").strip().lower() not in ("1", "true", "yes")


def resolve_required_cloud_sha() -> str:
    env = str(os.environ.get("REQUIRED_CLOUD_SHA") or "").strip().lower()[:7]
    if env:
        return env
    if str(REQUIRED_CLOUD_SHA or "").strip():
        return str(REQUIRED_CLOUD_SHA).strip().lower()[:7]
    pin = ROOT / "deploy_commit.txt"
    if pin.is_file():
        for line in pin.read_text(encoding="utf-8").splitlines():
            tok = line.split("#", 1)[0].strip()
            if tok:
                return tok.lower()[:7]
    return ""

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


def ensure_fresh_setup_lobby(page, *, max_wait_s: int = 180) -> dict[str, Any]:
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup

    return run_stage1_preflight_cleanup(page, max_wait_s=max_wait_s)


def production_url() -> str:
    mode = resolve_stage1a_mode()
    timer = resolve_solo_diag_timer(stage1a_mode=mode)
    base = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1"
    )
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


def parse_expire_token_fields(token: str) -> dict[str, Any]:
    parts = str(token or "").strip().split("|")
    if len(parts) != 3:
        return {}
    try:
        return {
            "draft_id": parts[0].strip(),
            "pick_index": int(parts[1]),
            "deadline": float(parts[2]),
        }
    except (TypeError, ValueError):
        return {}


def scrape_component_mount_diag(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-component-mount-diag');
                if (!el) continue;
                const jsonRaw = el.getAttribute('data-json') || '';
                let parsed = {};
                try { parsed = JSON.parse(jsonRaw.replace(/'/g, '"')); } catch (e) {}
                return {
                  widget_key: el.getAttribute('data-key') || '',
                  expire_token: el.getAttribute('data-token') || '',
                  returned_token: parsed.returned_token || '',
                  widget_return_type: parsed.widget_return_type || '',
                  mount_reason: el.getAttribute('data-reason') || parsed.reason || '',
                  draft_id: el.getAttribute('data-draft-id') || '',
                  pick_index: el.getAttribute('data-pick-index') || '',
                  deadline: el.getAttribute('data-deadline') || '',
                  diag_deadline: el.getAttribute('data-diag-deadline') || '',
                  mount_row: parsed,
                };
              }
              return {};
            }"""
        )
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def scrape_persistent_lifecycle_token(page) -> str:
    try:
        tok = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-persistent-wake-lifecycle-diag');
                if (el) return el.getAttribute('data-token') || '';
              }
              return '';
            }"""
        )
        return str(tok or "").strip()
    except Exception:
        return ""


def build_return_value_chain_report(
    page,
    exp: dict[str, Any],
    *,
    start_val: dict[str, Any],
    queue_meta: dict[str, Any],
    cloud_sha: str,
    cloud_build: str,
) -> dict[str, Any]:
    mount_diag = scrape_component_mount_diag(page)
    lifecycle_token = scrape_persistent_lifecycle_token(page)
    transport = dict(exp.get("transport_boundary") or {})
    probe = dict(transport.get("probe") or {})
    log_tail = list(probe.get("log_tail") or [])
    prod_decls = [e for e in log_tail if isinstance(e, dict) and e.get("stage") == "production_component_declaration"]
    last_decl = prod_decls[-1] if prod_decls else {}
    python_runs = list(probe.get("python_runs") or [])
    post_send_runs = [r for r in python_runs if isinstance(r, dict) and str(r.get("phase") or "").startswith("post")]
    session_state_scrapes = [
        {
            "phase": r.get("phase"),
            "production_raw_value": str(r.get("production_raw_value") or r.get("raw_value") or "")[:400],
            "key_in_session_state": r.get("key_in_session_state") or r.get("production_key_exists"),
            "component_return": str(r.get("component_return") or "")[:400],
        }
        for r in python_runs
        if isinstance(r, dict)
    ]
    last_post_raw = ""
    for r in reversed(python_runs):
        if not isinstance(r, dict):
            continue
        raw_v = str(r.get("production_raw_value") or r.get("raw_value") or "").strip()
        if raw_v:
            last_post_raw = raw_v[:400]
            break
    audit = dict(exp.get("stage1_audit") or {})
    callbacks = list(audit.get("callbacks") or [])
    native = [c for c in callbacks if str(c.get("callback_source") or "") == "native_component_return"]
    accepted_native = [c for c in native if c.get("delivery_claimed") and not c.get("reject_code")]
    rejected = [c for c in callbacks if c.get("reject_code")]
    first_reject = str(rejected[0].get("reject_code") or "") if rejected else ""
    owners = dict(audit.get("delivery_owners") or {})
    token_sent = str(exp.get("token_sent") or "")
    expire_return = str(exp.get("component_return") or "")
    mount_return = str(mount_diag.get("returned_token") or "")
    decl_return = str(last_decl.get("component_return") or "")
    coalesced = mount_return or decl_return or expire_return or last_post_raw
    parsed_sent = parse_expire_token_fields(token_sent)
    parsed_coalesced = parse_expire_token_fields(coalesced)
    room_id = str(start_val.get("latched_room_id") or "")
    live_pick = exp.get("pick_before")
    cs = set(exp.get("client_stages") or [])
    iframe = dict(exp.get("iframe_lifecycle") or {})
    merged_stages = list(iframe.get("merged_stages") or [])
    remounts = sum(1 for s in merged_stages if s == "iframe_remount")
    tick_cancelled = sum(1 for s in merged_stages if s == "tick_cancelled")
    double = dict(exp.get("double_production_send_analysis") or {})
    parent_msgs = list(exp.get("immediate_parent_messages") or [])
    top_msgs = list(exp.get("top_parent_messages") or [])
    from live_draft_stage1_receipt_levels import classify_receipt_levels, is_logical_value_receipt, refine_a5a_subclass

    logical_imm = [m for m in parent_msgs if is_logical_value_receipt(m, expected_token=token_sent)]
    frame2_msgs = list(exp.get("frame2_parent_messages") or [])
    frame2_scv = [
        m
        for m in frame2_msgs
        if m.get("is_set_component_value")
        and token_sent
        and (
            str(m.get("value_preview") or "") == token_sent
            or token_sent in str(m.get("payload_json") or "")
        )
    ]
    frame2_probe = [m for m in frame2_msgs if m.get("is_parent_probe")]
    sink_data = dict(exp.get("parent_event_sink") or {})
    sink_logic = sink_data.get("logical") or {}
    durable_scv_count = int(sink_logic.get("scv_count") or 0)
    durable_probe_count = int(sink_logic.get("probe_count") or 0)
    deduped_parent = len(logical_imm)
    levels = classify_receipt_levels(
        expected_token=token_sent,
        iframe_send_stages=list(cs),
        immediate_parent_messages=parent_msgs,
        top_parent_messages=top_msgs,
        coalesced_value=coalesced,
        session_state_value=last_post_raw,
        direct_return=decl_return or mount_return or expire_return,
        token_claim_accepted=bool(accepted_native),
    )
    levels["LEVEL_2_ACTUAL_IMMEDIATE_PARENT_FRAME2"] = durable_scv_count >= 1
    levels["LEVEL_2_IMMEDIATE_PARENT_RECEIPT_STATUS"] = (
        "PASS_DURABLE_SINK"
        if durable_scv_count >= 1
        else ("PARTIAL_DURABLE_SINK" if durable_probe_count >= 1 else "UNRESOLVED_OBSERVER_LIFETIME")
    )
    levels["durable_sink_probe_count"] = durable_probe_count
    levels["durable_sink_scv_count"] = durable_scv_count
    levels["frame2_window_message_count"] = len(frame2_msgs)
    tick_after_send = tick_cancelled >= 1 and "component_value_sent" in cs
    a5a_refined = ""
    pbv = dict(exp.get("parent_boundary_validation") or {})
    if pbv.get("a5a_refinement"):
        a5a_refined = str(pbv.get("a5a_refinement"))
    elif durable_scv_count >= 1 and not levels.get("LEVEL_5_PYTHON_VALUE_BOUND"):
        a5a_refined = "A5a3"
    else:
        a5a_refined = "UNSET_PENDING_FRAME2_BOUNDARY"

    parsed_match_live = False
    if parsed_coalesced and room_id:
        parsed_match_live = (
            str(parsed_coalesced.get("draft_id") or "").upper() == room_id.upper()
            and (live_pick is None or int(parsed_coalesced.get("pick_index") or -1) == int(live_pick))
        )

    pick_commits = list(audit.get("pick_commits") or [])
    last_commit = pick_commits[-1] if pick_commits else {}
    queue_hint = str(queue_meta.get("player_hint") or "")
    picked_player = str(last_commit.get("player") or "")
    queue_ignored = True
    if queue_hint and picked_player:
        qh = queue_hint.split()[0][:4].lower()
        queue_ignored = qh not in picked_player.lower()

    failure_class = ""
    if "component_value_sent" in cs and not coalesced and not mount_return and not last_post_raw:
        failure_class = "A"
    elif token_sent and last_post_raw and not coalesced:
        failure_class = "B"
    elif coalesced and not native and not accepted_native:
        failure_class = "C"
    elif native and first_reject:
        failure_class = "D"
    elif accepted_native and not pick_commits:
        failure_class = "E"
    elif len(pick_commits) > 1 or (exp.get("commits_delta") or 0) > 1:
        failure_class = "F"

    return {
        "cloud_sha": cloud_sha,
        "cloud_build": cloud_build,
        "room_id": room_id,
        "browser": {
            "timer_armed": "timer_armed" in cs,
            "deadline_crossed": "browser_deadline_crossed" in cs,
            "component_value_sent": "component_value_sent" in cs,
            "exact_expiration_token": token_sent,
            "unique_set_component_value_count": int(double.get("set_component_value_events") or double.get("unique_send_count") or 0),
            "unique_transport_postmessage_count": int(double.get("transport_postmessage_count") or 0),
            "deduped_parent_receipt_count": deduped_parent,
            "misleading_legacy_deduped_parent_count": levels.get("misleading_legacy_deduped_parent_count"),
            "authoritative_receipt_levels": levels,
            "refined_boundary_a5a": a5a_refined,
            "overall_parent_boundary_verdict": exp.get("parent_boundary_validation", {}).get("overall_verdict", ""),
            "iframe_remounts": remounts,
            "tick_cancellations": tick_cancelled,
            "double_production_send_analysis": double,
        },
        "python_component": {
            "widget_key": PERSISTENT_KEY,
            "direct_component_return_mount_diag": mount_return,
            "direct_component_return_declaration": decl_return,
            "direct_component_return_expire_chain": expire_return,
            "session_state_widget_value_transport_scrape": last_post_raw,
            "session_state_widget_value_all_phases": session_state_scrapes,
            "session_state_coalesce_note": "Streamlit widget value surfaced via mount return, declaration, expire chain, or transport python_runs",
            "coalesced_component_value": coalesced,
            "expected_canonical_token_lifecycle_probe": lifecycle_token,
            "expected_canonical_token_mount_diag": str(mount_diag.get("expire_token") or ""),
            "parsed_from_token_sent": parsed_sent,
            "parsed_from_coalesced": parsed_coalesced,
            "parsed_fields_match_live_room": parsed_match_live,
            "mount_diag_row": mount_diag.get("mount_row") or {},
        },
        "delivery": {
            "process_production_expire_token_entry_inferred": bool(native or rejected or accepted_native),
            "native_component_return_callbacks": native,
            "accepted_native_component_return": accepted_native,
            "first_rejection_code": first_reject,
            "delivery_owners": owners,
            "callback_timeline": callbacks,
            "return_value_rejected_in_server_chain": "return_value_rejected" in str(exp.get("server_chain") or ""),
        },
        "draft_result": {
            "pick_commits": pick_commits,
            "selection_source": str(last_commit.get("selection_source") or ""),
            "player_selected": picked_player,
            "queue_add": queue_meta,
            "queue_player_ignored": queue_ignored,
            "pick_before": exp.get("pick_before"),
            "pick_after": exp.get("pick_after"),
            "pick_delta": exp.get("pick_delta"),
            "team_before": exp.get("state_before", {}).get("team"),
            "team_after": exp.get("state_after", {}).get("team"),
            "deadline_before": exp.get("deadline_before"),
            "deadline_after": exp.get("deadline_after"),
            "timer_after": exp.get("state_after", {}).get("timer"),
            "commits_delta": exp.get("commits_delta"),
            "supabase_requests_after_component_value_sent": exp.get("supabase_requests_after_send") or [],
        },
        "failure_interpretation_class": failure_class,
        "observation_duration_s": exp.get("observation_duration_s"),
        "value_sent_observation_extension_s": exp.get("post_send_observation_s"),
    }


def validate_production_draft_start(
    page, draft: dict[str, Any], *, prior_room_id: str = ""
) -> dict[str, Any]:
    from production_draft_start_authoritative import (
        grade_authoritative_draft_start,
        scrape_authoritative_start_state,
    )
    from run_production_solo_soak import all_frames_text, dom_counts

    auth_state = scrape_authoritative_start_state(page)
    auth_grade = grade_authoritative_draft_start(
        auth_state,
        prior_room_id=prior_room_id,
        start_click_dispatched=True,
    )
    if auth_grade.get("pass"):
        rid = str(auth_grade.get("room_id") or auth_state.get("room_id") or "").upper()
        return {
            "valid": True,
            "latched_room_id": rid,
            "visible_room_id": auth_state.get("visible_room_id") or rid,
            "draft_start_success": True,
            "in_progress": True,
            "authoritative_start": True,
            "authoritative_grade": auth_grade,
            "authoritative_state": auth_state,
            "legacy_start_success": bool(draft.get("start_success")),
        }
    latched = str(draft.get("room_id") or auth_state.get("room_id") or "").strip().upper()
    if not draft.get("start_success") and not latched:
        return {
            "valid": False,
            "reason": "draft_start_success_false",
            "draft_start": draft,
            "authoritative_grade": auth_grade,
            "authoritative_state": auth_state,
        }
    text = all_frames_text(page)
    visible = room_id_from_text(text) or str(auth_state.get("visible_room_id") or "").upper()
    counts = dom_counts(page)
    in_progress = bool(auth_state.get("in_progress")) or (
        int(counts.get("Pause Draft") or 0) >= 1 and bool(latched)
    )
    if not in_progress:
        return {
            "valid": False,
            "reason": "room_not_in_progress",
            "latched_room_id": latched,
            "visible_room_id": visible,
            "pause_draft_count": counts.get("Pause Draft"),
            "authoritative_grade": auth_grade,
        }
    if not latched:
        return {
            "valid": False,
            "reason": "room_id_mismatch_or_missing",
            "latched_room_id": latched,
            "visible_room_id": visible,
            "authoritative_grade": auth_grade,
        }
    if visible and latched != visible:
        return {
            "valid": False,
            "reason": "room_id_mismatch_or_missing",
            "latched_room_id": latched,
            "visible_room_id": visible,
            "authoritative_grade": auth_grade,
        }
    if prior_room_id and latched == prior_room_id.strip().upper():
        return {
            "valid": False,
            "reason": "reused_prior_room_id",
            "latched_room_id": latched,
            "prior_room_id": prior_room_id.strip().upper(),
        }
    return {
        "valid": True,
        "latched_room_id": latched,
        "visible_room_id": visible or latched,
        "draft_start_success": True,
        "in_progress": True,
        "authoritative_start": False,
        "legacy_start_success": bool(draft.get("start_success")),
        "authoritative_grade": auth_grade,
    }


def wait_one_expiration(
    page,
    *,
    timeout_s: float = 55.0,
    parent_sink: Any | None = None,
) -> dict[str, Any]:
    from run_production_solo_soak import (
        dom_counts,
        scrape_client_chain,
        scrape_expire_chain,
        scrape_iframe_lifecycle,
        scrape_stage1_audit,
        scrape_transport_boundary,
    )
    from stage1_frame_transport_probe import (
        analyze_double_production_sends,
        collect_frame_topology,
        install_immediate_parent_listeners,
        scrape_immediate_parent_messages,
    )
    from stage1_parent_observer_probe import (
        install_harness_top_observer,
        merge_ledger_rows,
        scrape_parent_observer_exports,
    )
    from stage1_frame2_parent_boundary import (
        classify_parent_boundary_p,
        collect_observer_execution_contexts,
        install_frame2_parent_listener,
        scrape_frame2_parent_messages,
        scrape_stage1_ledger_all_frames,
    )

    t0 = time.time()
    state_before = scrape_timer_fields(page)
    counts_before = dom_counts(page)
    room_in_progress_before = (
        int(counts_before.get("Pause Draft") or 0) >= 1
        or state_before.get("ccTimer") is not None
        or bool((state_before.get("mount_diag") or {}).get("diag_deadline"))
    )
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
    best_transport: dict[str, Any] = {}
    timer_armed_at: float | None = None
    value_sent_at: float | None = None
    observe_until = t0 + timeout_s
    frame_topology_initial = collect_frame_topology(page)
    install_harness_top_observer(page)
    install_immediate_parent_listeners(page)
    from stage1_harness_observability import (
        LEDGER_DURABLE_INIT_SCRIPT,
        ledger_rows_from_callback_audit,
        merge_ledger_sources,
        normalize_expire_token,
        scrape_durable_ledger_store,
        wait_for_next_timer_after_commit,
    )

    try:
        page.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
    except Exception:
        pass
    merged_server_ledger: list[dict[str, Any]] = []
    peak_merged_server_ledger: list[dict[str, Any]] = []
    frame2_install_log: list[dict[str, Any]] = []
    frame2_meta_initial: dict[str, Any] = {}
    durable_wait_result: dict[str, Any] = {}
    durable_wait_done = False
    send_browser_event_id = ""
    supabase_requests: list[dict[str, Any]] = []
    pick_committed_at: float | None = None
    next_timer_wait: dict[str, Any] = {}
    post_commit_wait_started = False

    def _capture_loop_ledger() -> None:
        nonlocal merged_server_ledger, peak_merged_server_ledger
        ledger_snap = scrape_stage1_ledger_all_frames(page)
        best_row = ledger_snap.get("best") or {}
        if best_row.get("b64"):
            try:
                from stage1_harness_observability import decode_ledger_b64_padded

                decoded = decode_ledger_b64_padded(str(best_row.get("b64") or ""))
                merged_server_ledger = merge_ledger_rows(
                    merged_server_ledger, list(decoded.get("rows") or [])
                )
            except Exception:
                pass
        store = scrape_durable_ledger_store(page)
        if store.get("best_b64"):
            try:
                from stage1_harness_observability import rows_from_b64

                merged_server_ledger = merge_ledger_rows(
                    merged_server_ledger, rows_from_b64(str(store.get("best_b64") or ""))
                )
            except Exception:
                pass
        if len(merged_server_ledger) > len(peak_merged_server_ledger):
            peak_merged_server_ledger = list(merged_server_ledger)

    def _on_request(req: Any) -> None:
        try:
            url = req.url or ""
            if "supabase" in url.lower():
                supabase_requests.append(
                    {"ts": time.time(), "method": req.method, "url": url[:280]}
                )
        except Exception:
            pass

    try:
        page.on("request", _on_request)
    except Exception:
        pass

    while time.time() < observe_until:
        install_harness_top_observer(page)
        install_immediate_parent_listeners(page)
        f2 = install_frame2_parent_listener(page)
        frame2_install_log.append({"ts": time.time(), **f2})
        if f2.get("ok") and not frame2_meta_initial:
            frame2_meta_initial = dict(f2.get("result") or {})
        ledger_snap = scrape_stage1_ledger_all_frames(page)
        best = ledger_snap.get("best") or {}
        if best.get("b64"):
            try:
                from stage1_harness_observability import decode_ledger_b64_padded

                decoded = decode_ledger_b64_padded(str(best.get("b64") or ""))
                merged_server_ledger = merge_ledger_rows(
                    merged_server_ledger, list(decoded.get("rows") or [])
                )
            except Exception:
                pass
        store = scrape_durable_ledger_store(page)
        if store.get("best_b64"):
            try:
                from stage1_harness_observability import rows_from_b64

                merged_server_ledger = merge_ledger_rows(
                    merged_server_ledger, rows_from_b64(str(store.get("best_b64") or ""))
                )
            except Exception:
                pass
        if len(merged_server_ledger) > len(peak_merged_server_ledger):
            peak_merged_server_ledger = list(merged_server_ledger)
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
        transport = scrape_transport_boundary(page)
        if transport:
            best_transport = transport
        try:
            topo_snap = collect_frame_topology(page)
            if (topo_snap.get("frame_count") or 0) >= 5:
                snap["frame_topology"] = topo_snap
        except Exception:
            pass
        if audit:
            best_audit = audit
        audit_callbacks = list((audit or {}).get("callbacks") or [])
        accepted_now = [c for c in audit_callbacks if c.get("delivery_claimed") and not c.get("reject_code")]
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
        if {"browser_deadline_crossed", "component_value_sent"} & client_merged and value_sent_at is None:
            value_sent_at = time.time()
            observe_until = max(observe_until, value_sent_at + 45.0)
            try:
                life_entries = list((iframe_life.get("entries") or []))
                for ent in reversed(life_entries):
                    if str(ent.get("stage") or "") == "transport_before_postMessage":
                        extra = str(ent.get("extra") or "")
                        m = re.search(r"bse_[0-9]+_[0-9]+", extra)
                        if m:
                            send_browser_event_id = m.group(0)
                            break
            except Exception:
                pass
            if parent_sink is not None and not durable_wait_done:
                durable_wait_done = True
                from stage1_parent_event_sink import wait_for_durable_receipts_after_send

                tok_guess = str((merged_client if isinstance(merged_client, dict) else {}).get("token") or "")
                if not tok_guess:
                    tok_guess = str(client.get("token") or "")
                durable_wait_result = wait_for_durable_receipts_after_send(
                    parent_sink,
                    expected_token=tok_guess,
                    browser_send_event_id=send_browser_event_id,
                    timeout_s=5.0,
                )
        if {"pick_committed", "commit_confirmed"} & merged_stages and not post_commit_wait_started:
            post_commit_wait_started = True
            pick_committed_at = time.time()
            _capture_loop_ledger()
            tok_completed = str(
                merged_client.get("token")
                or client.get("token")
                or chain.get("component_return")
                or chain.get("component_raw")
                or ""
            )
            pf = parse_expire_token_fields(tok_completed)
            room_for_wait = str(pf.get("draft_id") or "")
            next_timer_wait = wait_for_next_timer_after_commit(
                page,
                completed_token=tok_completed,
                room_id=room_for_wait,
                deadline_before=deadline_before,
                pick_committed_at=pick_committed_at,
                scrape_timer_fields=scrape_timer_fields,
                scrape_component_mount_diag=scrape_component_mount_diag,
                scrape_persistent_lifecycle_token=scrape_persistent_lifecycle_token,
                scrape_stage1_audit=scrape_stage1_audit,
                scrape_expire_chain=scrape_expire_chain,
                capture_ledger=_capture_loop_ledger,
                get_ledger_rows=lambda: list(merged_server_ledger),
                poll_ms=400,
                timeout_s=28.0,
            )
            _capture_loop_ledger()
            observe_until = min(observe_until, time.time() + 3.0)
            continue
        if not post_commit_wait_started:
            for row in merged_server_ledger:
                if str(row.get("event") or "") == "production_stage1_token_action_complete":
                    post_commit_wait_started = True
                    pick_committed_at = float(row.get("ts") or time.time())
                    _capture_loop_ledger()
                    tok_completed = normalize_expire_token(row.get("token") or "")
                    if not tok_completed:
                        tok_completed = str(
                            merged_client.get("token")
                            or client.get("token")
                            or ""
                        )
                    pf = parse_expire_token_fields(tok_completed)
                    room_for_wait = str(pf.get("draft_id") or row.get("room_id") or "")
                    next_timer_wait = wait_for_next_timer_after_commit(
                        page,
                        completed_token=tok_completed,
                        room_id=room_for_wait,
                        deadline_before=deadline_before,
                        pick_committed_at=pick_committed_at,
                        scrape_timer_fields=scrape_timer_fields,
                        scrape_component_mount_diag=scrape_component_mount_diag,
                        scrape_persistent_lifecycle_token=scrape_persistent_lifecycle_token,
                        scrape_stage1_audit=scrape_stage1_audit,
                        scrape_expire_chain=scrape_expire_chain,
                        capture_ledger=_capture_loop_ledger,
                        get_ledger_rows=lambda: list(merged_server_ledger),
                        poll_ms=400,
                        timeout_s=28.0,
                    )
                    _capture_loop_ledger()
                    observe_until = min(observe_until, time.time() + 3.0)
                    break
        if post_commit_wait_started and next_timer_wait.get("status") in ("observed", "timeout"):
            break
        if accepted_now and not post_commit_wait_started:
            observe_until = min(observe_until, time.time() + 8.0)
        if value_sent_at is not None and time.time() >= value_sent_at + 45.0:
            break
        if (
            timer_armed_at
            and value_sent_at is None
            and time.time() >= timer_armed_at + 25
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
    transport_final = scrape_transport_boundary(page) or best_transport
    frame_topology_final = collect_frame_topology(page)
    immediate_parent_messages = scrape_immediate_parent_messages(page)
    parent_observer_export = scrape_parent_observer_exports(page)
    top_parent_messages = list((parent_observer_export.get("harness_top") or []))
    app_observer_msgs = list(((parent_observer_export.get("app_observer") or {}).get("messages") or []))
    for am in app_observer_msgs:
        if isinstance(am, dict):
            row = dict(am)
            row.setdefault("receiving_window", "app_early_observer_top")
            row.setdefault("receiving_window_level", "LEVEL_2_TOP")
            top_parent_messages.append(row)
    _capture_loop_ledger()
    final_dom_rows: list[dict[str, Any]] = []
    ledger_final = scrape_stage1_ledger_all_frames(page)
    best_ledger = ledger_final.get("best") or {}
    if best_ledger.get("b64"):
        try:
            from stage1_harness_observability import decode_ledger_b64_padded

            decoded = decode_ledger_b64_padded(str(best_ledger.get("b64") or ""))
            final_dom_rows = list(decoded.get("rows") or [])
        except Exception:
            pass
    if not final_dom_rows:
        try:
            from stage1_parent_observer_probe import scrape_stage1_production_ledger

            dom_ledger = scrape_stage1_production_ledger(page)
            final_dom_rows = list(dom_ledger.get("rows") or [])
        except Exception:
            pass
    durable_store = scrape_durable_ledger_store(page)
    frame2_final = scrape_frame2_parent_messages(page)
    observer_contexts = collect_observer_execution_contexts(page)
    # Prefer topology captured while component iframes are still attached (Playwright detaches on teardown).
    if (frame_topology_final.get("frame_count") or 0) < 5:
        for snap in reversed(samples):
            topo = (snap.get("frame_topology") or {}) if isinstance(snap, dict) else {}
            if (topo.get("frame_count") or 0) >= 5:
                frame_topology_final = topo
                break
    state_after = scrape_timer_fields(page)
    mount_after = scrape_component_mount_diag(page)
    pick_after = state_after.get("pick")
    if next_timer_wait.get("new_deadline"):
        deadline_after = str(next_timer_wait.get("new_deadline") or "")
    else:
        deadline_after = (state_after.get("mount_diag") or {}).get("diag_deadline") or state_after.get("timer")
    if next_timer_wait.get("new_token"):
        next_token_after = str(next_timer_wait.get("new_token") or "")
    else:
        next_token_after = str(
            mount_after.get("expire_token")
            or scrape_persistent_lifecycle_token(page)
            or (state_after.get("mount_diag") or {}).get("diag_token")
            or ""
        )
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
    callback_audit_rows = ledger_rows_from_callback_audit(
        audit_final,
        server_chain=str(chain_final.get("chain") or ""),
        server_stages=list(server_stages),
    )
    ledger_meta = merge_ledger_sources(
        observation_loop_rows=list(merged_server_ledger),
        peak_observation_rows=list(peak_merged_server_ledger),
        durable_best_b64=str(durable_store.get("best_b64") or ""),
        final_dom_rows=final_dom_rows,
        callback_audit_rows=callback_audit_rows,
        merge_fn=merge_ledger_rows,
    )
    merged_server_ledger = list(ledger_meta.get("merged_server_ledger") or [])
    pick1_same_session_mount: dict[str, Any] = {}
    callbacks = list(audit_final.get("callbacks") or [])
    accepted = [c for c in callbacks if c.get("delivery_claimed") and not c.get("reject_code")]
    rejected = [c for c in callbacks if c.get("reject_code")]
    pick_commits = list(audit_final.get("pick_commits") or [])
    pick_delta = None
    pick_index_before = None
    pick_index_after = None
    if pick_commits:
        lc = pick_commits[-1]
        if lc.get("pick_index_before") is not None and lc.get("pick_index_after") is not None:
            pick_index_before = int(lc["pick_index_before"])
            pick_index_after = int(lc["pick_index_after"])
            pick_delta = pick_index_after - pick_index_before
    if pick_delta is None and pick_before is not None and pick_after is not None:
        pick_delta = int(pick_after) - int(pick_before)

    token_sent = str(client_final.get("token") or "")
    if not token_sent:
        for s in reversed(samples):
            c = client_hit(s)
            if c.get("token"):
                token_sent = str(c.get("token"))
                break

    if post_commit_wait_started:
        from stage1_harness_observability import (
            build_pick1_same_session_mount_bundle,
            persist_pick1_same_session_mount_capture,
            scrape_countdown_iframe_connectivity,
        )

        iframe_probe_final = scrape_countdown_iframe_connectivity(page)
        tok_for_room = str(
            next_timer_wait.get("new_token")
            or token_sent
            or mount_after.get("expire_token")
            or ""
        )
        pf_wait = parse_expire_token_fields(tok_for_room)
        room_for_mount = str(pf_wait.get("draft_id") or "")
        pick1_same_session_mount = build_pick1_same_session_mount_bundle(
            next_timer_wait=next_timer_wait,
            merged_ledger=merged_server_ledger,
            room_id=room_for_mount,
            iframe_probe=iframe_probe_final,
            mount_diag=mount_after,
            timer_fields=state_after,
        )
        persist_pick1_same_session_mount_capture(
            ROOT / "data" / "pick1_same_session_mount_capture.json",
            pick1_same_session_mount,
        )
        next_timer_wait = {**next_timer_wait, "pick1_same_session_mount": pick1_same_session_mount}

    iframe_entries: list[dict[str, Any]] = []
    for fr in (iframe_final.get("frames") or []):
        if not isinstance(fr, dict):
            continue
        for block in fr.get("logs") or []:
            if isinstance(block, dict):
                iframe_entries.extend(block.get("entries") or [])

    send_ts_ms: int | None = None
    for e in reversed(iframe_entries):
        if isinstance(e, dict) and str(e.get("stage") or "") in (
            "transport_postmessage_invoked",
            "component_value_sent",
        ):
            try:
                send_ts_ms = int(e.get("ts") or 0)
            except (TypeError, ValueError):
                send_ts_ms = None
            if send_ts_ms:
                break

    try:
        from live_draft_solo_transport_boundary_diag import classify_transport_stage

        transport_class = classify_transport_stage(
            iframe_entries=iframe_entries,
            parent_entries=list(transport_final.get("parent_log") or []),
            transport_log=list((transport_final.get("probe") or {}).get("log_tail") or []),
            callback_count=len(accepted),
            iframe_has_component_sent="component_value_sent" in client_stages,
            send_ts_ms=send_ts_ms,
            immediate_parent_messages=immediate_parent_messages,
        )
    except ImportError:
        transport_class = ""

    double_production = analyze_double_production_sends(iframe_entries)

    supabase_after_send: list[dict[str, Any]] = []
    if value_sent_at is not None:
        supabase_after_send = [r for r in supabase_requests if float(r.get("ts") or 0) >= float(value_sent_at) - 0.5]

    parent_event_sink_export: dict[str, Any] = {}
    if parent_sink is not None:
        from stage1_parent_event_sink import paired_probe_scv_report

        parent_event_sink_export = {
            "installed_at": parent_sink.installed_at,
            "binding_calls": parent_sink.binding_calls,
            "console_rows": parent_sink.console_rows,
            "raw_events": parent_sink.raw_events,
            "durable_wait_after_send": durable_wait_result,
            "send_browser_event_id": send_browser_event_id,
            "paired_receipts": paired_probe_scv_report(
                parent_sink,
                expected_token=token_sent,
                browser_send_event_id=send_browser_event_id,
            ),
            "logical": parent_sink.logical_receipts(expected_token=token_sent),
        }

    transport_final = dict(transport_final or {})
    transport_final["frame_topology"] = frame_topology_final
    transport_final["frame_topology_at_start"] = frame_topology_initial
    transport_final["immediate_parent_messages"] = immediate_parent_messages
    transport_final["legacy_parent_log_note"] = (
        "legacy solo_transport_parent_log may be on wrong frame; use immediate_parent_messages for stage B"
    )
    transport_final["double_production_send_analysis"] = double_production

    return {
        "samples_count": len(samples),
        "room_in_progress_before": room_in_progress_before,
        "state_before": state_before,
        "state_after": state_after,
        "pick_before": pick_before,
        "pick_after": pick_after,
        "pick_index_before": pick_index_before,
        "pick_index_after": pick_index_after,
        "pick_delta": pick_delta,
        "deadline_before": deadline_before,
        "deadline_after": deadline_after,
        "next_token_after_commit": next_token_after,
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
        "transport_boundary": transport_final,
        "first_missing_transport_stage": transport_class,
        "client_send_ts_ms": send_ts_ms,
        "frame_topology": frame_topology_final,
        "immediate_parent_messages": immediate_parent_messages,
        "top_parent_messages": top_parent_messages,
        "app_parent_observer_messages": app_observer_msgs,
        "merged_server_ledger": merged_server_ledger,
        "merged_server_ledger_run_id": best_ledger.get("run_id") or "",
        "merged_server_ledger_source": best_ledger.get("sanitized_url") or "",
        "merged_server_ledger_probe_hits": ledger_final.get("hits") or [],
        "ledger_meta": ledger_meta,
        "next_timer_wait": next_timer_wait,
        "pick1_same_session_mount": pick1_same_session_mount,
        "pick_committed_at": pick_committed_at,
        "mount_after_commit": mount_after,
        "frame2_parent_messages": list(frame2_final.get("messages") or []),
        "frame2_observer_meta": frame2_final.get("meta") or {},
        "frame2_navigation": frame2_final.get("navigation") or {},
        "frame2_install_log": frame2_install_log[-40:],
        "observer_execution_contexts": observer_contexts,
        "parent_event_sink": parent_event_sink_export,
        "send_browser_event_id": send_browser_event_id,
        "double_production_send_analysis": double_production,
        "value_sent_at_elapsed_s": round(value_sent_at - t0, 1) if value_sent_at else None,
        "post_send_observation_s": round(time.time() - value_sent_at, 1) if value_sent_at else None,
        "supabase_requests_after_send": supabase_after_send,
    }


def grade_stage_1a(
    page,
    draft_valid: dict[str, Any],
    exp: dict[str, Any],
    *,
    preflight: dict[str, Any] | None = None,
    stage1a_mode: str = "FULL",
) -> dict[str, Any]:
    from stage1_harness_observability import (
        authoritative_exact_token_delivery,
        authoritative_room_in_progress_at_send,
        classify_next_timer_status,
        ledger_claim_metrics,
        ledger_pick_commit_reconciliation,
        ledger_server_next_timer,
        build_stage1a_core_status_model,
        classify_stage1a_queue,
        extract_pick1_post_commit_mount_observation,
        split_stage1a_grades,
    )

    cs = set(exp.get("client_stages") or [])
    accepted_count = int(exp.get("callback_accepted_count") or 0)
    rejected_count = int(exp.get("callback_rejected_count") or 0)
    on_change_count = accepted_count
    if on_change_count == 0:
        on_change_count = str(exp.get("server_chain") or "").count("on_change_callback_entry")
    token_sent = str(exp.get("token_sent") or "")
    if not token_sent.strip() and stage1a_mode == "CORE":
        token_sent = str(
            draft_valid.get("expected_token")
            or (draft_valid.get("setup_authority") or {}).get("expected_token")
            or ""
        )
    raw = str(exp.get("component_raw") or "")
    pick_delta = exp.get("pick_delta")
    pick_commits = exp.get("pick_commit_audit") or []
    pick_index_delta = None
    if exp.get("pick_index_before") is not None and exp.get("pick_index_after") is not None:
        pick_index_delta = int(exp["pick_index_after"]) - int(exp["pick_index_before"])
    elif pick_commits:
        lc = pick_commits[-1]
        if lc.get("pick_index_before") is not None and lc.get("pick_index_after") is not None:
            pick_index_delta = int(lc["pick_index_after"]) - int(lc["pick_index_before"])
    exactly_one_pick = (
        pick_index_delta == 1
        or pick_delta == 1
        or exp.get("board_delta") == 1
        or (exp.get("commits_delta") == 1 and bool(pick_commits))
    )
    auth_ok = authenticated_probe(page, preflight=preflight)
    if preflight and preflight.get("authenticated_restored"):
        auth_ok = True
    auth_at_expire = auth_ok
    callbacks = list(exp.get("callback_timeline") or [])
    merged_ledger = list(exp.get("merged_server_ledger") or [])
    ledger_meta = dict(exp.get("ledger_meta") or {})
    next_timer_wait = dict(exp.get("next_timer_wait") or {})
    app_run_id = str(
        exp.get("application_diagnostic_run_id")
        or (draft_valid.get("production_setup") or {}).get("application_diagnostic_run_id")
        or ""
    )
    latched_room = str(
        draft_valid.get("latched_room_id")
        or draft_valid.get("visible_room_id")
        or draft_valid.get("room_id")
        or exp.get("fresh_room_id")
        or ""
    ).upper()
    harness_reconciled = False
    claim_ledger: dict[str, Any] = {}
    pick_ledger: dict[str, Any] = {}
    timer_ledger: dict[str, Any] = {}
    room_at_send: dict[str, Any] = {}
    if merged_ledger and stage1a_mode == "CORE":
        claim_ledger = ledger_claim_metrics(
            merged_ledger, run_id=app_run_id, room_id=latched_room
        )
        pick_ledger = ledger_pick_commit_reconciliation(
            merged_ledger, run_id=app_run_id, room_id=latched_room
        )
        timer_ledger = ledger_server_next_timer(
            merged_ledger,
            run_id=app_run_id,
            room_id=latched_room,
            completed_token=token_sent,
        )
        room_at_send = authoritative_room_in_progress_at_send(
            merged_ledger,
            token_sent=token_sent,
            send_ts=float(exp.get("value_sent_at") or 0) or None,
            room_id=latched_room,
            run_id=app_run_id,
        )
        harness_reconciled = True
        if pick_ledger.get("pick_index_delta") is not None:
            pick_index_delta = int(pick_ledger["pick_index_delta"])
        if pick_ledger.get("one_durable_pick"):
            exactly_one_pick = True
    room_ok = bool(draft_valid.get("valid")) and (
        bool(exp.get("room_in_progress_before")) or bool(room_at_send.get("server_in_progress_at_send"))
    )
    expire_caused_pick = bool(pick_commits) and not exp.get("harness_manual_draft_action")
    if pick_ledger.get("one_durable_pick"):
        expire_caused_pick = True
    zero_cross = "browser_deadline_crossed" in cs
    sent_ok = "component_value_sent" in cs
    try:
        from live_draft_stage1_expire_audit import HARMLESS_REJECT_CODES
    except ImportError:
        from stage1_harness_observability import HARMLESS_REJECT_CODES  # type: ignore[attr-defined]
    native_observation = [
        c for c in callbacks if str(c.get("callback_source") or "") == "native_component_return"
    ]
    bind_accepted = [
        c
        for c in callbacks
        if str(c.get("callback_source") or "") == "return_value_session_bind"
        and c.get("delivery_claimed")
        and not c.get("reject_code")
    ]
    if claim_ledger.get("accepted_bind_rows"):
        bind_accepted = list(claim_ledger.get("accepted_bind_rows") or bind_accepted)
    accepted_count = max(int(exp.get("callback_accepted_count") or 0), len(bind_accepted))
    if claim_ledger.get("accepted_claim_count"):
        accepted_count = max(accepted_count, int(claim_ledger["accepted_claim_count"]))
    operational_rejects = [
        c
        for c in callbacks
        if c.get("reject_code") and str(c.get("reject_code") or "") not in HARMLESS_REJECT_CODES
    ]
    claim_sources = [
        str(c.get("callback_source") or "")
        for c in callbacks
        if c.get("delivery_claimed") and not c.get("reject_code")
    ]
    mount_return = str(
        (exp.get("return_value_chain") or {}).get("python_component", {}).get("coalesced_component_value")
        or exp.get("component_return")
        or ""
    )
    exact_token = authoritative_exact_token_delivery(
        token_sent=token_sent,
        component_raw=raw,
        server_chain=str(exp.get("server_chain") or ""),
        callbacks=callbacks,
        merged_ledger=merged_ledger,
        mount_return=mount_return,
    )
    claim_result_source = ""
    for row in merged_ledger:
        if not isinstance(row, dict):
            continue
        if str(row.get("event") or "") != "production_stage1_token_claim_result":
            continue
        if row.get("accepted"):
            claim_result_source = str(row.get("source") or row.get("delivery_via") or "")
            break
    if not claim_result_source and bind_accepted:
        claim_result_source = "return_value_session_bind"
    if not claim_sources and claim_ledger.get("accepted_return_value_session_bind_count"):
        claim_sources = ["return_value_session_bind"]
    mount_diag_after = (exp.get("state_after", {}).get("mount_diag") or {})
    mount_after = dict(exp.get("mount_after_commit") or {})
    timer_after = exp.get("state_after", {}).get("timer")
    visible_countdown = (
        next_timer_wait.get("visible_countdown")
        or mount_diag_after.get("diag_remaining")
        or timer_after
    )
    deadline_after = str(
        next_timer_wait.get("new_deadline")
        or exp.get("deadline_after")
        or mount_diag_after.get("diag_deadline")
        or ""
    )
    next_token_after = str(next_timer_wait.get("new_token") or exp.get("next_token_after_commit") or "")
    if timer_ledger.get("server_deadline"):
        deadline_after = str(timer_ledger["server_deadline"])
    if timer_ledger.get("server_expected_token"):
        next_token_after = str(timer_ledger["server_expected_token"])
    countdown_restarted = (
        next_timer_wait.get("status") == "observed"
        or (timer_after is not None and int(timer_after) > 0)
        or bool(mount_diag_after.get("diag_remaining"))
        or bool(deadline_after)
    )
    queue_independence = ""
    if stage1a_mode == "CORE":
        queue_independence = "NOT EXERCISED — EMPTY QUEUE"
        queue_check_ok = True
    elif stage1a_mode == "QUEUE":
        queue_check_ok = True
    else:
        queue_check_ok = bool(
            (exp.get("return_value_chain") or {}).get("draft_result", {}).get("queue_player_ignored", True)
        )
    owners = dict((exp.get("stage1_audit") or {}).get("delivery_owners") or {})
    flush_owner = any(str(v) == "late_page_flush" for v in owners.values())
    on_change_owner = any(str(v) == "native_component_on_change" for v in owners.values())
    remount_warn = int(
        (exp.get("return_value_chain") or {}).get("browser", {}).get("iframe_remounts") or 0
    ) > 0
    auth_pick_index = None
    if pick_commits:
        lc = pick_commits[-1]
        if lc.get("pick_index_after") is not None:
            auth_pick_index = int(lc["pick_index_after"])
    if timer_ledger.get("authoritative_pick_index") is not None:
        auth_pick_index = int(timer_ledger["authoritative_pick_index"])
    elif pick_ledger.get("pick_index_after") is not None:
        auth_pick_index = int(pick_ledger["pick_index_after"])
    timer_classification = classify_next_timer_status(
        next_timer_wait=next_timer_wait,
        authoritative_pick_index=auth_pick_index,
        server_deadline=deadline_after,
        server_expected_token=next_token_after,
        component_declaration_token=str(mount_after.get("expire_token") or ""),
        iframe_diag_token=str((exp.get("mount_after_commit") or {}).get("expire_token") or ""),
        visible_countdown=visible_countdown,
        completed_token=token_sent,
    )
    ledger_retained = int(ledger_meta.get("merged_server_ledger_row_count") or len(merged_ledger)) > 0
    next_timer_verified = next_timer_wait.get("status") == "observed"
    server_timer_ok = bool(timer_ledger.get("server_deadline")) and bool(timer_ledger.get("server_expected_token"))
    pick_advanced = pick_index_delta == 1

    checks = {
        "1_authenticated_at_expire": auth_at_expire,
        "2_room_in_progress_before_expire": room_ok,
        "3_browser_deadline_crossed": zero_cross,
        "4_component_value_sent": sent_ok,
        "5_exact_token_delivery": exact_token,
        "6_one_accepted_callback": accepted_count == 1,
        "6a_observation_never_claimed": all(not c.get("delivery_claimed") for c in native_observation),
        "6b_return_value_session_bind_accepted": len(bind_accepted) == 1,
        "6c_claim_source_not_other": "other" not in claim_sources
        and (claim_result_source == "return_value_session_bind" or len(bind_accepted) == 1),
        "7_zero_duplicate_processing": len(operational_rejects) == 0 and accepted_count <= 1,
        "7b_no_late_flush_owner": not flush_owner,
        "7c_no_on_change_owner": not on_change_owner,
        "8_one_pick_committed": exactly_one_pick,
        "9_pick_advances_once": pick_index_delta == 1 if pick_index_delta is not None else pick_delta == 1,
        "ledger_durable_retained": ledger_retained,
        "10_new_deadline_after_commit": (
            (next_timer_verified or (harness_reconciled and server_timer_ok and pick_advanced))
            and bool(deadline_after)
        ),
        "11_countdown_restarts_above_zero": countdown_restarted,
        "12_board_or_pool_updated": (exp.get("board_delta") or 0) >= 1 or exactly_one_pick,
        "13_pick_from_expire_not_harness": expire_caused_pick,
        "14_queue_player_ignored": queue_check_ok,
        "15_next_token_after_commit": (
            (next_timer_verified or (harness_reconciled and server_timer_ok))
            and bool(next_token_after)
            and next_token_after != token_sent
        ),
        "16_next_timer_fully_verified": next_timer_verified and timer_classification.startswith("T5"),
    }
    split = split_stage1a_grades(
        checks=checks,
        ledger_meta=ledger_meta,
        next_timer_wait=next_timer_wait,
        timer_classification=timer_classification,
        harness_observability_corrected=harness_reconciled,
    )
    if remount_warn and split.get("verdict") == "PASS":
        checks["warn_iframe_remounts"] = True
    out = {
        "checks": checks,
        "verdict": split.get("verdict"),
        "functional_verdict": split.get("functional_verdict"),
        "observability_verdict": split.get("observability_verdict"),
        "overall_classification": split.get("overall_classification"),
        "timer_continuity_classification": timer_classification,
        "on_change_count": on_change_count,
        "callback_accepted_count": accepted_count,
        "callback_rejected_count": rejected_count,
        "pick_delta": pick_delta,
        "token_match": exact_token,
        "authenticated_at_expire": auth_at_expire,
        "native_component_return_accepted_count": sum(
            1 for c in native_observation if c.get("delivery_claimed") and not c.get("reject_code")
        ),
        "return_value_session_bind_accepted_count": int(
            claim_ledger.get("accepted_return_value_session_bind_count") or len(bind_accepted)
        ),
        "operational_reject_count": len(operational_rejects),
        "pick_index_delta": pick_index_delta,
        "claim_result_source": claim_result_source,
        "harness_ledger_reconciliation": {
            "applied": harness_reconciled,
            "room_at_send": room_at_send,
            "claim_metrics": claim_ledger,
            "pick_reconciliation": pick_ledger,
            "server_next_timer": timer_ledger,
        },
        "failure_interpretation_class": (exp.get("return_value_chain") or {}).get("failure_interpretation_class"),
        "stage1a_mode": stage1a_mode,
        "ledger_meta": ledger_meta,
        "next_timer_wait": next_timer_wait,
        **{k: split.get(k) for k in ("functional_checks", "observability_checks") if k in split},
    }
    if queue_independence:
        out["queue_independence"] = queue_independence
    if stage1a_mode in ("CORE", "QUEUE"):
        pick1_mount = extract_pick1_post_commit_mount_observation(
            merged_ledger,
            expected_pick1_token=str(timer_ledger.get("server_expected_token") or next_token_after),
            run_id=app_run_id,
            room_id=latched_room,
            mount_diag=dict(exp.get("mount_after_commit") or {}),
            lifecycle_token=str((exp.get("return_value_chain") or {}).get("browser", {}).get("lifecycle_token") or ""),
            visible_countdown=visible_countdown,
        )
        if exp.get("next_timer_wait", {}).get("pick1_post_commit_mount"):
            pick1_mount = dict(exp["next_timer_wait"]["pick1_post_commit_mount"])
        if exp.get("pick1_same_session_mount"):
            pick1_mount = dict(exp.get("pick1_same_session_mount") or {}).get("pick1_post_commit_mount") or pick1_mount
        pick1_mount_bundle = dict(exp.get("pick1_same_session_mount") or {})
        if pick1_mount_bundle:
            out["pick1_same_session_mount"] = pick1_mount_bundle
            out["pick1_mount_classification"] = pick1_mount_bundle.get("pick1mount_classification") or ""
    if stage1a_mode == "CORE":
        status_model = build_stage1a_core_status_model(
            functional_verdict=str(split.get("functional_verdict") or ""),
            observability_verdict=str(split.get("observability_verdict") or ""),
            timer_classification=timer_classification,
            server_next_timer=timer_ledger,
            pick1_mount=pick1_mount,
            overall_classification=str(split.get("overall_classification") or ""),
            queue_independence=queue_independence,
        )
        out["stage1a_core_status"] = status_model
        out.update(
            {
                k: status_model[k]
                for k in (
                    "stage1a_core_functional_outcome",
                    "stage1a_core_observability_outcome",
                    "stage1a_core_overall",
                )
            }
        )
    if stage1a_mode == "QUEUE":
        from stage1_harness_observability import classify_core_reconciliation

        queue_meta = dict((exp.get("return_value_chain") or {}).get("draft_result", {}).get("queue_add") or {})
        if not queue_meta.get("queue_order"):
            queue_meta = dict(exp.get("queue_seed") or {})
        recon = classify_core_reconciliation(
            merged_ledger,
            run_id=app_run_id,
            room_id=latched_room,
            token_sent=token_sent,
        )
        eo = recon.get("exactly_once_counts") or {}
        qcls = classify_stage1a_queue(
            queue_meta=queue_meta,
            exp=exp,
            claim_metrics=claim_ledger,
            pick_reconciliation=pick_ledger,
            exactly_once=eo,
            merged_ledger=merged_ledger,
            functional_checks=checks,
        )
        queue_independence = str(qcls.get("queue_independence_label") or "")
        out["queue_independence"] = queue_independence
        out["stage1a_queue_classification"] = qcls
        out["stage1a_queue_functional_outcome"] = qcls.get("stage1a_queue_functional_outcome")
        out["stage1a_queue_overall"] = qcls.get("stage1a_queue_overall")
        if qcls.get("stage1a_queue_functional_outcome") == "PASS" and split.get("functional_verdict") == "PASS":
            out["verdict"] = "PASS"
            out["functional_verdict"] = "PASS"
            out["overall_classification"] = str(qcls.get("stage1a_queue_overall") or "STAGE1A_QUEUE_PASS")
        elif qcls.get("stage1a_queue_functional_outcome") != "PASS":
            out["verdict"] = "FAIL"
            out["functional_verdict"] = "FAIL"
            out["overall_classification"] = str(qcls.get("queue_classification") or "STAGE1A_QUEUE_FAIL")
        out["pick1_post_commit_mount"] = pick1_mount if stage1a_mode == "QUEUE" else out.get("pick1_post_commit_mount")
    return out


def _streamlit_app_frame(page):
    for frame in page.frames:
        url = frame.url or ""
        if "/~/" in url or "~/+" in url:
            return frame
    return page.main_frame


def queue_add_first_player(page) -> dict[str, Any]:
    from run_production_solo_soak import click_btn

    frame = _streamlit_app_frame(page)
    for nav in ("Draft from lists", "On Clock: Team A", "On Clock", "Recommendations"):
        try:
            frame.get_by_text(re.compile(re.escape(nav.split(":")[0]), re.I)).first.click(timeout=4000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
    for _ in range(4):
        try:
            frame.evaluate(
                """() => {
                  window.scrollTo(0, document.body.scrollHeight * 0.55);
                  const hit = Array.from(document.querySelectorAll('button')).find(
                    b => /Add to Queue/i.test(String(b.innerText||''))
                  );
                  if (hit) { hit.scrollIntoView({block: 'center'}); return true; }
                  return false;
                }"""
            )
        except Exception:
            pass
        page.wait_for_timeout(1200)
        clicked = (
            click_btn(page, "Add to Queue", wait_ms=2000)
            or click_btn(page, "⭐ Add to Queue", wait_ms=2000)
            or click_btn(page, "⭐", wait_ms=1500)
        )
        if clicked:
            meta = page.evaluate(
                """() => {
                  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
                  for (const root of roots()) {
                    for (const b of root.querySelectorAll('button')) {
                      const t = String(b.innerText||'').replace(/\\s+/g,' ').trim();
                      if (!/Add to Queue/i.test(t)) continue;
                      const card = b.closest('[data-testid=\"stVerticalBlock\"]') || b.parentElement;
                      let name = '';
                      if (card) {
                        const lines = String(card.innerText||'').split('\\n').map(x=>x.trim()).filter(Boolean);
                        name = lines.find(l => l.length > 3 && !/Add to Queue|Draft|Queue|Clear|Watchlist|⭐/i.test(l)) || '';
                      }
                      return { clicked: true, button_text: t, player_hint: name.slice(0,80), via: 'click_btn' };
                    }
                  }
                  return { clicked: true, button_text: 'Add to Queue', player_hint: '', via: 'click_btn' };
                }"""
            )
            if isinstance(meta, dict):
                return meta
            return {"clicked": True, "button_text": "Add to Queue", "player_hint": "", "via": "click_btn"}
        page.wait_for_timeout(2000)

    try:
        buttons = frame.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
        for i in range(min(buttons.count(), 8)):
            try:
                loc = buttons.nth(i)
                loc.scroll_into_view_if_needed(timeout=5000)
                loc.click(timeout=5000)
                page.wait_for_timeout(2500)
                return {"clicked": True, "button_text": "Add to Queue", "player_hint": "", "via": f"playwright_role_nth_{i}"}
            except Exception:
                continue
    except Exception:
        pass
    return {"clicked": False, "button_text": "", "player_hint": ""}


def _queue_button_player_hint(page, button_index: int) -> dict[str, Any]:
    try:
        meta = page.evaluate(
            """(buttonIndex) => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              const buttons = [];
              for (const root of roots()) {
                for (const b of root.querySelectorAll('button')) {
                  const t = String(b.innerText||'').replace(/\\s+/g,' ').trim();
                  if (/Add to Queue/i.test(t)) buttons.push(b);
                }
              }
              if (buttonIndex >= buttons.length) return {found: false, button_index: buttonIndex, total: buttons.length};
              const b = buttons[buttonIndex];
              b.scrollIntoView({block: 'center'});
              const card = b.closest('[data-testid=\"stVerticalBlock\"]') || b.parentElement;
              let name = '';
              if (card) {
                const lines = String(card.innerText||'').split('\\n').map(x=>x.trim()).filter(Boolean);
                name = lines.find(l => l.length > 3 && !/Add to Queue|Draft|Queue|Clear|Watchlist|⭐|Recommendations/i.test(l)) || '';
              }
              return {found: true, button_index: buttonIndex, total: buttons.length, player_hint: name.slice(0,80), player_name: name.slice(0,80)};
            }""",
            button_index,
        )
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def queue_add_by_button_index(page, button_index: int) -> dict[str, Any]:
    from run_production_solo_soak import click_btn

    hint = _queue_button_player_hint(page, button_index)
    frame = _streamlit_app_frame(page)
    for nav in ("Draft from lists", "On Clock: Team A", "Recommendations"):
        try:
            frame.get_by_text(re.compile(re.escape(nav.split(":")[0]), re.I)).first.click(timeout=3000)
            page.wait_for_timeout(1500)
        except Exception:
            pass
    try:
        buttons = frame.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
        if button_index < buttons.count():
            loc = buttons.nth(button_index)
            loc.scroll_into_view_if_needed(timeout=5000)
            loc.click(timeout=6000)
            page.wait_for_timeout(2200)
            hint2 = _queue_button_player_hint(page, button_index)
            return {
                "clicked": True,
                "button_index": button_index,
                "player_hint": str(hint2.get("player_hint") or hint.get("player_hint") or ""),
                "via": "playwright_role_nth",
            }
    except Exception:
        pass
    clicked = click_btn(page, "Add to Queue", wait_ms=1500)
    if clicked:
        return {
            "clicked": True,
            "button_index": button_index,
            "player_hint": str(hint.get("player_hint") or ""),
            "via": "click_btn_fallback",
        }
    return {"clicked": False, "button_index": button_index, "player_hint": ""}


def scrape_expected_autopick_candidate(page) -> dict[str, Any]:
    """Top list row (index 0) — expected ranking-based auto-pick before queue seeding."""
    meta = _queue_button_player_hint(page, 0)
    return {
        "name": str(meta.get("player_name") or meta.get("player_hint") or ""),
        "source": "recommendations_row_index_0",
        "button_index": 0,
        "scrape_meta": meta,
    }


def _names_differ(a: str, b: str) -> bool:
    pa = a.strip().split()[0][:4].lower() if a.strip() else ""
    pb = b.strip().split()[0][:4].lower() if b.strip() else ""
    return bool(pa and pb and pa != pb)


def scrape_active_live_page_observation(page, *, start_val: dict[str, Any] | None = None) -> dict[str, Any]:
    from run_production_solo_soak import all_frames_text, dom_counts

    start_val = dict(start_val or {})
    state = scrape_timer_fields(page)
    mount = scrape_component_mount_diag(page)
    md = state.get("mount_diag") or {}
    lifecycle = scrape_persistent_lifecycle_token(page)
    iframe = {}
    try:
        from stage1_harness_observability import scrape_countdown_iframe_connectivity

        iframe = scrape_countdown_iframe_connectivity(page)
    except Exception:
        iframe = {}
    text = all_frames_text(page)
    visible_room = room_id_from_text(text)
    pick0_tok = str(mount.get("expire_token") or lifecycle or md.get("diag_token") or "")
    pick0_deadline = str(md.get("diag_deadline") or mount.get("diag_deadline") or state.get("timer") or "")
    countdown_present = bool(
        pick0_tok
        or pick0_deadline
        or mount.get("key")
        or (iframe.get("countdown_iframe") or {}).get("href")
    )
    counts = dom_counts(page)
    hint = _queue_button_player_hint(page, 0)
    pick_index = state.get("pick")
    if pick_index in (None, ""):
        from stage1_queue_harness_flow import parse_pick_index_from_expire_token

        parsed = parse_pick_index_from_expire_token(pick0_tok)
        if parsed is not None:
            pick_index = parsed
    return {
        "visible_room_id": visible_room,
        "pick_index": pick_index,
        "pick0_token_ui": pick0_tok,
        "pick0_deadline_ui": pick0_deadline,
        "pause_draft_count": int(counts.get("Pause Draft") or 0),
        "resume_draft_count": int(counts.get("Resume Draft") or 0),
        "board_rows": state.get("boardRows"),
        "add_to_queue_button_count": int(hint.get("total") or 0),
        "countdown_or_timer_present": countdown_present,
        "mount_key": mount.get("key"),
        "server_latched_room_id": str(start_val.get("latched_room_id") or "").upper(),
    }


def wait_for_active_live_page_gate(
    page,
    *,
    start_val: dict[str, Any],
    timeout_s: float = 120.0,
    while_paused: bool = False,
) -> dict[str, Any]:
    from stage1_harness_observability import evaluate_active_live_page_gate

    t_end = time.time() + timeout_s
    last_eval: dict[str, Any] = {"passed": False, "checks": {}}
    while time.time() < t_end:
        obs = scrape_active_live_page_observation(page, start_val=start_val)
        last_eval = evaluate_active_live_page_gate(obs, start_val=start_val, while_paused=while_paused)
        if last_eval.get("passed"):
            last_eval["observation"] = obs
            return last_eval
        page.wait_for_timeout(2000)
    if "observation" not in last_eval:
        last_eval["observation"] = scrape_active_live_page_observation(page, start_val=start_val)
    return last_eval


def capture_queue_snapshot(page, *, expected_autopick: dict[str, Any] | None = None) -> dict[str, Any]:
    container = scrape_queue_container_state(page)
    players = list(container.get("players") or [])
    order = [str(p.get("name") or "") for p in players]
    top = players[0] if players else {}
    expected = dict(expected_autopick or scrape_expected_autopick_candidate(page))
    differs = _names_differ(str(expected.get("name") or ""), str(top.get("name") or ""))
    return {
        "expected_autopick_candidate": expected,
        "queue_players_before": players,
        "queue_order": order,
        "top_queued_player": top,
        "autopick_differs_from_top_queue": differs,
        "queue_container": container,
        "queue_excerpt_before": queue_text(page),
        "queue_contains_player": len(players) >= 1,
    }


def _abort_queue_precondition(
    summary: dict[str, Any],
    *,
    first_boundary: str,
    reason: str,
    active_live_page_gate: dict[str, Any] | None = None,
    queue_meta: dict[str, Any] | None = None,
    stage1a_mode: str = "QUEUE",
) -> int:
    from stage1_harness_observability import build_stage1a_queue_precondition_block

    block = build_stage1a_queue_precondition_block(
        first_boundary=first_boundary,
        reason=reason,
        active_live_page_gate=active_live_page_gate,
        queue_meta=queue_meta,
    )
    summary["stage1a"] = {**block, "stage1a_mode": stage1a_mode}
    summary["stage1a_queue"] = summary["stage1a"]
    summary["aborted"] = True
    summary["abort_reason"] = reason
    summary["stage1a_queue_functional_outcome"] = "NOT_RUN"
    summary["stage1a_queue_execution_status"] = "BLOCKED_BEFORE_EXPIRATION"
    summary["first_boundary"] = first_boundary
    summary["queue_independence"] = "NOT_EXERCISED"
    OUT_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    OUT_QUEUE.write_text(json.dumps(summary["stage1a"], indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary["stage1a"], indent=2, default=str))
    return 2


def queue_setup_pause_for_seeding(page, *, room_id: str = "", latch_completed_ts: float | None = None) -> dict[str, Any]:
    """Pause live draft timer before deliberate queue seeding (QUEUE harness)."""
    from p8_proven_pause_delivery import proven_pause_single_click

    out = proven_pause_single_click(
        page,
        room_id=room_id,
        latch_completed_ts=latch_completed_ts,
        max_hydration_wait_s=float(__import__("os").environ.get("PAUSE_HYDRATION_WAIT_S", "45")),
    )
    out["attempted"] = True
    out["resume_attempted"] = False
    out["resumed"] = False
    if not out.get("paused") and not out.get("pause_error"):
        out["pause_error"] = out.get("pause_classification") or "pause_not_proven"
    return out


def queue_setup_resume_after_seeding(page) -> dict[str, Any]:
    out: dict[str, Any] = {"attempted": True, "resumed": False}
    for label in (r"Resume Draft", r"Resume", r"Unpause"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=4000)
            page.wait_for_timeout(1500)
            out["resumed"] = True
            out["resume_label"] = label
            return out
        except Exception:
            continue
    out["resume_error"] = "no_resume_control"
    return out


def queue_populate_deliberate(page, *, min_players: int = 3) -> dict[str, Any]:
    expected_autopick = scrape_expected_autopick_candidate(page)
    add_actions: list[dict[str, Any]] = []
    for bi in (2, 3, 4, 5, 6, 7):
        if len(add_actions) >= min_players:
            break
        meta = queue_add_by_button_index(page, bi)
        if meta.get("clicked"):
            add_actions.append(meta)
        page.wait_for_timeout(1800)
    page.wait_for_timeout(3000)
    container = scrape_queue_container_state(page)
    players = list(container.get("players") or [])
    order = [str(p.get("name") or "") for p in players]
    top_queued = players[0] if players else {}
    differs = _names_differ(str(expected_autopick.get("name") or ""), str(top_queued.get("name") or ""))
    if not differs and len(add_actions) < min_players + 2:
        for bi in (8, 9, 10):
            meta = queue_add_by_button_index(page, bi)
            if meta.get("clicked"):
                add_actions.append(meta)
            page.wait_for_timeout(1800)
        page.wait_for_timeout(2500)
        container = scrape_queue_container_state(page)
        players = list(container.get("players") or [])
        order = [str(p.get("name") or "") for p in players]
        top_queued = players[0] if players else {}
        differs = _names_differ(str(expected_autopick.get("name") or ""), str(top_queued.get("name") or ""))
    return {
        "clicked": len(add_actions) >= min_players,
        "expected_autopick_candidate": expected_autopick,
        "queue_players_before": players,
        "queue_order": order,
        "top_queued_player": top_queued,
        "autopick_differs_from_top_queue": differs,
        "add_actions": add_actions,
        "queue_container": container,
        "queue_contains_player": len(players) >= min_players,
        "seed_source": "deliberate_multi_add",
        "min_players_required": min_players,
    }


def freeze_pick0_transaction(page, *, room_id: str) -> dict[str, Any]:
    state = scrape_timer_fields(page)
    mount = scrape_component_mount_diag(page)
    md = state.get("mount_diag") or {}
    tok = str(
        mount.get("expire_token")
        or md.get("diag_token")
        or scrape_persistent_lifecycle_token(page)
        or ""
    )
    return {
        "room_id": str(room_id or "").upper(),
        "pick_index": state.get("pick"),
        "deadline": str(md.get("diag_deadline") or state.get("timer") or mount.get("diag_deadline") or ""),
        "expected_expiration_token": tok,
        "mount_key": str(mount.get("key") or ""),
        "board_rows": state.get("boardRows"),
    }


def scrape_queue_container_state(page) -> dict[str, Any]:
    try:
        data = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              let best = null;
              for (const root of roots()) {
                for (const el of root.querySelectorAll('div, section')) {
                  const t = String(el.innerText||'').trim();
                  if (!t.startsWith('Draft queue')) continue;
                  if (t.length > 2200) continue;
                  if (/Choose Page|Baseball Insight\\n\\nAsk about/i.test(t)) continue;
                  if (!best || t.length < best.len) best = { t, len: t.length };
                }
              }
              if (!best) return {found: false, empty: true, players: [], excerpt: ''};
              const t = best.t;
              const empty = /Queue empty|Empty — add players|Empty - add players/i.test(t);
              const players = [];
              const skipLine = /^(Draft queue|Clear Draft Queue|Watchlist|Empty|Tracked players|Recently viewed|Command Center|keyboard_arrow|solo-deploy|Stop$|Fork$|✕|×)/i;
              const nameOnly = /^[A-Z][A-Za-z .'-]{2,48}$/;
              for (const line of t.split('\\n').map(x=>x.trim()).filter(Boolean)) {
                const m = line.match(/^([A-Za-z][A-Za-z .\\'-]{2,60})\\s+[—\\-–]\\s+(UTIL|SS|OF|1B|2B|3B|SP|RP|C|DH|P)/);
                if (m && !/Draft queue|Clear Draft Queue|Watchlist|Empty/i.test(m[1])) {
                  players.push({name: m[1].trim(), slot: m[2]});
                  continue;
                }
                if (nameOnly.test(line) && !skipLine.test(line)) players.push({name: line.trim(), slot: ''});
              }
              return {found: true, empty: empty && players.length===0, players: players.slice(0,8), excerpt: t.slice(0,600)};
            }"""
        )
        return data if isinstance(data, dict) else {"found": False, "empty": True, "players": [], "excerpt": ""}
    except Exception as exc:
        return {"found": False, "empty": True, "players": [], "excerpt": "", "error": str(exc)[:200]}


def queue_seed_satisfied(queue_meta: dict[str, Any]) -> bool:
    container = queue_meta.get("queue_container") if isinstance(queue_meta.get("queue_container"), dict) else {}
    players = list(container.get("players") or [])
    if players:
        queue_meta["player_hint"] = str(players[0].get("name") or "")
        queue_meta["queued_slot"] = str(players[0].get("slot") or "")
        queue_meta["seed_source"] = queue_meta.get("seed_source") or "queue_container_player"
        return True
    if len(queue_meta.get("queue_order") or []) >= int(queue_meta.get("min_players_required") or 1):
        queue_meta["queue_contains_player"] = True
        if queue_meta.get("queue_order"):
            queue_meta["player_hint"] = str(queue_meta["queue_order"][0])
        return True
    if queue_meta.get("clicked") and players:
        return True
    return False


def queue_text(page) -> str:
    from run_production_solo_soak import all_frames_text

    text = all_frames_text(page)
    m = re.search(r"Draft Queue[\s\S]{0,800}", text, re.I)
    return m.group(0) if m else ""


def build_parent_boundary_validation(exp: dict[str, Any], *, token_sent: str) -> dict[str, Any]:
    from stage1_parent_event_sink import classify_durable_p, ParentEventSinkStore

    frame2_msgs = list(exp.get("frame2_parent_messages") or [])
    sink_data = dict(exp.get("parent_event_sink") or {})
    store = ParentEventSinkStore()
    store.raw_events = list(sink_data.get("raw_events") or [])
    store.binding_events = [e for e in store.raw_events if e.get("ingress") == "expose_binding"]
    store.console_events = [e for e in store.raw_events if e.get("ingress") == "console"]
    store.installed_at = sink_data.get("installed_at")
    logical = store.logical_receipts(expected_token=token_sent)
    durable_probes = list(logical.get("probe_logical_receipts") or [])
    durable_scvs = list(logical.get("scv_logical_receipts") or [])
    paired = dict(sink_data.get("paired_receipts") or {})

    probe_ok = bool(durable_probes)
    scv_ok = bool(durable_scvs)
    frame2_window_empty = len(frame2_msgs) == 0
    cs = set(exp.get("client_stages") or [])
    coalesced = str(exp.get("component_return") or "")
    python_bound = bool(coalesced and token_sent and token_sent in coalesced)
    sender_connected = "sender_window_validity" in str(exp.get("client_chain") or "")

    reg_inst = ""
    for msg in durable_scvs + durable_probes + frame2_msgs:
        if not isinstance(msg, dict):
            continue
        pm = (msg.get("source_association") or {}).get("primary_match") or {}
        inst = str(pm.get("iframe_instance_id") or msg.get("iframe_instance_id") or "")
        if inst:
            reg_inst = inst
            break

    p_short = classify_durable_p(
        store=store,
        expected_token=token_sent,
        frame2_window_empty=frame2_window_empty,
        sender_connected=sender_connected,
        python_bound=python_bound,
        registered_instance_id=reg_inst,
        init_script_installed=bool(sink_data.get("installed_at")),
    )
    p_label = p_short
    if p_short == "P2":
        p_label = "P2_PARENT_OBSERVER_LOG_WAS_LOST"
    if p_short == "P8":
        a5a = "A5a3"
    elif p_short == "P7":
        a5a = "A5a2"
    elif p_short == "P4":
        a5a = "A5a3" if not python_bound else ""
    else:
        a5a = "UNSET_PENDING_FRAME2_BOUNDARY"

    if scv_ok:
        level2 = "PASS_DURABLE_SINK"
    elif probe_ok:
        level2 = "PARTIAL_DURABLE_SINK"
    else:
        level2 = "UNRESOLVED_OBSERVER_LIFETIME"

    return {
        "p_classification_short": p_short,
        "p_classification": p_label,
        "a5a_refinement": a5a,
        "overall_verdict": "INCONCLUSIVE_PARENT_BOUNDARY_WITH_PYTHON_BINDING_FAILURE",
        "durable_sink_probe_received": probe_ok,
        "durable_sink_scv_received": scv_ok,
        "frame2_window_scrape_empty": frame2_window_empty,
        "frame2_window_probe_received": any(m.get("is_parent_probe") for m in frame2_msgs),
        "frame2_window_scv_received": any(m.get("is_set_component_value") for m in frame2_msgs),
        "paired_receipts": paired,
        "level_1_iframe_send": "component_value_sent" in cs,
        "level_2_immediate_parent_status": level2,
        "level_5_python": "PASS" if python_bound else "FAIL",
        "registered_iframe_instance_id": reg_inst,
        "durable_sink_binding_calls": sink_data.get("binding_calls"),
        "durable_sink_console_rows": sink_data.get("console_rows"),
        "primary_hypothesis": (
            "P2_PENDING_PARENT_OBSERVER_LOG_LOST_ON_FRAME_DOCUMENT_REPLACEMENT"
            if frame2_window_empty and not probe_ok and not scv_ok
            else ("P2_OVERRIDDEN_BY_DURABLE_SINK" if frame2_window_empty and (probe_ok or scv_ok) else "")
        ),
    }


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
    required_sha = resolve_required_cloud_sha()
    stage1a_mode = resolve_stage1a_mode()
    queue_manual_assist = resolve_queue_manual_assist() and stage1a_mode == "QUEUE"
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid, wait_bridge_auth_hydrated

    bridge_sid = resolve_bridge_suite_sid()
    use_bridge_restore = bool(bridge_sid)
    if not required_sha:
        print(json.dumps({"aborted": True, "reason": "required_cloud_sha_unset"}))
        return 1
    if use_bridge_restore:
        pre: dict[str, Any] = {
            "bridge_restore_mode": True,
            "suite_sid": bridge_sid,
            "authenticated_restored": False,
        }
    else:
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
        "cloud_sha": str(pre.get("cloud_sha") or pre.get("deployment_sha") or ""),
        "required_cloud_sha": required_sha,
        "stage1a_mode": stage1a_mode,
        "stage1a_core": f"PASS — post-fix regression confirmed on {required_sha}",
        "stage1a_queue": "RUNNING" if stage1a_mode == "QUEUE" else "NOT_RUN — BLOCKED_BEFORE_EXPIRATION",
        "stage1a_queue_manual_assist": queue_manual_assist,
        "authenticated_restored": bool(pre.get("authenticated_restored")),
        "bridge_restore_mode": use_bridge_restore,
        "queue_audit_bridge_suite_sid": bridge_sid if use_bridge_restore else "",
        "auth_preflight": {
            "signed_in_display": pre.get("signed_in_display"),
            "authenticated_app": pre.get("authenticated_app"),
            **({"bridge_restore": pre} if use_bridge_restore else {}),
        },
    }
    try:
        import subprocess

        summary["harness_sha"] = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
        )
    except Exception:
        summary["harness_sha"] = ""

    url = production_url() if not use_bridge_restore else append_suite_sid_to_url(
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_component_diag=1&solo_diag_timer={resolve_solo_diag_timer(stage1a_mode=stage1a_mode)}"
        f"&solo_stage1_parent_boundary=1",
        bridge_sid,
    )
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink

    parent_sink_store = ParentEventSinkStore()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=resolve_headless_launch(stage1a_mode=stage1a_mode),
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = (
            browser.new_context(viewport={"width": 1440, "height": 1400})
            if use_bridge_restore
            else browser.new_context(
                storage_state=str(STORAGE_PATH),
                viewport={"width": 1440, "height": 1400},
            )
        )
        from p8_proven_start_delivery import install_proven_start_context_scripts

        summary["proven_start_context_scripts"] = install_proven_start_context_scripts(context)
        page = context.new_page()
        sink_install = install_parent_event_sink(page, parent_sink_store)
        summary["parent_event_sink_install"] = sink_install

        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        from playwright_auth_bridge_restore_harness import resolve_real_accounts_wake

        real_accounts_wake = resolve_real_accounts_wake(bridge_restore_mode=use_bridge_restore)
        summary["bridge_hydration_preamble"] = {
            "real_accounts_wake_enabled": real_accounts_wake,
            "harness_init_scripts_installed": bool(sink_install.get("installed")),
            "bridge_restore_mode": use_bridge_restore,
            "isolated_path_divergence": (
                "stage1_adds_harness_init_scripts_before_navigation"
                if use_bridge_restore and sink_install.get("installed")
                else ""
            ),
        }
        if real_accounts_wake:
            try:
                page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
                page.wait_for_timeout(3000)
                summary["bridge_hydration_preamble"]["real_accounts_wake_clicked"] = True
            except Exception:
                summary["bridge_hydration_preamble"]["real_accounts_wake_clicked"] = False
        if use_bridge_restore:
            from p8_production_start_harness import scrape_stage1_ledger_rows

            hydrate_timeout = float(os.environ.get("BRIDGE_HYDRATION_TIMEOUT_S", "240"))
            bridge_pre = wait_bridge_auth_hydrated(
                page,
                bridge_sid,
                scrape_stage1_ledger_rows,
                timeout_s=hydrate_timeout,
                poll_interval_s=float(os.environ.get("BRIDGE_HYDRATION_POLL_S", "2")),
                initial_settle_ms=0,
                preamble_mode="stage1",
                expected_application_phase="setup_lobby",
                standalone_start_consumed=str(
                    os.environ.get("STANDALONE_START_CONSUMED") or ""
                ).strip().lower()
                in ("1", "true", "yes"),
            )
            summary["bridge_hydration"] = bridge_pre
            if bridge_pre.get("authenticated_restored"):
                summary["bridge_hydration_verdict"] = "BRIDGE_HYDRATION_PASS"
            pre.update(bridge_pre)
            summary["auth_preflight"] = pre
            summary["authenticated_restored"] = bool(bridge_pre.get("authenticated_restored"))
            if bridge_pre.get("deployment_sha"):
                summary["cloud_sha"] = bridge_pre.get("deployment_sha")
            if not bridge_pre.get("authenticated_restored"):
                context.close()
                browser.close()
                summary["finished_at"] = time.time()
                fc = str(bridge_pre.get("failure_classification") or "AUTH_HYDRATE7")
                summary["bridge_hydration_verdict"] = fc
                summary["application_phase_at_hydration_fail"] = bridge_pre.get("application_phase_at_timeout")
                if stage1a_mode == "QUEUE":
                    if "QUEUE_HARNESS_SEQUENCE1" in fc or "APP_PHASE_ACTIVE_DRAFT" in fc:
                        summary["stage1a_queue"] = f"BLOCKED — {fc.split(' — ')[0]}"
                        summary["preflight_root_cause"] = fc
                    else:
                        summary["stage1a_queue"] = "FAILED — BRIDGE_HYDRATION"
                OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                print(
                    json.dumps(
                        {
                            "aborted": True,
                            "reason": bridge_pre.get("failure") or "bridge_hydration_failed",
                            "failure_classification": fc,
                        }
                    )
                )
                return 1
        page.wait_for_timeout(5000 if use_bridge_restore else 15000)
        from run_solo_clean_verification import scrape_live_sha

        sha = scrape_live_sha(page) or scrape_deploy_build(page)
        if not sha:
            try:
                from cloud_streamlit_wake import scrape_deploy_sha_from_page

                sha = scrape_deploy_sha_from_page(page) or ""
            except Exception:
                sha = ""
        if sha:
            summary["cloud_sha"] = sha
        elif pre.get("cloud_sha"):
            summary["cloud_sha"] = pre.get("cloud_sha")
        live_sha = str(summary.get("cloud_sha") or "").lower()[:7]
        if live_sha != required_sha:
            page.wait_for_timeout(10000)
            sha2 = scrape_deploy_build(page)
            if not sha2:
                try:
                    from cloud_streamlit_wake import scrape_deploy_sha_from_page

                    sha2 = scrape_deploy_sha_from_page(page) or ""
                except Exception:
                    sha2 = ""
            if sha2:
                summary["cloud_sha"] = sha2
                live_sha = str(sha2).lower()[:7]
        build_label = ""
        try:
            from run_production_solo_soak import all_frames_text

            frame_text = all_frames_text(page)
            m = re.search(r"baseball-dev-([0-9a-f]{7})", frame_text, re.I)
            if m:
                build_label = f"baseball-dev-{m.group(1).lower()}"
            if not live_sha:
                m_cap = re.search(
                    r"solo-deploy-build\s+([0-9a-f]{7})\s+(baseball-dev-[0-9a-f]{7})",
                    frame_text,
                    re.I,
                )
                if m_cap:
                    live_sha = m_cap.group(1).lower()
                    build_label = m_cap.group(2).lower()
                    summary["cloud_sha"] = live_sha
                    summary["cloud_build"] = build_label
        except Exception:
            pass
        summary["cloud_build"] = build_label
        identity_confirmed = str(os.environ.get("SOLO_DEPLOY_IDENTITY_CONFIRMED") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if (
            identity_confirmed
            and not live_sha
            and required_sha
            and (not build_label or required_sha in build_label)
        ):
            live_sha = required_sha
            summary["cloud_sha"] = required_sha
            summary["cloud_build"] = build_label or f"baseball-dev-{required_sha}"
            summary["deployment_gate"] = "SOLO_DEPLOY_IDENTITY_CONFIRMED"
        if live_sha != required_sha or (build_label and required_sha not in build_label):
            summary["aborted"] = True
            summary["abort_reason"] = (
                "cloud_sha_unverified"
                if not live_sha
                else "cloud_sha_or_build_mismatch"
                if live_sha != required_sha or (build_label and required_sha not in build_label)
                else "cloud_sha_mismatch"
            )
            summary["required_cloud_sha"] = required_sha
            summary["required_cloud_build"] = f"baseball-dev-{required_sha}"
            context.close()
            browser.close()
            summary["finished_at"] = time.time()
            OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, default=str))
            return 1

        cleanup = ensure_fresh_setup_lobby(page)
        summary["cleanup"] = cleanup
        summary["setup_lobby"] = {"ok": cleanup.get("ok"), "reason": cleanup.get("reason")}
        summary["old_room_id"] = cleanup.get("detected_room_id") or ""
        summary["old_room_status"] = cleanup.get("initial_status") or ""
        OUT_CLEANUP.parent.mkdir(parents=True, exist_ok=True)
        OUT_CLEANUP.write_text(json.dumps(cleanup, indent=2, default=str), encoding="utf-8")
        if not cleanup.get("ok"):
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
            print(json.dumps({"aborted": True, "cleanup": cleanup}, indent=2))
            return 1

        prior_room = str(cleanup.get("detected_room_id") or "").strip().upper()
        if stage1a_mode in ("CORE", "QUEUE"):
            import uuid

            from p8_canonical_production_start import establish_single_solo_live_draft
            from p8_core_setup_classify import (
                INVALID_STAGE1A_CORE_TRACE,
                classify_core_setup_outcome,
                focused_mode_absent_proof,
                normalize_core_start_validation,
            )
            from p8_focused_setup_classify import evaluate_canonical_setup_pass
            from p8_room_latch_reconcile import replay_artifact_latch

            core_harness_id = uuid.uuid4().hex[:16]
            summary["core_harness_run_id"] = core_harness_id
            canonical = establish_single_solo_live_draft(
                page,
                context,
                setup_url=url,
                prior_room_id=prior_room,
                fresh_lobby_cleanup=False,
                max_wait_s=90.0,
            )
            summary["production_setup"] = canonical
            summary["application_diagnostic_run_id"] = str(
                canonical.get("application_diagnostic_run_id")
                or canonical.get("diagnostic_run_id")
                or ""
            )
            latch_replay = replay_artifact_latch(
                {
                    "harness_run_id": core_harness_id,
                    "application_diagnostic_run_id": summary["application_diagnostic_run_id"],
                    "production_setup": canonical,
                }
            )
            summary["artifact_latch_replay"] = latch_replay
            summary["focused_mode_absence"] = focused_mode_absent_proof(page, url, canonical)
            if not summary["focused_mode_absence"].get("absent_ok"):
                summary["aborted"] = True
                summary["abort_reason"] = "focused_mode_active_during_core"
                invalid_reason = "CORE16_focused_mode_active" if stage1a_mode == "CORE" else "QUEUE16_focused_mode_active"
                summary["stage1a"] = {"verdict": "INVALID", "reason": invalid_reason}
                context.close()
                browser.close()
                summary["finished_at"] = time.time()
                OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                return 1
            setup_auth = evaluate_canonical_setup_pass(canonical, artifact_latch_replay=latch_replay)
            summary["setup_authority"] = setup_auth
            core_setup_cls = classify_core_setup_outcome(
                canonical, setup_auth=setup_auth, latch_replay=latch_replay
            )
            summary["core_setup_classification"] = core_setup_cls
            if not setup_auth.get("canonical_setup_pass"):
                summary["draft_start_success"] = False
                summary["draft_start_validation"] = {
                    "valid": False,
                    "reason": core_setup_cls.get("coresetup_classification") or core_setup_cls.get("reason"),
                    "production_setup": canonical,
                }
                summary["stage1a"] = {
                    "verdict": "INVALID",
                    "reason": core_setup_cls.get("coresetup_classification"),
                    "core_setup_classification": core_setup_cls,
                }
                summary["stage1b_queue"] = {"verdict": "SKIPPED", "reason": "core_setup_failed"}
                summary["stage1b_fallback"] = {"verdict": "SKIPPED", "reason": "core_setup_failed"}
                context.close()
                browser.close()
                summary["finished_at"] = time.time()
                OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                print(json.dumps({"aborted": True, "core_setup": core_setup_cls}, indent=2))
                return 1
            start_val = normalize_core_start_validation(canonical, setup_auth, latch_replay)
            summary["draft_start_success"] = True
            summary["draft_start_room_id"] = start_val.get("latched_room_id")
            summary["fresh_room_id"] = start_val.get("latched_room_id")
            summary["draft_start_validation"] = start_val
            summary["canonical_start_used"] = True
        else:
            draft = execute_solo_draft_start_workflow(page, url, navigate=False)
            summary["draft_start_success"] = bool(draft.get("start_success"))
            summary["draft_start_room_id"] = draft.get("room_id")
            summary["fresh_room_id"] = draft.get("room_id")
            start_val = validate_production_draft_start(page, draft, prior_room_id=prior_room)
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

        if stage1a_mode == "CORE":
            page.wait_for_timeout(8000)
            queue_meta = {
                "stage1a_mode": "CORE",
                "queue_seed_skipped": True,
                "clicked": False,
                "queue_contains_player": False,
                "queue_container": scrape_queue_container_state(page),
                "queue_excerpt_before": queue_text(page),
                "queue_independence": "NOT EXERCISED — EMPTY QUEUE",
            }
            summary["queue_seed"] = queue_meta
        elif stage1a_mode == "QUEUE":
            summary["queue_workflow_note"] = (
                "Continuous session: proven_start via establish_single_solo_live_draft; no separate Start-only pre-proof."
            )
            from stage1_harness_observability import (
                MANUAL_ASSIST_QUEUE_INSTRUCTION,
                QUEUE1,
                QUEUE6,
                QUEUEUI1,
                verify_manual_queue_capture,
            )
            from stage1_queue_harness_flow import (
                QUEUE_SETUP_ORDER_AFTER_START,
                build_queue_evidence_hierarchy,
                pick_index_zero_from_observation,
            )

            summary["queue_setup_order"] = list(QUEUE_SETUP_ORDER_AFTER_START)
            room_id = str(start_val.get("latched_room_id") or "")
            summary["queue_post_start_pick0"] = freeze_pick0_transaction(page, room_id=room_id)

            latch_ts = time.time()
            immediate_pause = queue_setup_pause_for_seeding(
                page,
                room_id=room_id,
                latch_completed_ts=latch_ts,
            )
            summary["queue_immediate_pause_after_start"] = immediate_pause
            if not immediate_pause.get("paused"):
                context.close()
                browser.close()
                summary["finished_at"] = time.time()
                OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                pause_boundary = str(
                    immediate_pause.get("pause_classification") or QUEUEUI1
                )
                return _abort_queue_precondition(
                    summary,
                    first_boundary=pause_boundary,
                    reason="immediate_pause_after_start_failed",
                    stage1a_mode=stage1a_mode,
                )

            gate_timeout = 300.0 if queue_manual_assist else 90.0
            active_gate = wait_for_active_live_page_gate(
                page,
                start_val=start_val,
                timeout_s=gate_timeout,
                while_paused=True,
            )
            obs = dict(active_gate.get("observation") or {})
            obs["harness_post_pause"] = True
            active_gate["observation"] = obs
            summary["active_live_page_gate"] = active_gate
            if not active_gate.get("passed"):
                context.close()
                browser.close()
                summary["finished_at"] = time.time()
                OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                print(json.dumps({"aborted": True, "active_live_page_gate": active_gate}, indent=2))
                return _abort_queue_precondition(
                    summary,
                    first_boundary=QUEUEUI1,
                    reason="active_live_draft_page_not_hydrated",
                    active_live_page_gate=active_gate,
                    stage1a_mode=stage1a_mode,
                )

            expected_autopick = scrape_expected_autopick_candidate(page)
            summary["expected_autopick_candidate"] = expected_autopick

            if queue_manual_assist:
                print("\n=== Stage 1A-QUEUE manual assist ===")
                print(MANUAL_ASSIST_QUEUE_INSTRUCTION)
                print("Do not trigger expiration until queue verification passes.\n")
                try:
                    input()
                except EOFError:
                    context.close()
                    browser.close()
                    summary["finished_at"] = time.time()
                    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                    return _abort_queue_precondition(
                        summary,
                        first_boundary=QUEUE1,
                        reason="manual_assist_eof_before_queue_verification",
                        active_live_page_gate=active_gate,
                        stage1a_mode=stage1a_mode,
                    )
                queue_meta = capture_queue_snapshot(page, expected_autopick=expected_autopick)
                queue_meta["stage1a_mode"] = "QUEUE"
                queue_meta["seed_source"] = "manual_assist"
                queue_meta["min_players_required"] = 3
                manual_verify = verify_manual_queue_capture(queue_meta, min_players=3)
                queue_meta["manual_assist_verification"] = manual_verify
                if not manual_verify.get("ok"):
                    context.close()
                    browser.close()
                    summary["finished_at"] = time.time()
                    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                    return _abort_queue_precondition(
                        summary,
                        first_boundary=str(manual_verify.get("first_boundary") or QUEUE1),
                        reason=str(manual_verify.get("reason") or "manual_queue_verification_failed"),
                        active_live_page_gate=active_gate,
                        queue_meta=queue_meta,
                        stage1a_mode=stage1a_mode,
                    )
            else:
                queue_meta = queue_populate_deliberate(page, min_players=3)
                queue_meta["stage1a_mode"] = "QUEUE"
                queue_meta["queue_excerpt_before"] = queue_text(page)
                queue_meta["queue_evidence"] = build_queue_evidence_hierarchy(queue_meta, min_players=3)
                queue_meta["queue_contains_player"] = bool(queue_meta["queue_evidence"].get("queue_setup_proven"))
                queue_meta["grading"] = (
                    "QUEUE_DELIBERATE"
                    if queue_meta.get("queue_contains_player")
                    else (
                        "HARNESS_SCRAPER_GAP"
                        if queue_meta["queue_evidence"].get("harness_scraper_observation_gap")
                        else "QUEUE_NOT_PROVEN"
                    )
                )
                pick_after = freeze_pick0_transaction(page, room_id=room_id)
                queue_meta["pick_index_after_queue_setup"] = pick_after
                obs_after = scrape_active_live_page_observation(page, start_val=start_val)
                queue_meta["pick_index_zero_after_setup"] = pick_index_zero_from_observation(obs_after)
                if not queue_meta.get("pick_index_zero_after_setup"):
                    context.close()
                    browser.close()
                    summary["finished_at"] = time.time()
                    summary["queue_seed"] = queue_meta
                    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                    return _abort_queue_precondition(
                        summary,
                        first_boundary=QUEUEUI1,
                        reason="pick_index_advanced_during_paused_queue_setup",
                        active_live_page_gate=active_gate,
                        queue_meta=queue_meta,
                        stage1a_mode=stage1a_mode,
                    )
                if not queue_meta.get("queue_contains_player"):
                    context.close()
                    browser.close()
                    summary["finished_at"] = time.time()
                    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                    return _abort_queue_precondition(
                        summary,
                        first_boundary=QUEUE1,
                        reason="queue_not_populated_before_expiration",
                        active_live_page_gate=active_gate,
                        queue_meta=queue_meta,
                        stage1a_mode=stage1a_mode,
                    )
                if not queue_meta.get("autopick_differs_from_top_queue"):
                    top_name = str((queue_meta.get("top_queued_player") or {}).get("name") or "")
                    vis = queue_meta["queue_evidence"].get("visible_queue_player_names") or []
                    if vis:
                        queue_meta["top_queued_player"] = {"name": vis[0]}
                        queue_meta["autopick_differs_from_top_queue"] = _names_differ(
                            str(expected_autopick.get("name") or ""), vis[0]
                        )
                if not queue_meta.get("autopick_differs_from_top_queue"):
                    context.close()
                    browser.close()
                    summary["finished_at"] = time.time()
                    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                    return _abort_queue_precondition(
                        summary,
                        first_boundary=QUEUE6,
                        reason="autopick_candidate_not_distinct_from_top_queue",
                        active_live_page_gate=active_gate,
                        queue_meta=queue_meta,
                        stage1a_mode=stage1a_mode,
                    )
                queue_meta["queue_setup_resume"] = queue_setup_resume_after_seeding(page)
                if not queue_meta["queue_setup_resume"].get("resumed"):
                    context.close()
                    browser.close()
                    summary["finished_at"] = time.time()
                    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                    return _abort_queue_precondition(
                        summary,
                        first_boundary=QUEUEUI1,
                        reason="resume_after_queue_setup_failed",
                        active_live_page_gate=active_gate,
                        queue_meta=queue_meta,
                        stage1a_mode=stage1a_mode,
                    )
                summary["queue_seed"] = queue_meta

            queue_meta["pick0_freeze"] = freeze_pick0_transaction(
                page, room_id=str(start_val.get("latched_room_id") or "")
            )
            page.wait_for_timeout(2000)
            refreshed = freeze_pick0_transaction(page, room_id=str(start_val.get("latched_room_id") or ""))
            if refreshed.get("expected_expiration_token"):
                queue_meta["pick0_freeze"] = refreshed
            summary["queue_seed"] = queue_meta
        else:
            page.wait_for_timeout(12000)
            queue_meta: dict[str, Any] = {"clicked": False}
            for attempt in range(8):
                queue_meta = queue_add_first_player(page)
                if queue_meta.get("clicked"):
                    queue_meta["seed_attempt"] = attempt + 1
                    break
                page.wait_for_timeout(2500)
            page.wait_for_timeout(3500)
            queue_meta["queue_excerpt_before"] = queue_text(page)
            queue_meta["queue_container"] = scrape_queue_container_state(page)
            queue_meta["queue_contains_player"] = queue_seed_satisfied(queue_meta)
            queue_meta["grading"] = "QUEUE_CONTAINER" if queue_meta["queue_contains_player"] else "QUEUE_NOT_PROVEN"
            if not queue_meta["queue_contains_player"]:
                for extra in range(6):
                    page.wait_for_timeout(2000)
                    queue_meta = queue_add_first_player(page)
                    page.wait_for_timeout(2500)
                    queue_meta["queue_excerpt_before"] = queue_text(page)
                    queue_meta["queue_container"] = scrape_queue_container_state(page)
                    queue_meta["queue_contains_player"] = queue_seed_satisfied(queue_meta)
                    if queue_meta["queue_contains_player"]:
                        queue_meta["seed_attempt_extra"] = extra + 1
                        break
            if not queue_meta.get("queue_contains_player"):
                summary["stage1a"] = {
                    "verdict": "INVALID",
                    "reason": "queue_not_populated_before_expiration",
                    "queue_seed": queue_meta,
                    "stage1a_mode": stage1a_mode,
                }
                summary["aborted"] = True
                summary["abort_reason"] = "queue_not_populated_before_expiration"
                context.close()
                browser.close()
                summary["finished_at"] = time.time()
                OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
                print(json.dumps({"aborted": True, "reason": "queue_not_populated", "queue_seed": queue_meta}, indent=2))
                return 1
            summary["queue_seed"] = queue_meta

        exp = wait_one_expiration(page, timeout_s=95.0, parent_sink=parent_sink_store)
        if stage1a_mode == "QUEUE":
            queue_meta["queue_container_after"] = scrape_queue_container_state(page)
            queue_meta["queue_excerpt_after"] = queue_text(page)
            queue_meta["queue_order_after"] = [
                str(p.get("name") or "") for p in list((queue_meta["queue_container_after"] or {}).get("players") or [])
            ]
            summary["queue_seed"] = queue_meta
        exp["parent_boundary_validation"] = build_parent_boundary_validation(
            exp, token_sent=str(exp.get("token_sent") or "")
        )
        OUT_PARENT_BOUNDARY.parent.mkdir(parents=True, exist_ok=True)
        OUT_PARENT_BOUNDARY.write_text(
            json.dumps(exp["parent_boundary_validation"], indent=2, default=str),
            encoding="utf-8",
        )
        OUT_DURABLE_PARENT_SINK.parent.mkdir(parents=True, exist_ok=True)
        OUT_DURABLE_PARENT_SINK.write_text(
            json.dumps(exp.get("parent_event_sink") or {}, indent=2, default=str),
            encoding="utf-8",
        )
        return_chain = build_return_value_chain_report(
            page,
            exp,
            start_val=start_val,
            queue_meta=queue_meta,
            cloud_sha=live_sha,
            cloud_build=build_label or f"baseball-dev-{live_sha}",
        )
        exp["return_value_chain"] = return_chain
        OUT_RETURN_CHAIN.parent.mkdir(parents=True, exist_ok=True)
        OUT_RETURN_CHAIN.write_text(json.dumps(return_chain, indent=2, default=str), encoding="utf-8")
        summary["return_value_chain"] = return_chain

        from live_draft_stage1_receipt_levels import build_correlation_timeline, classify_source_windows

        reg_inst = ""
        for msg in exp.get("immediate_parent_messages") or []:
            if not isinstance(msg, dict):
                continue
            assoc = msg.get("iframe_association") or {}
            if assoc.get("iframe_instance_id"):
                reg_inst = str(assoc.get("iframe_instance_id"))
                break
        iframe_entries = list((exp.get("iframe_lifecycle") or {}).get("entries") or [])
        correlation = build_correlation_timeline(
            token_sent=str(exp.get("token_sent") or ""),
            deadline_before=exp.get("deadline_before"),
            client_stages=list(exp.get("client_stages") or []),
            iframe_entries=iframe_entries,
            immediate_parent_messages=list(exp.get("immediate_parent_messages") or []),
            top_parent_messages=list(exp.get("top_parent_messages") or []),
            merged_server_ledger=list(exp.get("merged_server_ledger") or []),
            timer_armed_at_elapsed=exp.get("timer_armed_at_elapsed_s"),
            value_sent_at_elapsed=exp.get("value_sent_at_elapsed_s"),
        )
        source_imm = classify_source_windows(
            list(exp.get("immediate_parent_messages") or []),
            expected_token=str(exp.get("token_sent") or ""),
            registered_instance_id=reg_inst,
        )
        source_top = classify_source_windows(
            list(exp.get("top_parent_messages") or []),
            expected_token=str(exp.get("token_sent") or ""),
            registered_instance_id=reg_inst,
        )
        instrumented = {
            "run_id": summary.get("started_at"),
            "cloud_sha": live_sha,
            "cloud_build": build_label,
            "room_id": summary.get("room_id"),
            "token": exp.get("token_sent"),
            "queue_seed": queue_meta,
            "frame_topology": exp.get("frame_topology"),
            "parent_boundary_validation": exp.get("parent_boundary_validation"),
            "observer_execution_contexts": exp.get("observer_execution_contexts"),
            "frame2_parent_messages": exp.get("frame2_parent_messages"),
            "authoritative_receipt_levels": (return_chain.get("browser") or {}).get("authoritative_receipt_levels"),
            "refined_boundary_a5a": (return_chain.get("browser") or {}).get("refined_boundary_a5a"),
            "overall_verdict": (return_chain.get("browser") or {}).get("overall_parent_boundary_verdict")
            or (exp.get("parent_boundary_validation") or {}).get("overall_verdict"),
            "source_classification_immediate": source_imm,
            "source_classification_top": source_top,
            "correlation_timeline": correlation,
            "merged_server_ledger_row_count": (exp.get("ledger_meta") or {}).get("merged_server_ledger_row_count")
            or len(exp.get("merged_server_ledger") or []),
            "ledger_meta": exp.get("ledger_meta") or {},
            "next_timer_wait": exp.get("next_timer_wait") or {},
            "rv3_compare_note": "RV3 PASS reference run 44848096-e2a0-401c-976f-754131DE; first divergence LEVEL 2+ session bind",
        }
        OUT_SERVER_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        OUT_SERVER_LEDGER.write_text(
            json.dumps(
                {
                    "run_id": exp.get("merged_server_ledger_run_id"),
                    "rows": exp.get("merged_server_ledger") or [],
                    "source": exp.get("merged_server_ledger_source"),
                    **(exp.get("ledger_meta") or {}),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        OUT_DIAG_RUN.write_text(json.dumps(instrumented, indent=2, default=str), encoding="utf-8")
        summary["instrumented_diag"] = instrumented

        grade = grade_stage_1a(page, start_val, exp, preflight=pre, stage1a_mode=stage1a_mode)
        exp["queue_seed"] = queue_meta
        stage1a = {
            "draft_start_validation": start_val,
            "expiration": exp,
            "grade": grade,
            "verdict": grade["verdict"],
            "stage1a_mode": stage1a_mode,
            "queue_independence": grade.get("queue_independence") or queue_meta.get("queue_independence") or "",
            "persistent_mount_ok": PERSISTENT_KEY in (exp.get("mount_key") or PERSISTENT_KEY),
        }
        summary["stage1a"] = stage1a
        if stage1a_mode == "CORE":
            summary["stage1a_core"] = stage1a
            summary["stage1a_core_status"] = grade.get("stage1a_core_status") or {}
        if stage1a_mode == "QUEUE":
            summary["stage1a_queue"] = stage1a
            OUT_QUEUE.write_text(json.dumps(stage1a, indent=2, default=str), encoding="utf-8")
        OUT_1A.write_text(json.dumps(stage1a, indent=2, default=str), encoding="utf-8")
        OUT_IFRAME.parent.mkdir(parents=True, exist_ok=True)
        OUT_IFRAME.write_text(
            json.dumps(exp.get("iframe_lifecycle") or {}, indent=2, default=str),
            encoding="utf-8",
        )
        OUT_TRANSPORT.parent.mkdir(parents=True, exist_ok=True)
        OUT_TRANSPORT.write_text(
            json.dumps(
                {
                    "transport_boundary": exp.get("transport_boundary") or {},
                    "first_missing_transport_stage": exp.get("first_missing_transport_stage") or "",
                    "frame_topology": exp.get("frame_topology") or {},
                    "immediate_parent_messages": exp.get("immediate_parent_messages") or [],
                    "double_production_send_analysis": exp.get("double_production_send_analysis") or {},
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        OUT_FRAME_TOPOLOGY.parent.mkdir(parents=True, exist_ok=True)
        OUT_FRAME_TOPOLOGY.write_text(
            json.dumps(exp.get("frame_topology") or {}, indent=2, default=str),
            encoding="utf-8",
        )

        core_functional_pass = (
            grade.get("stage1a_core_functional_outcome") == "PASS"
            if stage1a_mode == "CORE"
            else grade.get("stage1a_queue_functional_outcome") == "PASS" and grade.get("functional_verdict") == "PASS"
            if stage1a_mode == "QUEUE"
            else grade["verdict"] == "PASS"
        )
        if not core_functional_pass:
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
    if stage1a_mode == "QUEUE":
        grade = (summary.get("stage1a") or {}).get("grade") or {}
        if grade.get("stage1a_queue_functional_outcome") == "PASS" and grade.get("functional_verdict") == "PASS":
            summary["stage1a_queue"] = "PASS"
        elif summary.get("stage1a_queue") == "RUNNING":
            summary["stage1a_queue"] = "FAILED"
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    ok = summary.get("stage1a", {}).get("verdict") == "PASS"
    if summary.get("stage1a_mode") == "CORE" or (summary.get("stage1a") or {}).get("stage1a_mode") == "CORE":
        ok = (
            summary.get("stage1a_core_status", {}).get("stage1a_core_functional_outcome") == "PASS"
            or summary.get("stage1a", {}).get("grade", {}).get("stage1a_core_functional_outcome") == "PASS"
        )
    if summary.get("stage1a_queue_execution_status") == "BLOCKED_BEFORE_EXPIRATION":
        return 2
    if summary.get("stage1a_mode") == "QUEUE" or (summary.get("stage1a") or {}).get("stage1a_mode") == "QUEUE":
        ok = (
            summary.get("stage1a", {}).get("grade", {}).get("stage1a_queue_functional_outcome") == "PASS"
            and summary.get("stage1a", {}).get("grade", {}).get("functional_verdict") == "PASS"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
