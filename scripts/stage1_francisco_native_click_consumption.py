"""Francisco native click: live st.button binding + Streamlit consumption ack.

Browser-free pure evaluators. Distinguishes Playwright dispatch from Streamlit
widget consumption / callback entry. Never mutates queues.
"""

from __future__ import annotations

import base64
import re
from typing import Any

BINDING_UNIQUE = "unique"

_CLASS_ACK_OK = "FRANCISCO_NATIVE_CLICK_CONSUMPTION_ACK_OK"
_CLASS_DISPATCH_NO_ACK = "FRANCISCO_NATIVE_CLICK_DISPATCHED_WITHOUT_WIDGET_ACK"
_CLASS_NOT_DISPATCHED = "FRANCISCO_NATIVE_CLICK_NOT_DISPATCHED"
_CLASS_PROXY_REJECT = "FRANCISCO_NATIVE_STBUTTON_TARGET_PROXY_REJECTED"
_CLASS_STALE_REJECT = "FRANCISCO_NATIVE_STBUTTON_TARGET_STALE_REJECTED"
_CLASS_LIVE_OK = "FRANCISCO_NATIVE_STBUTTON_TARGET_LIVE_OK"


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _b64_contains_widget_key(payload_b64: str, widget_key: str) -> bool:
    key = _norm(widget_key)
    if not key or not payload_b64:
        return False
    try:
        raw = base64.b64decode(payload_b64)
    except Exception:
        return False
    return key.encode("utf-8") in raw


def ws_samples_contain_widget_key(samples: list[Any] | None, widget_key: str) -> bool:
    """True only when the exact expected widget_key appears in sample payloads."""
    key = _norm(widget_key)
    if not key:
        return False
    key_b = key.encode("utf-8")
    for entry in list(samples or []):
        if not isinstance(entry, dict):
            continue
        if _b64_contains_widget_key(str(entry.get("payload_base64") or ""), key):
            return True
        # Some hooks store decoded snippets.
        for field in ("payload_text", "payload_preview", "decoded_text"):
            text = str(entry.get(field) or "")
            if key in text:
                return True
        raw_hex = str(entry.get("payload_hex") or "")
        if raw_hex and key_b.hex() in raw_hex.replace(" ", "").lower():
            return True
    return False


def evaluate_francisco_native_click_consumption_ack(
    *,
    click_dispatched: bool,
    authorized_rec_card_key: str = "",
    post_click_transport: dict[str, Any] | None = None,
    callback_entered_observed: bool = False,
    trusted_dom_click: bool = False,
) -> dict[str, Any]:
    """Separate browser dispatch from Francisco-widget Streamlit consumption.

    ``click_dispatched`` alone never proves callback entry or membership mutation.
    Generic ``native_widget_event_observed*`` / seq advance is supporting traffic only
    unless the exact ``authorized_rec_card_key`` is correlated or callback entry is observed.
    """
    transport = dict(post_click_transport or {})
    widget_key = _norm(authorized_rec_card_key)
    samples = list(transport.get("ws_log_sample") or [])
    key_in_ws = ws_samples_contain_widget_key(samples, widget_key) if widget_key else False
    generic_native = bool(
        transport.get("native_widget_event_observed_strict")
        or transport.get("native_widget_event_observed")
    )
    seq_changed = bool(transport.get("script_run_seq_changed"))
    generic_traffic = bool(generic_native or seq_changed or transport.get("streamlit_backmsg_sent"))
    callback_obs = bool(callback_entered_observed)
    francisco_ack = bool(key_in_ws or callback_obs)

    if not click_dispatched:
        classification = _CLASS_NOT_DISPATCHED
    elif francisco_ack:
        classification = _CLASS_ACK_OK
    else:
        classification = _CLASS_DISPATCH_NO_ACK

    return {
        "click_dispatched": bool(click_dispatched),
        "trusted_dom_click": bool(trusted_dom_click),
        "expected_widget_key": widget_key,
        "authorized_rec_card_key": widget_key,
        "expected_widget_key_present_in_transport": key_in_ws,
        "generic_streamlit_traffic_observed": generic_traffic,
        "native_widget_event_observed_strict": bool(
            transport.get("native_widget_event_observed_strict")
        ),
        "script_run_seq_changed": seq_changed,
        "callback_entered_observed": callback_obs,
        "francisco_widget_consumption_ack": francisco_ack,
        # Hard semantic fence — dispatch never implies these:
        "click_dispatch_alone_proves_callback": False,
        "click_dispatch_alone_proves_mutation": False,
        "callback_entered_from_dispatch_alone": False,
        "mutation_proven_from_dispatch_alone": False,
        "classification": classification,
        "ok": bool(click_dispatched and francisco_ack),
    }


def evaluate_live_stbutton_target_binding(
    dom_inspection: dict[str, Any] | None,
    *,
    player_name: str,
    expected_widget_key: str = "",
    probe_widget_key: str = "",
    binding_confidence: str = "",
    require_unique_binding: bool = True,
    stale_generation: bool = False,
    proxy_only: bool = False,
    room_match: bool = True,
    pick_match: bool = True,
    player_id_match: bool = True,
    widget_key_match: bool = True,
) -> dict[str, Any]:
    """Fail closed for metadata/proxy/stale targets; accept unique live native st.button."""
    insp = dict(dom_inspection or {})
    failures: list[str] = []
    name = _norm(player_name)

    if stale_generation:
        failures.append("stale_generation")
    if proxy_only:
        failures.append("proxy_only")
    if require_unique_binding and _norm(binding_confidence) and _norm(binding_confidence) != BINDING_UNIQUE:
        failures.append("binding_confidence")
    if not room_match:
        failures.append("room_mismatch")
    if not pick_match:
        failures.append("pick_mismatch")
    if not player_id_match:
        failures.append("player_id_mismatch")
    if not widget_key_match:
        failures.append("widget_key_mismatch")

    if not insp.get("ld_rec_card_meta_found"):
        failures.append("ld_rec_card_meta_missing")
    if int(insp.get("native_st_base_button_count") or 0) < 1:
        failures.append("native_st_base_button_missing")
    if int(insp.get("visible_button_count_in_card") or 0) < 1:
        failures.append("visible_add_button_missing")

    recommended = insp.get("recommended_click") if isinstance(insp.get("recommended_click"), dict) else {}
    if not recommended:
        failures.append("recommended_click_missing")
    else:
        if recommended.get("is_st_base_button") is not True:
            failures.append("not_st_base_button")
        if recommended.get("inside_st_button") is not True:
            failures.append("not_inside_st_button")
        if recommended.get("click_non_native_element") is True:
            failures.append("non_native_click_element")
        if recommended.get("visible") is not True:
            failures.append("recommended_not_visible")
        text = _norm(recommended.get("text"))
        if text and "add to queue" not in text.lower():
            failures.append("button_text_mismatch")

    # When solo exec probe is present, it must match Stage-A widget key.
    exp_key = _norm(expected_widget_key)
    probe_key = _norm(probe_widget_key)
    if exp_key and probe_key and probe_key != exp_key:
        failures.append("exec_probe_widget_key_mismatch")
    if exp_key and probe_key == "" and insp.get("exec_probe_required") is True:
        failures.append("exec_probe_widget_key_missing")

    if name and _norm(insp.get("player_name")) and _norm(insp.get("player_name")).lower() != name.lower():
        failures.append("player_name_mismatch")

    # Duplicate visible Add-to-Queue in the same card without unique identity → reject.
    visible_n = int(insp.get("visible_button_count_in_card") or 0)
    if visible_n > 1 and _norm(binding_confidence) != BINDING_UNIQUE:
        failures.append("duplicate_visible_add_without_unique_binding")

    ok = not failures
    if "stale_generation" in failures or "proxy_only" in failures:
        classification = _CLASS_STALE_REJECT if "stale_generation" in failures else _CLASS_PROXY_REJECT
    elif ok:
        classification = _CLASS_LIVE_OK
    else:
        classification = _CLASS_PROXY_REJECT if "proxy_only" in failures else _CLASS_STALE_REJECT

    return {
        "ok": ok,
        "failures": failures,
        "classification": classification,
        "maps_ld_rec_card_meta_to_st_button": bool(
            insp.get("ld_rec_card_meta_found")
            and int(insp.get("native_st_base_button_count") or 0) >= 1
            and recommended.get("is_st_base_button") is True
        ),
        "recommended_is_interactive_st_button": bool(
            recommended.get("is_st_base_button") is True
            and recommended.get("inside_st_button") is True
            and recommended.get("click_non_native_element") is not True
        ),
        "expected_widget_key": exp_key,
        "probe_widget_key": probe_key,
    }


def merge_candidate_with_live_reacquisition(
    candidate: dict[str, Any] | None,
    live: dict[str, Any] | None,
) -> dict[str, Any]:
    """Replace positional/stale fields with live reacquisition before the single click.

    Never invents a second click. Caller must dispatch at most once on the result.
    """
    base = dict(candidate or {})
    live_row = dict(live or {})
    if not live_row:
        return base
    out = dict(base)
    for key in (
        "frameIndex",
        "frameUrl",
        "index_in_frame",
        "button_text",
        "bounding_box",
        "dom_generation_ts",
        "binding_via",
        "binding_confidence",
        "player_name",
        "visible",
        "enabled",
        "attached_to_dom",
        "widget_key",
        "player_id",
        "room_id",
        "pick_index",
        "current_pick_index",
    ):
        if live_row.get(key) not in (None, ""):
            out[key] = live_row.get(key)
    out["live_reacquired"] = True
    out["reacquisition_source"] = str(live_row.get("reacquisition_source") or "live_dom")
    return out


def parity_replay_dispatch_once(
    *,
    stage_a_authorized: bool,
    metadata_candidate: dict[str, Any] | None,
    live_target: dict[str, Any] | None,
    live_binding_eval: dict[str, Any] | None,
    streamlit_ack: dict[str, Any] | None,
    allow_dispatch_without_live: bool = False,
) -> dict[str, Any]:
    """Browser-free parity replay for Stage A → reacquire → one dispatch → ack."""
    helper_invocations = 0
    browser_clicks = 0
    js_fallback = False
    retry_count = 0
    direct_callback = False
    direct_queue_helper = False
    q_append = False

    if not stage_a_authorized:
        return {
            "ok": False,
            "dispatched": False,
            "reason": "stage_a_not_authorized",
            "helper_invocations": 0,
            "browser_clicks": 0,
            "retry_count": 0,
        }

    meta = dict(metadata_candidate or {})
    live = dict(live_target or {})
    binding = dict(live_binding_eval or {})

    if meta and not live and not allow_dispatch_without_live:
        # Metadata/proxy-only path: fail before dispatch.
        return {
            "ok": False,
            "dispatched": False,
            "reason": "metadata_proxy_only_no_live_stbutton",
            "helper_invocations": 0,
            "browser_clicks": 0,
            "retry_count": 0,
            "click_dispatched": False,
            "callback_entered": False,
            "mutation_proven": False,
        }

    if binding and binding.get("ok") is False:
        return {
            "ok": False,
            "dispatched": False,
            "reason": "live_target_rejected",
            "failures": list(binding.get("failures") or []),
            "helper_invocations": 0,
            "browser_clicks": 0,
            "retry_count": 0,
            "click_dispatched": False,
            "callback_entered": False,
            "mutation_proven": False,
        }

    # Single final target chosen before the one click.
    final_candidate = merge_candidate_with_live_reacquisition(meta, live)
    helper_invocations = 1
    browser_clicks = 1
    click_dispatched = True

    ack = dict(streamlit_ack or {})
    if not ack:
        ack = evaluate_francisco_native_click_consumption_ack(
            click_dispatched=True,
            authorized_rec_card_key=_norm(final_candidate.get("widget_key")),
            post_click_transport={},
            callback_entered_observed=False,
            trusted_dom_click=True,
        )

    callback_entered = bool(ack.get("callback_entered_observed") or ack.get("francisco_widget_consumption_ack"))
    # Membership still requires POST authority elsewhere — never from dispatch alone.
    mutation_proven = bool(ack.get("mutation_proven")) if "mutation_proven" in ack else False

    return {
        "ok": bool(click_dispatched and ack.get("francisco_widget_consumption_ack")),
        "dispatched": True,
        "click_dispatched": click_dispatched,
        "final_candidate": final_candidate,
        "helper_invocations": helper_invocations,
        "browser_clicks": browser_clicks,
        "js_fallback": js_fallback,
        "retry_count": retry_count,
        "direct_callback_invocation": direct_callback,
        "direct_queue_helper": direct_queue_helper,
        "q_append": q_append,
        "callback_entered": callback_entered and not (
            click_dispatched and not ack.get("francisco_widget_consumption_ack")
        ),
        "mutation_proven": mutation_proven,
        "consumption_ack": ack,
        "second_dispatch": False,
    }
