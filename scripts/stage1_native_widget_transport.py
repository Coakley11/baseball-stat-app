"""Classify Streamlit websocket traffic: native widget vs generic component hints."""

from __future__ import annotations

import base64
from typing import Any

# Streamlit native st.button clicks often appear as component_value_hint frames without
# widget_key byte matches in the WS hook (see proven Pause/Start production captures).
# The in-page hook defaults to solo countdown ``widget_key``; Add-to-Queue must re-scan
# ``payload_base64`` for the authorized rec-card key and/or protobuf trigger=true.
_COMPONENT_USER_ACTION_MIN_BYTES = 800


def payload_contains_widget_key(entry: dict[str, Any], widget_key: str) -> bool:
    """True when ``widget_key`` appears in payload_base64 (or legacy text fields)."""
    key = str(widget_key or "").strip()
    if not key or not isinstance(entry, dict):
        return False
    b64 = str(entry.get("payload_base64") or "")
    if b64:
        try:
            if key.encode("utf-8") in base64.b64decode(b64):
                return True
        except Exception:
            pass
    for field in ("payload_text", "payload_preview", "decoded_text"):
        if key in str(entry.get(field) or ""):
            return True
    return False


def enrich_ws_samples_for_expected_key(
    samples: list[dict[str, Any]],
    *,
    expected_widget_key: str = "",
) -> list[dict[str, Any]]:
    """Recompute ``widget_key_bytes_present`` against the click's authorized key."""
    want = str(expected_widget_key or "").strip()
    out: list[dict[str, Any]] = []
    for entry in samples:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        if want:
            row["widget_key_bytes_present"] = payload_contains_widget_key(row, want)
            row["expected_widget_key"] = want
        out.append(row)
    return out


def classify_outbound_frame(entry: dict[str, Any]) -> dict[str, str]:
    hint = str(entry.get("frame_type_hint") or "").lower()
    wkey = bool(entry.get("widget_key_bytes_present"))
    byte_len = int(entry.get("byte_len") or 0)
    strict_native = hint == "widget_state_backmsg_hint" or wkey
    component_user_action = hint == "component_value_hint" and byte_len >= _COMPONENT_USER_ACTION_MIN_BYTES
    relaxed_native = strict_native or component_user_action
    component_only = hint == "component_value_hint" and not relaxed_native
    return {
        "frame_type_hint": hint or "unknown",
        "native_widget_event_hint_strict": str(strict_native).lower(),
        "native_widget_event_hint": str(relaxed_native).lower(),
        "component_value_only_hint": str(component_only).lower(),
        "component_user_action_hint": str(component_user_action).lower(),
    }


def classify_transport_from_ws_samples(
    samples: list[dict[str, Any]],
    *,
    pre_script_run_seq: str = "",
    post_script_run_seq: str = "",
    expected_widget_key: str = "",
) -> dict[str, Any]:
    """Pure classifier for retrospective gate analysis (no live page)."""
    prepared = enrich_ws_samples_for_expected_key(
        list(samples or []),
        expected_widget_key=expected_widget_key,
    )
    enriched: list[dict[str, Any]] = []
    native_strict = 0
    native_relaxed = 0
    component_only_count = 0
    for entry in prepared[:24]:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row.update(classify_outbound_frame(entry))
        if row.get("native_widget_event_hint_strict") == "true":
            native_strict += 1
        if row.get("native_widget_event_hint") == "true":
            native_relaxed += 1
        if row.get("component_value_only_hint") == "true":
            component_only_count += 1
        enriched.append(row)

    seq_changed = False
    if pre_script_run_seq and post_script_run_seq:
        try:
            seq_changed = int(post_script_run_seq) > int(pre_script_run_seq)
        except ValueError:
            seq_changed = post_script_run_seq != pre_script_run_seq

    outbound_n = len(prepared)
    native_widget_event_observed_strict = native_strict > 0
    native_widget_event_observed = native_relaxed > 0
    generic_component_traffic_only = (
        component_only_count > 0 and not native_widget_event_observed and outbound_n > 0
    )
    streamlit_outbound_after_click = outbound_n > 0
    want = str(expected_widget_key or "").strip()

    return {
        "outbound_frames_after_click": outbound_n,
        "native_widget_event_observed_strict": native_widget_event_observed_strict,
        "native_widget_event_observed": native_widget_event_observed,
        "native_widget_frame_count_strict": native_strict,
        "native_widget_frame_count": native_relaxed,
        "component_value_only_frame_count": component_only_count,
        "generic_component_traffic_only": generic_component_traffic_only,
        "streamlit_outbound_after_click": streamlit_outbound_after_click,
        "streamlit_backmsg_sent": streamlit_outbound_after_click or native_widget_event_observed,
        "python_rerun_started": bool(seq_changed),
        "script_run_seq_before": pre_script_run_seq,
        "ledger_script_run_seq_after": post_script_run_seq,
        "script_run_seq_changed": seq_changed,
        "expected_widget_key": want,
        "ws_log_sample": enriched[:8],
    }


def apply_strict_backmsg_authority(
    transport: dict[str, Any],
    *,
    raw_log: list[dict[str, Any]] | None = None,
    click_ts: float = 0.0,
    expected_widget_key: str = "",
) -> dict[str, Any]:
    """Upgrade heuristic strict flags from protobuf ``trigger_value=true`` evidence.

    Pause and Add-to-Queue both land as ``component_value_hint`` without ASCII ``widget``;
    the WS hook also defaults to the solo countdown key. Protobuf decode is authoritative.
    """
    out = dict(transport or {})
    want = str(expected_widget_key or out.get("expected_widget_key") or "").strip()
    try:
        from stage1_strict_backmsg_decode import summarize_strict_backmsg_evidence
    except ImportError:
        return out

    samples = list(out.get("ws_log_sample") or [])
    log = list(raw_log) if isinstance(raw_log, list) else [
        {**dict(e), "direction": e.get("direction") or "outbound"} for e in samples if isinstance(e, dict)
    ]
    # Ensure direction for samples used as raw_log fallback.
    normalized: list[dict[str, Any]] = []
    for e in log:
        if not isinstance(e, dict):
            continue
        row = dict(e)
        row.setdefault("direction", "outbound")
        normalized.append(row)

    strict = summarize_strict_backmsg_evidence(
        normalized,
        click_ts=float(click_ts or out.get("click_ts") or 0.0),
        relaxed_ws_sample=samples,
        expected_widget_id=want,
    )
    out["strict_backmsg"] = strict
    if strict.get("target_trigger_backmsg_seen") or (
        want and strict.get("activated_widget_state_present") and any(
            want in str(i) for i in (strict.get("activated_widget_ids") or [])
        )
    ):
        out["native_widget_event_observed_strict"] = True
        out["native_widget_event_observed"] = True
        out["protobuf_target_trigger_observed"] = True
    elif strict.get("activated_widget_state_present") and not want:
        # Any activated trigger counts as strict native when no specific key was requested.
        out["native_widget_event_observed_strict"] = True
        out["native_widget_event_observed"] = True
        out["protobuf_target_trigger_observed"] = True
    if strict.get("rerun_script_backmsg_seen"):
        out["streamlit_backmsg_sent"] = True
    return out


def wait_for_post_click_app_diag_advance(
    page,
    *,
    pre_script_run_seq: str | int | None,
    frame_url_hint: str = "",
    timeout_s: float = 5.0,
    poll_s: float = 0.15,
) -> dict[str, Any]:
    """Wait briefly for ``#solo-stage1-current-run-diag`` seq to exceed pre-click seq.

    Production 392ba87/131d99b2: Lindor post-click scrape at +0.21s still saw seq 21 while
    a ``full_run`` seq-22 probe was stamped ~40ms later — causing false
    ``script_run_seq_changed=false`` despite an actual consuming ScriptRun.
    """
    import time as _time

    from stage1_run_binding import capture_run_binding_snapshot

    try:
        pre_i = int(pre_script_run_seq) if pre_script_run_seq not in (None, "") else None
    except (TypeError, ValueError):
        pre_i = None

    deadline = _time.time() + max(0.5, float(timeout_s))
    last: dict[str, Any] = {}
    polls = 0
    while _time.time() < deadline:
        polls += 1
        last = capture_run_binding_snapshot(page, frame_url_hint=frame_url_hint, phase="post_click")
        cur = last.get("current_app_diag_seq")
        try:
            cur_i = int(cur) if cur is not None else None
        except (TypeError, ValueError):
            cur_i = None
        if pre_i is not None and cur_i is not None and cur_i > pre_i:
            return {
                "advanced": True,
                "polls": polls,
                "pre_seq": pre_i,
                "post_seq": cur_i,
                "binding": last,
                "waited_s": round(float(timeout_s) - max(0.0, deadline - _time.time()), 3),
            }
        # Also accept any candidate full_run probe with higher seq (stale DOM siblings).
        for cand in last.get("current_app_diag_candidates") or []:
            if not isinstance(cand, dict):
                continue
            try:
                cseq = int(cand.get("script_run_seq"))
            except (TypeError, ValueError):
                continue
            if pre_i is not None and cseq > pre_i and str(cand.get("fragment_run_hint") or "") == "full_run":
                # Re-select by recapturing — selection prefers highest seq.
                last = capture_run_binding_snapshot(page, frame_url_hint=frame_url_hint, phase="post_click")
                cur2 = last.get("current_app_diag_seq")
                try:
                    if cur2 is not None and int(cur2) > pre_i:
                        return {
                            "advanced": True,
                            "polls": polls,
                            "pre_seq": pre_i,
                            "post_seq": int(cur2),
                            "binding": last,
                            "via": "candidate_full_run",
                            "waited_s": round(float(timeout_s) - max(0.0, deadline - _time.time()), 3),
                        }
                except (TypeError, ValueError):
                    pass
        _time.sleep(max(0.05, float(poll_s)))
    return {
        "advanced": False,
        "polls": polls,
        "pre_seq": pre_i,
        "post_seq": last.get("current_app_diag_seq") if last else None,
        "binding": last,
        "waited_s": float(timeout_s),
        "timeout": True,
    }


def scrape_native_widget_transport_evidence(
    page,
    *,
    click_ts: float,
    pre_script_run_seq: str = "",
    pre_run_binding: dict[str, Any] | None = None,
    frame_url_hint: str = "",
    expected_widget_key: str = "",
    wait_for_seq_advance_s: float = 5.0,
) -> dict[str, Any]:
    """Distinguish native st.button widget traffic from solo timer/component SCV."""
    try:
        from p8_proven_start_delivery import aggregate_ws_boundary_log
    except ImportError:
        return {"error": "aggregate_ws_boundary_log_unavailable"}

    raw_log = aggregate_ws_boundary_log(page)
    outbound = [e for e in raw_log if isinstance(e, dict) and e.get("direction") == "outbound"]
    after = [e for e in outbound if float(e.get("wall_ts_ms") or 0) >= (click_ts * 1000.0 - 50.0)]

    pre_binding = dict(pre_run_binding) if isinstance(pre_run_binding, dict) else {}
    pre_grade = pre_binding.get("current_app_diag_seq")
    if pre_grade is None:
        pre_grade = pre_binding.get("ledger_transport_grade_script_run_seq")
    if pre_grade is None and pre_script_run_seq:
        pre_grade = pre_script_run_seq

    wait_meta: dict[str, Any] = {}
    try:
        from stage1_run_binding import capture_run_binding_snapshot, merge_run_binding_into_transport

        wait_meta = wait_for_post_click_app_diag_advance(
            page,
            pre_script_run_seq=pre_grade,
            frame_url_hint=frame_url_hint,
            timeout_s=float(wait_for_seq_advance_s),
        )
        post_binding = dict(wait_meta.get("binding") or {})
        if not post_binding:
            post_binding = capture_run_binding_snapshot(page, frame_url_hint=frame_url_hint, phase="post_click")
    except ImportError:
        post_binding = {}
        merge_run_binding_into_transport = None  # type: ignore[assignment,misc]

    post_grade = post_binding.get("current_app_diag_seq")
    if post_grade is None:
        post_grade = post_binding.get("ledger_transport_grade_script_run_seq")
    want = str(expected_widget_key or "").strip()

    out = classify_transport_from_ws_samples(
        after,
        pre_script_run_seq=str(pre_grade) if pre_grade is not None else "",
        post_script_run_seq=str(post_grade) if post_grade is not None else "",
        expected_widget_key=want,
    )
    out["click_ts"] = click_ts
    out["legacy_pre_script_run_seq_arg"] = pre_script_run_seq
    out["post_click_seq_wait"] = {
        k: wait_meta.get(k)
        for k in ("advanced", "polls", "pre_seq", "post_seq", "waited_s", "timeout", "via")
        if k in wait_meta
    }
    out = apply_strict_backmsg_authority(
        out,
        raw_log=raw_log,
        click_ts=click_ts,
        expected_widget_key=want,
    )
    if merge_run_binding_into_transport and pre_binding:
        combined_pre = {**pre_binding, "phase": "pre_click"}
        out["run_binding_pre"] = combined_pre
        out["run_binding_post"] = {**post_binding, "phase": "post_click"} if post_binding else {}
        # Grade seq change from post snapshot (not pre-only merge).
        out = merge_run_binding_into_transport(out, combined_pre)
        if post_grade is not None:
            out["ledger_script_run_seq_after"] = str(post_grade)
            if out.get("run_binding_consistent") is not False:
                try:
                    out["script_run_seq_changed"] = int(post_grade) > int(pre_grade or 0)
                except (TypeError, ValueError):
                    out["script_run_seq_changed"] = str(post_grade) != str(pre_grade or "")
                out["python_rerun_started"] = bool(out.get("script_run_seq_changed"))
                out["python_rerun_observability_blocked"] = False
            else:
                out["python_rerun_started"] = False
                out["python_rerun_observability_blocked"] = True
        # Prefer post binding as authoritative run_binding when phase is post_click.
        if post_binding:
            out["run_binding"] = dict(out.get("run_binding_post") or post_binding)

    # Attach same-run consumption ledger scrape correlated to post seq / widget key.
    try:
        from stage1_rec_run_stage_scrape import scrape_rec_run_stage_for_consuming_run

        consume_seq = post_grade if post_grade is not None else None
        out["consuming_run_stage_ledger"] = scrape_rec_run_stage_for_consuming_run(
            page,
            run_seq=consume_seq,
            room_id=str(
                (post_binding or {}).get("lifecycle_room_id")
                or (pre_binding or {}).get("lifecycle_room_id")
                or ""
            ),
            widget_key=want,
        )
    except ImportError:
        out["consuming_run_stage_ledger"] = {"ok": False, "fail_reason": "scrape_module_missing"}
    except Exception as exc:
        out["consuming_run_stage_ledger"] = {"ok": False, "fail_reason": f"scrape_error:{type(exc).__name__}", "error": str(exc)[:160]}
    return out


QUEUE1C3A2L = "QUEUE1C3A2L"
QUEUE1C3A2O1 = "QUEUE1C3A2O1"
QUEUE1C3A2O2 = "QUEUE1C3A2O2"


def classify_queue1c3a_subcode(
    *,
    click_target: dict[str, Any] | None,
    transport: dict[str, Any] | None,
    render_trace_present: bool,
    callback_trace_present: bool,
    callback_entered: bool | None,
    widget_liveness: str = "",
) -> str:
    """Refine QUEUE1C3A using DOM target + transport + render/callback probes."""
    if not render_trace_present:
        return "QUEUE1C3A5"
    live = str(widget_liveness or "").strip().lower()
    if live == "stale_retained_dom":
        return QUEUE1C3A2L
    tgt = click_target if isinstance(click_target, dict) else {}
    tr = transport if isinstance(transport, dict) else {}
    if tr.get("run_binding_consistent") is False:
        return QUEUE1C3A2O1
    if tr.get("dom_capture_observability_failed"):
        return QUEUE1C3A2O2
    if tgt.get("click_non_native_element"):
        return "QUEUE1C3A1"
    if tgt.get("inside_st_tooltip") and not tgt.get("is_st_base_button"):
        return "QUEUE1C3A1"
    # Authoritative QUEUE1C3A2 uses strict native detection (byte/widget hints), not relaxed SCV.
    strict_native = tr.get("native_widget_event_observed_strict")
    if strict_native is None:
        strict_native = tr.get("native_widget_event_observed")
    if not strict_native and tr.get("generic_component_traffic_only"):
        return "QUEUE1C3A2"
    if (
        not strict_native
        and not tr.get("script_run_seq_changed")
        and tr.get("streamlit_outbound_after_click")
        and tr.get("run_binding_consistent") is not False
    ):
        return "QUEUE1C3A2"
    if tr.get("native_widget_event_observed") and not tr.get("script_run_seq_changed"):
        if tr.get("run_binding_consistent") is False:
            return QUEUE1C3A2O1
        return "QUEUE1C3A3"
    if tr.get("script_run_seq_changed") and callback_entered is False:
        return "QUEUE1C3A4"
    if callback_trace_present and not callback_entered:
        return "QUEUE1C3A4"
    return "QUEUE1C3A"
