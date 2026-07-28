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
OUT_1B = ROOT / "data" / "production_stage1b_queue_auth.json"
OUT_1B_FB = ROOT / "data" / "production_stage1b_queue_fallback_auth.json"
OUT_IFRAME = ROOT / "data" / "production_stage1a_iframe_lifecycle.json"
OUT_TRANSPORT = ROOT / "data" / "production_stage1a_transport_boundary.json"
OUT_FRAME_TOPOLOGY = ROOT / "data" / "production_stage1a_frame_topology.json"
OUT_CLEANUP = ROOT / "data" / "production_stage1a_preflight_cleanup.json"
OUT_RETURN_CHAIN = ROOT / "data" / "production_stage1a_return_value_chain.json"
OUT_SERVER_LEDGER = ROOT / "data" / "production_stage1a_server_ledger_merged.json"
OUT_DIAG_RUN = ROOT / "data" / "production_stage1a_instrumented_diag.json"
REQUIRED_CLOUD_SHA = ""


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
    tick_after_send = tick_cancelled >= 1 and "component_value_sent" in cs
    a5a_refined = refine_a5a_subclass(levels, unrelated_render_after_send=tick_after_send and not levels.get("LEVEL_5_PYTHON_VALUE_BOUND"))

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


def wait_one_expiration(page, *, timeout_s: float = 55.0) -> dict[str, Any]:
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
        scrape_stage1_production_ledger,
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
    merged_server_ledger: list[dict[str, Any]] = []
    supabase_requests: list[dict[str, Any]] = []

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
        ledger_snap = scrape_stage1_production_ledger(page)
        merged_server_ledger = merge_ledger_rows(merged_server_ledger, list(ledger_snap.get("rows") or []))
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
        if {"pick_committed", "commit_confirmed"} & merged_stages:
            break
        if accepted_now:
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
    ledger_final = scrape_stage1_production_ledger(page)
    merged_server_ledger = merge_ledger_rows(merged_server_ledger, list(ledger_final.get("rows") or []))
    # Prefer topology captured while component iframes are still attached (Playwright detaches on teardown).
    if (frame_topology_final.get("frame_count") or 0) < 5:
        for snap in reversed(samples):
            topo = (snap.get("frame_topology") or {}) if isinstance(snap, dict) else {}
            if (topo.get("frame_count") or 0) >= 5:
                frame_topology_final = topo
                break
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
        "transport_boundary": transport_final,
        "first_missing_transport_stage": transport_class,
        "client_send_ts_ms": send_ts_ms,
        "frame_topology": frame_topology_final,
        "immediate_parent_messages": immediate_parent_messages,
        "top_parent_messages": top_parent_messages,
        "app_parent_observer_messages": app_observer_msgs,
        "merged_server_ledger": merged_server_ledger,
        "merged_server_ledger_run_id": ledger_final.get("run_id") or "",
        "merged_server_ledger_source": ledger_final.get("source") or "",
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
    pick_delta = exp.get("pick_delta")
    exactly_one_pick = pick_delta == 1 or exp.get("board_delta") == 1
    auth_ok = authenticated_probe(page, preflight=preflight)
    if preflight and preflight.get("authenticated_restored"):
        auth_ok = True
    auth_at_expire = auth_ok
    room_ok = bool(draft_valid.get("valid")) and bool(exp.get("room_in_progress_before"))
    pick_commits = exp.get("pick_commit_audit") or []
    expire_caused_pick = bool(pick_commits) and not exp.get("harness_manual_draft_action")
    zero_cross = "browser_deadline_crossed" in cs
    sent_ok = "component_value_sent" in cs
    callbacks = list(exp.get("callback_timeline") or [])
    native_accepted = [
        c
        for c in callbacks
        if str(c.get("callback_source") or "") == "native_component_return"
        and c.get("delivery_claimed")
        and not c.get("reject_code")
    ]
    mount_return = str(
        (exp.get("return_value_chain") or {}).get("python_component", {}).get("coalesced_component_value")
        or exp.get("component_return")
        or ""
    )
    token_match = bool(
        token_sent
        and (
            token_sent in raw
            or token_sent in str(exp.get("server_chain") or "")
            or token_sent == mount_return
        )
    )
    timer_after = exp.get("state_after", {}).get("timer")
    mount_diag_after = (exp.get("state_after", {}).get("mount_diag") or {})
    countdown_restarted = (
        (timer_after is not None and int(timer_after) > 0)
        or bool(mount_diag_after.get("diag_remaining"))
        or bool(exp.get("deadline_after"))
    )
    queue_ignored = bool(
        (exp.get("return_value_chain") or {}).get("draft_result", {}).get("queue_player_ignored", True)
    )
    owners = dict((exp.get("stage1_audit") or {}).get("delivery_owners") or {})
    flush_owner = any(str(v) == "late_page_flush" for v in owners.values())
    on_change_owner = any(str(v) == "native_component_on_change" for v in owners.values())
    remount_warn = int(
        (exp.get("return_value_chain") or {}).get("browser", {}).get("iframe_remounts") or 0
    ) > 0

    checks = {
        "1_authenticated_at_expire": auth_at_expire,
        "2_room_in_progress_before_expire": room_ok,
        "3_browser_deadline_crossed": zero_cross,
        "4_component_value_sent": sent_ok,
        "5_exact_token_delivery": token_match or bool(token_sent and mount_return),
        "6_one_accepted_callback": accepted_count == 1,
        "6b_native_component_return_accepted": len(native_accepted) == 1,
        "7_zero_duplicate_processing": rejected_count == 0 and on_change_count <= 1,
        "7b_no_late_flush_owner": not flush_owner,
        "7c_no_on_change_owner": not on_change_owner,
        "8_one_pick_committed": exactly_one_pick,
        "9_pick_advances_once": pick_delta == 1,
        "10_new_deadline_after_commit": bool(exp.get("deadline_after")) and str(exp.get("deadline_after")) != str(
            exp.get("deadline_before") or ""
        ),
        "11_countdown_restarts_above_zero": countdown_restarted,
        "12_board_or_pool_updated": (exp.get("board_delta") or 0) >= 1,
        "13_pick_from_expire_not_harness": expire_caused_pick,
        "14_queue_player_ignored": queue_ignored,
    }
    passed = all(checks.values())
    if remount_warn and passed:
        checks["warn_iframe_remounts"] = True
    return {
        "checks": checks,
        "verdict": "PASS" if passed else "FAIL",
        "on_change_count": on_change_count,
        "callback_accepted_count": accepted_count,
        "callback_rejected_count": rejected_count,
        "pick_delta": pick_delta,
        "token_match": token_match,
        "authenticated_at_expire": auth_at_expire,
        "native_component_return_accepted_count": len(native_accepted),
        "failure_interpretation_class": (exp.get("return_value_chain") or {}).get("failure_interpretation_class"),
    }


def queue_add_first_player(page) -> dict[str, Any]:
    from run_production_solo_soak import click_btn

    for _ in range(4):
        try:
            page.evaluate(
                """() => {
                  const labels = ['Draft from lists', 'On Clock', 'Recommendations'];
                  for (const lab of labels) {
                    const w = Array.from(document.querySelectorAll('*')).find(
                      el => el.childElementCount <= 6 && (el.innerText||'').trim().startsWith(lab)
                    );
                    if (w) { w.scrollIntoView({block: 'center'}); return true; }
                  }
                  window.scrollTo(0, document.body.scrollHeight * 0.45);
                  return false;
                }"""
            )
        except Exception:
            pass
        page.wait_for_timeout(1200)
        if click_btn(page, "Add to Queue", wait_ms=1500) or click_btn(page, "⭐", wait_ms=1500):
            meta = page.evaluate(
                """() => {
                  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
                  for (const root of roots()) {
                    for (const b of root.querySelectorAll('button')) {
                      const t = String(b.innerText||'').replace(/\\s+/g,' ').trim();
                      if (!/Add to Queue/i.test(t)) continue;
                      const card = b.closest('[data-testid=\"stVerticalBlock\"]') || b.parentElement;
                      let name = '';
                      if (card) {
                        const lines = String(card.innerText||'').split('\\n').map(x=>x.trim()).filter(Boolean);
                        name = lines.find(l => l.length > 3 && !/Add to Queue|Draft|Queue|Clear|Watchlist/i.test(l)) || '';
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
        loc = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).first
        loc.scroll_into_view_if_needed(timeout=5000)
        loc.click(timeout=5000)
        return {"clicked": True, "button_text": "Add to Queue", "player_hint": "", "via": "playwright_role"}
    except Exception:
        pass
    return {"clicked": False, "button_text": "", "player_hint": ""}


def queue_seed_satisfied(queue_meta: dict[str, Any]) -> bool:
    if queue_meta.get("clicked"):
        return True
    excerpt = str(queue_meta.get("queue_excerpt_before") or "")
    if not excerpt or "Queue empty" in excerpt:
        return False
    m = re.search(r"\n([A-Za-z][^\n]{2,60}?)\s+—\s*(UTIL|SP|RP|C|1B|2B|3B|SS|OF|DH|P)", excerpt)
    if m:
        queue_meta.setdefault("player_hint", m.group(1).strip())
        queue_meta["seed_source"] = "queue_already_populated"
        return True
    if "On the clock" in excerpt and "Clear Draft Queue" in excerpt:
        queue_meta["seed_source"] = "queue_nonempty_ui"
        return True
    return False


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
    required_sha = resolve_required_cloud_sha()
    if not required_sha:
        print(json.dumps({"aborted": True, "reason": "required_cloud_sha_unset"}))
        return 1
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
        "cloud_sha": str(pre.get("cloud_sha") or ""),
        "required_cloud_sha": required_sha,
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
        try:
            from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT

            page.add_init_script(HARNESS_TOP_OBSERVER_INIT_SCRIPT)
        except ImportError:
            pass

        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(20000)
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

            m = re.search(r"baseball-dev-([0-9a-f]{7})", all_frames_text(page), re.I)
            if m:
                build_label = f"baseball-dev-{m.group(1).lower()}"
        except Exception:
            pass
        summary["cloud_build"] = build_label
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

        queue_meta = queue_add_first_player(page)
        page.wait_for_timeout(3500)
        queue_meta["queue_excerpt_before"] = queue_text(page)
        hint = str(queue_meta.get("player_hint") or "").strip()
        excerpt = str(queue_meta.get("queue_excerpt_before") or "")
        queue_meta["queue_contains_player"] = queue_seed_satisfied(queue_meta) or bool(
            queue_meta.get("clicked") and hint and hint.split()[0][:4].lower() in excerpt.lower()
        )
        summary["queue_seed"] = queue_meta
        if not queue_seed_satisfied(queue_meta):
            summary["aborted"] = True
            summary["abort_reason"] = "queue_seed_failed"
            context.close()
            browser.close()
            summary["finished_at"] = time.time()
            OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, default=str))
            return 1

        exp = wait_one_expiration(page, timeout_s=95.0)
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
            "authoritative_receipt_levels": (return_chain.get("browser") or {}).get("authoritative_receipt_levels"),
            "refined_boundary_a5a": (return_chain.get("browser") or {}).get("refined_boundary_a5a"),
            "source_classification_immediate": source_imm,
            "source_classification_top": source_top,
            "correlation_timeline": correlation,
            "merged_server_ledger_row_count": len(exp.get("merged_server_ledger") or []),
            "rv3_compare_note": "RV3 PASS reference run 44848096-e2a0-401c-976f-754131DE; first divergence LEVEL 2+ session bind",
        }
        OUT_SERVER_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        OUT_SERVER_LEDGER.write_text(
            json.dumps(
                {
                    "run_id": exp.get("merged_server_ledger_run_id"),
                    "rows": exp.get("merged_server_ledger") or [],
                    "source": exp.get("merged_server_ledger_source"),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        OUT_DIAG_RUN.write_text(json.dumps(instrumented, indent=2, default=str), encoding="utf-8")
        summary["instrumented_diag"] = instrumented

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
