"""Authoritative Stage 1A receipt levels (LEVEL 1–5); harness grading only."""

from __future__ import annotations

from typing import Any

PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
SET_COMPONENT_VALUE = "streamlit:setComponentValue"


def is_logical_value_receipt(row: dict[str, Any], *, expected_token: str = "") -> bool:
    """True only for streamlit:setComponentValue (not register / frame-height / duplicates)."""
    if not isinstance(row, dict):
        return False
    if row.get("has_set_component_value") is True:
        mt_ok = True
    else:
        mt_ok = str(row.get("message_type") or "") == SET_COMPONENT_VALUE or row.get("is_set_component_value") is True
    if not mt_ok:
        return False
    if row.get("is_register_component") or row.get("is_frame_height"):
        return False
    mt = str(row.get("message_type") or "")
    if mt in ("streamlit:setFrameHeight", "streamlit:registerComponent", "solo:rvCountdownRegister"):
        return False
    if expected_token:
        val = str(row.get("value_preview") or row.get("token_or_value_preview") or row.get("value") or row.get("token") or "")
        return val == expected_token or expected_token in val
    return True


def classify_receipt_levels(
    *,
    expected_token: str,
    iframe_send_stages: list[str] | None = None,
    immediate_parent_messages: list[dict[str, Any]] | None = None,
    top_parent_messages: list[dict[str, Any]] | None = None,
    coalesced_value: str = "",
    session_state_value: str = "",
    direct_return: str = "",
    token_claim_accepted: bool = False,
    registered_instance_id: str = "",
) -> dict[str, Any]:
    iframe_stages = set(iframe_send_stages or [])
    level1 = bool(
        {"transport_before_postMessage", "component_value_sent", "expiration_send_claimed"} & iframe_stages
        or "component_value_sent" in iframe_stages
    )

    imm = list(immediate_parent_messages or [])
    top = list(top_parent_messages or []) if top_parent_messages is not None else imm
    imm_scv = [m for m in imm if is_logical_value_receipt(m, expected_token=expected_token)]
    top_scv = [m for m in top if is_logical_value_receipt(m, expected_token=expected_token)]
    level2_imm = len(imm_scv) >= 1
    level2_top = len(top_scv) >= 1

    def _source_current(m: dict[str, Any]) -> bool:
        if m.get("source_matches_current_production_iframe") is True:
            return True
        assoc = m.get("iframe_association") or {}
        inst = str(assoc.get("iframe_instance_id") or m.get("iframe_instance_id") or "")
        if registered_instance_id and inst:
            return inst == registered_instance_id
        return bool(assoc.get("source_matches_content_window"))

    level3_imm = level2_imm and all(_source_current(m) for m in imm_scv)
    level3_top = level2_top and all(_source_current(m) for m in top_scv)

    bound = bool(
        token_claim_accepted
        or (expected_token and expected_token in (coalesced_value or ""))
        or (expected_token and expected_token in (session_state_value or ""))
        or (expected_token and expected_token in (direct_return or ""))
    )
    level5 = bound

    level4 = level3_top and bound

    non_value_imm = [
        m
        for m in imm
        if str(m.get("message_type") or "") in ("solo:rvCountdownRegister", "streamlit:setFrameHeight", "streamlit:registerComponent")
    ]

    return {
        "LEVEL_1_IFRAME_SEND_EXECUTED": level1,
        "LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_IMMEDIATE": level2_imm,
        "LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_TOP": level2_top,
        "LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_IMMEDIATE": level3_imm,
        "LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_TOP": level3_top,
        "LEVEL_4_STREAMLIT_PROTOCOL_ACCEPTED": level4,
        "LEVEL_5_PYTHON_VALUE_BOUND": level5,
        "logical_set_component_value_receipts_immediate": len(imm_scv),
        "logical_set_component_value_receipts_top": len(top_scv),
        "non_value_parent_messages_immediate": len(non_value_imm),
        "misleading_legacy_deduped_parent_count": len(
            {str(m.get("token") or m.get("value") or m) for m in imm if m}
        ),
    }


def refine_a5a_subclass(levels: dict[str, Any], *, unrelated_render_after_send: bool = False) -> str:
    if levels.get("LEVEL_5_PYTHON_VALUE_BOUND"):
        return "A5a5"
    if not levels.get("LEVEL_1_IFRAME_SEND_EXECUTED"):
        return "A5a6"
    if not levels.get("LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_IMMEDIATE") and not levels.get(
        "LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_TOP"
    ):
        return "A5a1"
    if levels.get("LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_TOP") and not levels.get(
        "LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_TOP"
    ):
        return "A5a2"
    if levels.get("LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_TOP") and not levels.get("LEVEL_5_PYTHON_VALUE_BOUND"):
        return "A5a3"
    if unrelated_render_after_send and not levels.get("LEVEL_4_STREAMLIT_PROTOCOL_ACCEPTED"):
        return "A5a6"
    return "A5a3"


def classify_source_windows(
    messages: list[dict[str, Any]],
    *,
    expected_token: str,
    registered_instance_id: str = "",
) -> dict[str, Any]:
    scv = [m for m in messages if is_logical_value_receipt(m, expected_token=expected_token)]
    stale: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    disconnected: list[dict[str, Any]] = []
    for m in scv:
        assoc = m.get("iframe_association") or {}
        if assoc.get("iframe_is_connected") is False:
            disconnected.append(m)
        inst = str(assoc.get("iframe_instance_id") or m.get("iframe_instance_id") or "")
        if registered_instance_id and inst and inst != registered_instance_id:
            stale.append(m)
        elif m.get("source_matches_current_production_iframe") is False and registered_instance_id:
            stale.append(m)
        else:
            current.append(m)
    return {
        "logical_scv_count": len(scv),
        "current_source_scv": current,
        "stale_source_scv": stale,
        "disconnected_source_scv": disconnected,
    }


def build_correlation_timeline(
    *,
    token_sent: str,
    deadline_before: Any,
    client_stages: list[str] | None,
    iframe_entries: list[dict[str, Any]] | None,
    immediate_parent_messages: list[dict[str, Any]] | None,
    top_parent_messages: list[dict[str, Any]] | None,
    merged_server_ledger: list[dict[str, Any]] | None,
    timer_armed_at_elapsed: float | None,
    value_sent_at_elapsed: float | None,
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    if deadline_before is not None:
        timeline.append({"kind": "expiration_deadline", "detail": str(deadline_before)})
    for e in iframe_entries or []:
        if not isinstance(e, dict):
            continue
        stage = str(e.get("stage") or "")
        if stage in (
            "transport_before_postMessage",
            "expiration_send_claimed",
            "transport_postmessage_invoked",
            "component_value_sent",
            "browser_deadline_crossed",
        ):
            timeline.append(
                {
                    "kind": "iframe",
                    "ts_ms": e.get("ts"),
                    "stage": stage,
                    "extra_preview": str(e.get("extra") or "")[:240],
                }
            )
    for m in immediate_parent_messages or []:
        if not is_logical_value_receipt(m, expected_token=token_sent):
            continue
        timeline.append(
            {
                "kind": "parent_immediate",
                "ts_ms": m.get("ts") or m.get("wall_ts"),
                "message_type": m.get("message_type"),
                "value_preview": m.get("value_preview"),
            }
        )
    for m in top_parent_messages or []:
        if not is_logical_value_receipt(m, expected_token=token_sent):
            continue
        timeline.append(
            {
                "kind": "parent_top",
                "ts_ms": m.get("wall_ts") or m.get("ts"),
                "message_type": m.get("message_type"),
                "value_preview": m.get("value_preview"),
            }
        )
    for row in merged_server_ledger or []:
        if not isinstance(row, dict):
            continue
        ev = str(row.get("event") or "")
        if ev.startswith("production_stage1_"):
            timeline.append(
                {
                    "kind": "python_ledger",
                    "ts": row.get("ts"),
                    "event": ev,
                    "script_run_seq": row.get("script_run_seq"),
                }
            )
    if timer_armed_at_elapsed is not None:
        timeline.append({"kind": "harness", "event": "timer_armed", "elapsed_s": timer_armed_at_elapsed})
    if value_sent_at_elapsed is not None:
        timeline.append({"kind": "harness", "event": "value_sent_observed", "elapsed_s": value_sent_at_elapsed})
    if client_stages and "tick_cancelled" in client_stages:
        timeline.append(
            {"kind": "iframe_lifecycle", "event": "tick_cancelled", "note": "not proof of LEVEL 4 alone"}
        )

    def _sort_key(item: dict[str, Any]) -> tuple:
        ts = item.get("ts_ms") or item.get("ts")
        try:
            return (float(ts or 0), str(item.get("kind")))
        except (TypeError, ValueError):
            return (0.0, str(item.get("kind")))

    timeline.sort(key=_sort_key)
    return timeline
