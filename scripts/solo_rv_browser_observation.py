"""Runner-only RV1 browser event observation (identity filtering, no production changes)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any


DEFAULT_WIDGET_KEY = "solo_countdown_wake_solo_persistent"


def new_instrumentation_epoch_id(*, step: str = "RV1") -> str:
    tag = step.lower().replace(" ", "")
    return f"{tag}-epoch-{uuid.uuid4().hex[:12]}"


def install_rv_browser_capture_before_navigation(
    context: Any,
    *,
    run_id: str,
    instrumentation_epoch_id: str,
    control_name: str = "RV1",
) -> None:
    """Init script must run before first navigation to the RV control URL."""
    payload = json.dumps(
        {
            "runId": run_id,
            "epochId": instrumentation_epoch_id,
            "controlName": control_name,
        }
    )
    context.add_init_script(
        f"""() => {{
          const p = {payload};
          window.__solo_rv_instrumentation_run_id = p.runId;
          window.__solo_rv_instrumentation_epoch_id = p.epochId;
          window.__solo_rv_control_name = p.controlName;
          if (!window.__solo_immediate_parent_msgs) {{
            window.__solo_immediate_parent_msgs = [];
          }}
        }}"""
    )


def attach_rv_page_listeners(page: Any, *, expected_token: str = "") -> None:
    from stage1_frame_transport_probe import install_immediate_parent_listeners

    install_immediate_parent_listeners(page, expected_production_token=expected_token)


def build_run_identity_from_ledger(
    rows: list[dict[str, Any]], *, run_id: str, control_name: str = "RV1"
) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "solo_rv_run_id": run_id,
        "room_id": "",
        "pick_index": None,
        "deadline": None,
        "expected_token": "",
        "widget_key": DEFAULT_WIDGET_KEY,
        "control_name": control_name,
    }
    for event in (
        "real_room_hydrated",
        "production_draft_started",
        "production_setup_owner_established",
        "declaration_attempt",
        "declaration_returned",
    ):
        for row in rows:
            if str(row.get("event") or "") != event:
                continue
            if str(row.get("run_id") or "") not in ("", run_id):
                continue
            tok = str(row.get("expected_token") or "").strip()
            if control_name == "RV3" and tok:
                try:
                    from live_draft_solo_rv3_phase import is_rv3_rejected_token

                    if is_rv3_rejected_token(tok):
                        continue
                except ImportError:
                    pass
            identity["room_id"] = str(row.get("room_id") or identity["room_id"] or "").strip().upper()
            if row.get("pick_index") is not None:
                identity["pick_index"] = row.get("pick_index")
            if row.get("deadline") is not None:
                identity["deadline"] = row.get("deadline")
            if tok:
                identity["expected_token"] = tok
            wk = str(row.get("widget_key") or "").strip()
            if wk:
                identity["widget_key"] = wk
    return identity


def _token_matches_row(token: str, row: dict[str, Any]) -> bool:
    if not token:
        return True
    preview = str(row.get("token_preview") or "").strip()
    extra = str(row.get("extra_preview") or "")
    if preview and (token == preview or token.startswith(preview) or preview in token):
        return True
    if token in extra:
        return True
    parts = token.split("|")
    if parts and parts[0] and parts[0] in extra:
        return True
    return False


def _iframe_id_from_row(row: dict[str, Any], fallback: str = "") -> str:
    extra = str(row.get("extra_preview") or "")
    m = re.search(r"(solo_[0-9]+_[a-z0-9]+)", extra)
    if m:
        return m.group(1)
    iid = str(row.get("instance_id") or row.get("iframe_instance_id") or "").strip()
    return iid or fallback


def _timeline_row_matches_identity(row: dict[str, Any], identity: dict[str, Any]) -> bool:
    stage = str(row.get("stage") or "")
    widget = str(identity.get("widget_key") or DEFAULT_WIDGET_KEY)
    token = str(identity.get("expected_token") or "")
    room_id = str(identity.get("room_id") or "")
    preview = str(row.get("token_preview") or "").strip()
    if preview and any(x in preview.upper() for x in ("PARITY", "MINIMAL", "WIRING")):
        return False
    row_widget = str(row.get("widget_key") or "")
    if row_widget and widget and row_widget != widget:
        return False
    if stage in ("timer_armed", "transport_before_postMessage", "component_value_sent", "transport_postmessage_invoked"):
        if token and not _token_matches_row(token, row):
            return False
    if room_id:
        extra = str(row.get("extra_preview") or "")
        preview = str(row.get("token_preview") or "")
        if room_id not in extra and room_id not in preview and token and room_id not in token:
            if stage in ("timer_armed", "component_value_sent", "transport_before_postMessage"):
                return False
    return True


def filter_observations_by_run_identity(
    expiration: dict[str, Any],
    registry: dict[str, Any],
    identity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Identity-based grading — do not drop valid timer_arm rows by wall-clock epoch."""
    exp = dict(expiration or {})
    reg = dict(registry or {})
    token = str(identity.get("expected_token") or "")
    run_id = str(identity.get("solo_rv_run_id") or "")

    double = dict(exp.get("double_production_send_analysis") or {})
    timeline = [t for t in list(double.get("timeline") or []) if _timeline_row_matches_identity(t, identity)]
    double["timeline"] = timeline
    timer_ts = [float(t.get("ts") or 0) for t in timeline if str(t.get("stage") or "") == "timer_armed"]
    double["timer_armed_timestamps"] = timer_ts
    double["production_timer_armed_count"] = len(timer_ts)
    exp["double_production_send_analysis"] = double

    stages: set[str] = set()
    for row in timeline:
        stages.add(str(row.get("stage") or ""))
    if token and {"component_value_sent", "transport_before_postMessage"} & stages:
        stages.add("browser_deadline_crossed")
    exp["client_stages"] = sorted(stages)
    if token and ("component_value_sent" in stages or "transport_before_postMessage" in stages):
        exp["token_sent"] = token

    last = [e for e in list(reg.get("last") or []) if isinstance(e, dict)]
    logical = [e for e in list(reg.get("logical") or []) if isinstance(e, dict)]

    def _reg_matches(entry: dict[str, Any]) -> bool:
        et = str(entry.get("token") or entry.get("token_preview") or "")
        if token and et and token != et and not (token.startswith(et) or et in token):
            return False
        rid = str(entry.get("run_id") or "")
        if run_id and rid and rid != run_id:
            return False
        return True

    reg["last"] = [e for e in last if _reg_matches(e)]
    reg["logical"] = [e for e in logical if _reg_matches(e)]
    if run_id:
        reg["run_id"] = run_id
    exp["rv_run_identity"] = dict(identity)
    return exp, reg


def analyze_timer_arms_identity(
    expiration: dict[str, Any],
    registry: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, Any]:
    double = dict(expiration.get("double_production_send_analysis") or {})
    timeline = list(double.get("timeline") or [])
    token = str(identity.get("expected_token") or expiration.get("token_sent") or "")
    deadline = identity.get("deadline")
    widget = str(identity.get("widget_key") or DEFAULT_WIDGET_KEY)
    instance_id = str(registry.get("current") or "")
    if not instance_id:
        inst = registry.get("instances") or {}
        if isinstance(inst, dict) and inst:
            instance_id = str(next(iter(inst.values()), {}).get("instance_id") or "")

    raw_timer_rows = [r for r in timeline if str(r.get("stage") or "") == "timer_armed"]
    raw_count = len(raw_timer_rows)
    fingerprints: set[tuple[str, str, str, str]] = set()
    for row in raw_timer_rows:
        iid = _iframe_id_from_row(row, instance_id)
        dl = str(deadline if deadline is not None else "")
        if not dl and token and "|" in token:
            parts = token.split("|")
            if len(parts) >= 3:
                dl = parts[-1]
        fingerprints.add((iid, token, dl, widget))

    logical_count = len(fingerprints) if fingerprints else (1 if raw_count else 0)
    dup = raw_count > logical_count and logical_count >= 1
    return {
        "raw_timer_arms": raw_count,
        "logical_timer_arms": logical_count,
        "instrumentation_duplicate": dup,
        "fingerprints": [list(f) for f in fingerprints],
        "identity": dict(identity),
    }


def summarize_rv_control_browser(
    expiration: dict[str, Any], registry: dict[str, Any], identity: dict[str, Any]
) -> dict[str, Any]:
    from live_draft_solo_rv_binding_ladder import browser_send_proven, extract_transport_send_evidence, summarize_browser_events

    exp, reg = filter_observations_by_run_identity(expiration, registry, identity)
    browser = summarize_browser_events(exp, reg)
    browser["timer_arm_accounting"] = analyze_timer_arms_identity(exp, reg, identity)
    browser["rv_run_identity"] = dict(identity)
    browser["browser_send_proven"] = browser_send_proven(exp)
    browser["transport_send_evidence"] = extract_transport_send_evidence(exp)
    browser["_filtered_expiration"] = exp
    browser["_filtered_registry"] = reg
    return browser


def summarize_rv1_browser(expiration: dict[str, Any], registry: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    return summarize_rv_control_browser(expiration, registry, identity)


def validate_rv_browser_delivery(
    *,
    browser: dict[str, Any],
    expiration: dict[str, Any],
    control_probe_rows: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Browser delivery lane — expiration send chain; timer_arm row not required."""
    events = {str(r.get("event") or "") for r in control_probe_rows}
    logical = int(browser.get("logical_send_count") or 0)
    if logical != 1:
        return False, f"INVALID_BROWSER_SEND_COUNT_{logical}_need_1"
    sends = int(browser.get("unique_send_events") or 0)
    if sends != 1:
        return False, f"INVALID_BROWSER_UNIQUE_SEND_{sends}_need_1"
    cs = set(expiration.get("client_stages") or [])
    if "browser_deadline_crossed" not in cs and "component_value_sent" not in cs:
        if not browser.get("browser_send_proven"):
            return False, "INVALID_BROWSER_DEADLINE_CROSS_MISSING"
    if not browser.get("browser_send_proven") and not browser.get("parent_listener_on_app_window"):
        return False, "INVALID_BROWSER_LISTENER_NOT_OBSERVED"
    if not browser.get("sending_iframe_identified"):
        return False, "INVALID_BROWSER_IFRAME_NOT_IDENTIFIED"
    if browser.get("sender_current_status") == "disconnected":
        return False, "INVALID_BROWSER_IFRAME_DISCONNECTED"
    if browser.get("browser_send_proven") or "component_value_sent" in cs or logical == 1:
        if "post_delivery_redeclaration" not in events:
            return False, "INVALID_POST_DELIVERY_REDECLARATION_MISSING"
    return True, "PASS"


def lifecycle_instrumentation_report(browser: dict[str, Any], *, browser_delivery_ok: bool) -> tuple[str, list[str]]:
    warnings: list[str] = []
    timer = dict(browser.get("timer_arm_accounting") or {})
    logical_arms = int(timer.get("logical_timer_arms") or 0)
    raw_arms = int(timer.get("raw_timer_arms") or 0)
    if browser_delivery_ok and logical_arms != 1:
        if raw_arms == 0:
            warnings.append("WARN_TIMER_ARM_EVENT_NOT_OBSERVED")
        elif timer.get("instrumentation_duplicate"):
            warnings.append("WARN_TIMER_ARM_INSTRUMENTATION_DUPLICATE")
        else:
            warnings.append("WARN_TIMER_ARM_EVENT_NOT_OBSERVED")
    lane = "PASS" if not warnings else warnings[0]
    return lane, warnings


def validate_rv_browser_validity(
    *,
    browser: dict[str, Any],
    expiration: dict[str, Any],
    control_probe_rows: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Legacy combined check (timer arm required). Prefer validate_rv_browser_delivery + lifecycle_instrumentation_report."""
    delivery_ok, delivery_reason = validate_rv_browser_delivery(
        browser=browser,
        expiration=expiration,
        control_probe_rows=control_probe_rows,
    )
    if not delivery_ok:
        return False, delivery_reason
    timer = dict(browser.get("timer_arm_accounting") or {})
    if int(timer.get("logical_timer_arms") or 0) != 1:
        return False, "INVALID_TIMER_ARM_NOT_OBSERVED"
    return True, "PASS"


def grade_rv_python_binding(ledger_rows: list[dict[str, Any]], *, expected_token: str) -> tuple[str, str]:
    if not expected_token:
        return "INVALID", "INVALID_PYTHON_BINDING_missing_expected_token"
    from live_draft_solo_rv3_phase import is_rv3_rejected_token

    for row in reversed(ledger_rows):
        ev = str(row.get("event") or "")
        if ev not in ("declaration_returned", "post_delivery_redeclaration"):
            continue
        tok = str(row.get("expected_token") or "")
        if is_rv3_rejected_token(tok):
            continue
        if expected_token and tok and tok != expected_token and expected_token not in tok:
            continue
        coalesced = str(row.get("coalesced_value") or "").strip().strip("'\"")
        if not coalesced:
            cr = str(row.get("component_return") or "").strip().strip("'\"")
            if cr and cr != "None":
                coalesced = cr
        ss_after = str(row.get("session_state_after") or "")
        if expected_token in ss_after:
            return "PASS_RETURN_VALUE_DELIVERY", "rv1_python_coalesced_or_session_state"
        if coalesced == expected_token:
            return "PASS_RETURN_VALUE_DELIVERY", "rv1_python_coalesced_value"
    return "FAIL", "FAIL_CLASS_A_empty_or_mismatch_binding"


def grade_rv1_python_binding(ledger_rows: list[dict[str, Any]], *, expected_token: str) -> tuple[str, str]:
    return grade_rv_python_binding(ledger_rows, expected_token=expected_token)


def combine_rv_control_verdicts(
    *,
    setup_invalid: str,
    python_verdict: str,
    python_reason: str,
    browser_delivery_ok: bool,
    browser_delivery_reason: str,
    lifecycle_lane: str,
    observability_warnings: list[str],
    binding_fail: tuple[str, str] | None = None,
) -> tuple[str, str, str, str, str, list[str]]:
    """Returns overall, overall_reason, python_lane, browser_delivery_lane, lifecycle_lane, warnings."""
    python_lane = python_verdict if python_verdict else "PENDING"
    browser_lane = "PASS" if browser_delivery_ok else (browser_delivery_reason or "INVALID_BROWSER_DELIVERY")
    lifecycle = lifecycle_lane if lifecycle_lane else "PASS"
    warnings = list(observability_warnings or [])
    if setup_invalid:
        return "INVALID", setup_invalid, python_lane, browser_lane, lifecycle, warnings
    if not browser_delivery_ok:
        return "INVALID", browser_delivery_reason, python_lane, browser_lane, lifecycle, warnings
    if binding_fail and binding_fail[0] == "FAIL":
        return binding_fail[0], binding_fail[1], python_lane, browser_lane, lifecycle, warnings
    if python_verdict == "PASS_RETURN_VALUE_DELIVERY":
        if warnings:
            return (
                "PASS_WITH_OBSERVABILITY_WARN",
                warnings[0],
                "PASS_RETURN_VALUE_DELIVERY",
                "PASS",
                lifecycle,
                warnings,
            )
        return (
            "PASS_RETURN_VALUE_DELIVERY",
            "rv_python_and_browser_delivery",
            "PASS_RETURN_VALUE_DELIVERY",
            "PASS",
            "PASS",
            warnings,
        )
    if python_verdict.startswith("INVALID"):
        return "INVALID", python_reason, python_lane, browser_lane, lifecycle, warnings
    return python_verdict or "INVALID", python_reason or browser_delivery_reason, python_lane, browser_lane, lifecycle, warnings


def combine_rv1_verdicts(
    *,
    setup_invalid: str,
    python_verdict: str,
    python_reason: str,
    browser_ok: bool,
    browser_reason: str,
    binding_fail: tuple[str, str] | None = None,
    browser: dict[str, Any] | None = None,
) -> tuple[str, str, str, str]:
    """Legacy four-tuple; prefer combine_rv_control_verdicts for full lanes."""
    delivery_ok = bool(browser_ok)
    delivery_reason = "PASS" if delivery_ok else browser_reason
    lifecycle_lane, warnings = lifecycle_instrumentation_report(
        browser or {},
        browser_delivery_ok=delivery_ok,
    )
    overall, reason, py, br, _life, _w = combine_rv_control_verdicts(
        setup_invalid=setup_invalid,
        python_verdict=python_verdict,
        python_reason=python_reason,
        browser_delivery_ok=delivery_ok,
        browser_delivery_reason=delivery_reason,
        lifecycle_lane=lifecycle_lane,
        observability_warnings=warnings,
        binding_fail=binding_fail,
    )
    return overall, reason, py, br


def classify_rv2_binding_failure(
    *,
    browser: dict[str, Any],
    declaration_rows: list[dict[str, Any]],
    python_verdict: str,
) -> tuple[str, str]:
    """Map RV2 binding failures to A–D when browser delivery succeeded."""
    from live_draft_solo_rv_binding_ladder import _coalesce_from_row

    if python_verdict == "PASS_RETURN_VALUE_DELIVERY":
        return "", ""
    sender = dict(browser.get("sender_row") or {})
    if sender.get("source_connected") is False or browser.get("sender_current_status") in ("stale", "disconnected"):
        return "FAIL", "A_STALE_IFRAME_SEND"
    post = [
        r
        for r in declaration_rows
        if r.get("event") == "post_delivery_redeclaration"
        or "after_mount" in str(r.get("phase") or "")
    ]
    if not post:
        return "FAIL", "B_POST_DELIVERY_BRANCH_MISS"
    last = post[-1]
    coalesced = _coalesce_from_row(last)
    if not coalesced and sender.get("is_current_registered_instance"):
        return "FAIL", "D_PROTOCOL_VALUE_NOT_ACCEPTED"
    if not coalesced:
        return "FAIL", "B_POST_DELIVERY_BRANCH_MISS"
    return "FAIL", "C_COMPONENT_ID_CHANGED"
