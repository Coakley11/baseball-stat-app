"""Sibling PRE-Pause click with DOM + Streamlit transport capture."""

from __future__ import annotations

import time
from typing import Any

from stage1_dom_click_capture import (
    CAPTURE_TARGET_PAUSE_SIBLING,
    prepare_isolated_dom_click_capture,
    read_and_summarize_dom_click_capture,
)
from stage1_pause_sibling_scrape import (
    PAUSE_SIBLING_IMPL_REV,
    SIBLING_BUTTON_LABEL,
    scrape_pause_sibling_generation,
    scrape_pause_sibling_probe,
    sibling_delta,
)
from stage1_fragment_batch_console import attach_console_capture, summarize_fragment_batch_console
from stage1_streamlit_click_transport import capture_streamlit_click_transport, clear_ws_boundary_log
from streamlit_app_frame import describe_page_frames, resolve_streamlit_app_frame


def capture_sibling_pre_pause_transport(page, *, session_hint: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"step": "sibling_pre_pause_transport", "started_ts": time.time()}
    frame = resolve_streamlit_app_frame(page)
    out["app_frame_url"] = str(frame.url or "")[:240]
    out["frame_binding"] = describe_page_frames(page)

    before = scrape_pause_sibling_probe(page, frame=frame)
    out["scrape_before"] = before
    if not before.get("probe_found") or str(before.get("impl_rev") or "") != PAUSE_SIBLING_IMPL_REV:
        out["setup_abort"] = "SIBLING_LEDGER_NOT_EXPOSED"
        out["finished_ts"] = time.time()
        return out
    if int(before.get("count") or 0) != 0:
        out["setup_abort"] = "SIBLING_COUNT_BASELINE_NOT_ZERO"
        out["finished_ts"] = time.time()
        return out

    out["generation_before_click"] = scrape_pause_sibling_generation(page, frame=frame)
    loc = frame.get_by_role("button", name=SIBLING_BUTTON_LABEL, exact=True)
    try:
        loc.first.wait_for(state="attached", timeout=12000)
        loc.first.wait_for(state="visible", timeout=12000)
        out["target_attached"] = True
        out["target_visible"] = True
        out["target_enabled"] = bool(loc.first.is_enabled())
        loc.first.scroll_into_view_if_needed(timeout=12000)
    except Exception as exc:
        out["setup_abort"] = "UI_NOT_EXPOSED"
        out["click_error"] = str(exc)[:240]
        out["finished_ts"] = time.time()
        return out

    out["ws_clear"] = clear_ws_boundary_log(page)
    console_rows = attach_console_capture(page)
    prep = prepare_isolated_dom_click_capture(
        frame, capture_target=CAPTURE_TARGET_PAUSE_SIBLING, frame_url_hint=str(frame.url or "")
    )
    out["dom_click_capture_prep"] = prep
    click_ts = time.time()
    try:
        loc.first.click(timeout=12000)
        out["click_dispatched"] = True
    except Exception as exc:
        out["click_dispatched"] = False
        out["click_error"] = str(exc)[:240]
        out["finished_ts"] = time.time()
        return out
    click_ts = time.time()
    out["click_timestamp"] = click_ts
    page.wait_for_timeout(450)

    dom = read_and_summarize_dom_click_capture(frame, capture_target=CAPTURE_TARGET_PAUSE_SIBLING)
    out["dom_click_capture"] = dom
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))

    transport = capture_streamlit_click_transport(
        page,
        click_ts=click_ts,
        frame_url_hint=str(frame.url or ""),
        pre_script_run_seq=str(before.get("full_app_run_seq") or ""),
    )
    out["streamlit_transport"] = transport
    out["browser_console_fragment_batch"] = summarize_fragment_batch_console(
        console_rows, click_ts=click_ts
    )

    frame_after = resolve_streamlit_app_frame(page)
    after = scrape_pause_sibling_probe(page, frame=frame_after)
    out["scrape_after"] = after
    out["generation_after_click"] = scrape_pause_sibling_generation(page, frame=frame_after)
    delta = sibling_delta(before, after)
    out["delta"] = delta
    out["sibling_python_effect"] = int(delta.get("count_delta") or 0) >= 1 and bool(delta.get("new_event"))
    out["full_app_run_seq_before"] = before.get("full_app_run_seq")
    out["full_app_run_seq_after"] = after.get("full_app_run_seq")
    out["streamlit_session_id"] = after.get("streamlit_session_id") or before.get("streamlit_session_id")
    out["inbound_ws_activity_seen"] = bool(transport.get("websocket_inbound_activity_seen"))
    out["finished_ts"] = time.time()
    return out
