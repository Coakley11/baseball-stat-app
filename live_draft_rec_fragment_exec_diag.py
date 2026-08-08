"""Fragment-local execution diagnostics for recommendation-card widgets (solo diag only)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY = "_solo_stage1_recommendation_fragment_run_seq"
RECOMMENDATION_FRAGMENT_INVOCATION_KEY = "_solo_stage1_recommendation_fragment_invocations"
FRAGMENT_CALLBACK_LEDGER_KEY = "_live_draft_rec_fragment_callback_ledger"
FRAGMENT_PROBE_COUNTER_KEY = "_live_draft_rec_fragment_probe_click_count"
FRAGMENT_PROBE_LAST_KEY = "_live_draft_rec_fragment_probe_last"
FRAGMENT_EXEC_IMPL_REV = "rec_fragment_exec_diag_v2"
FRAGMENT_EXEC_PROBE_ELEMENT_ID = "solo-stage1-rec-fragment-exec-diag"
FRAGMENT_CALLBACK_LEDGER_PROBE_ID = "solo-stage1-rec-fragment-callback-ledger"
FRAGMENT_PROBE_BUTTON_LABEL = "Stage1 Recommendation Widget Probe"
MAX_LEDGER_ROWS = 48
MAX_INVOCATIONS = 64


def _solo_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def _full_app_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def execution_context_map() -> dict[str, str]:
    """Static map for harness/docs — Pause vs recommendation fragment paths."""
    return {
        "pause_control": "live_draft_control_center_ui (full-app shell, outside heavy_paint fragment)",
        "recommendation_paint_entry": "streamlit_app._paint_heavy_recommendations_body",
        "recommendation_fragment_wrapper": "live_draft_heavy_paint_ui.render_deferred_heavy_paint_fragment",
        "recommendation_cards": "live_draft_room_ui.render_live_draft_rec_cards",
        "francisco_callback": "live_draft_room_ui._on_rec_queue_click",
        "fragment_probe_callback": "live_draft_rec_fragment_exec_diag.on_recommendation_fragment_probe_click",
        "full_app_run_seq_source": "live_draft_stage1_production_ledger STAGE1_SCRIPT_SEQ_KEY",
        "fragment_run_seq_source": RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY,
    }


def enter_recommendation_paint_invocation(
    session: dict[str, Any],
    st: Any | None,
    *,
    via: str,
) -> dict[str, Any]:
    """Call at the start of _paint_heavy_recommendations_body (fragment or full-page)."""
    via_norm = str(via or "unknown").strip()[:32]
    seq = int(session.get(RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY) or 0) + 1
    session[RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY] = seq
    row: dict[str, Any] = {
        "ts": time.time(),
        "via": via_norm,
        "recommendation_fragment_run_seq": seq,
        "full_app_run_seq": _full_app_run_seq(session),
        "streamlit_session_id": _streamlit_session_id(),
        "fragment_context": via_norm == "fragment",
    }
    inv = list(session.get(RECOMMENDATION_FRAGMENT_INVOCATION_KEY) or [])
    inv.append(row)
    session[RECOMMENDATION_FRAGMENT_INVOCATION_KEY] = inv[-MAX_INVOCATIONS:]
    session["_solo_stage1_in_fragment_run"] = bool(row["fragment_context"])
    session["_solo_stage1_fragment_run_hint"] = "fragment_run" if row["fragment_context"] else "full_run"
    session["_solo_stage1_last_recommendation_paint"] = dict(row)
    return row


def recommendation_fragment_run_seq(session: dict[str, Any]) -> int:
    return int(session.get(RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY) or 0)


def append_fragment_callback_ledger(session: dict[str, Any], row: dict[str, Any]) -> None:
    book = list(session.get(FRAGMENT_CALLBACK_LEDGER_KEY) or [])
    book.append(dict(row))
    session[FRAGMENT_CALLBACK_LEDGER_KEY] = book[-MAX_LEDGER_ROWS:]
    session["_live_draft_rec_fragment_callback_ledger_last"] = dict(row)


def fragment_callback_ledger_export(session: dict[str, Any]) -> dict[str, Any]:
    book = list(session.get(FRAGMENT_CALLBACK_LEDGER_KEY) or [])
    return {
        "ledger_len": len(book),
        "last": dict(session.get("_live_draft_rec_fragment_callback_ledger_last") or {}),
        "rows": book[-12:],
        "probe_click_count": int(session.get(FRAGMENT_PROBE_COUNTER_KEY) or 0),
        "probe_last": dict(session.get(FRAGMENT_PROBE_LAST_KEY) or {}),
    }


def record_rec_queue_callback_entry(
    session: dict[str, Any],
    *,
    event_id: str,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    queue_before: list[str],
    callback_callable_name: str = "_on_rec_queue_click",
) -> None:
    """Durable ledger entry — survives fragment reruns without outer DOM repaint."""
    row = {
        "event_id": str(event_id or "")[:24] or uuid.uuid4().hex[:12],
        "ts": time.time(),
        "callback_id": callback_callable_name,
        "callback_entered": True,
        "source": "rec_card_add_to_queue",
        "room_id": str(room_id or "").strip(),
        "pick_index": int(pick_index),
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip(),
        "widget_key": str(widget_key or "").strip(),
        "full_app_run_seq": _full_app_run_seq(session),
        "recommendation_fragment_run_seq": recommendation_fragment_run_seq(session),
        "streamlit_session_id": _streamlit_session_id(),
        "queue_before_mutation": list(queue_before)[:20],
    }
    append_fragment_callback_ledger(session, row)


def on_recommendation_fragment_probe_click(
    _session: dict[str, Any],
    _room_id: str = "",
    _pick_index: int = 0,
    _widget_key: str = "",
) -> None:
    session = _session
    n = int(session.get(FRAGMENT_PROBE_COUNTER_KEY) or 0) + 1
    session[FRAGMENT_PROBE_COUNTER_KEY] = n
    row = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "callback_id": "on_recommendation_fragment_probe_click",
        "callback_entered": True,
        "source": "fragment_widget_probe",
        "room_id": str(_room_id or "").strip(),
        "pick_index": int(_pick_index),
        "widget_key": str(_widget_key or "").strip(),
        "full_app_run_seq": _full_app_run_seq(session),
        "recommendation_fragment_run_seq": recommendation_fragment_run_seq(session),
        "streamlit_session_id": _streamlit_session_id(),
        "probe_click_index": n,
    }
    session[FRAGMENT_PROBE_LAST_KEY] = dict(row)
    append_fragment_callback_ledger(session, row)


def _callback_registration_meta(fn: Any, *, args_preview: str = "") -> dict[str, str]:
    mod = getattr(fn, "__module__", "") or ""
    name = getattr(fn, "__name__", "") or ""
    return {
        "callback_module": str(mod)[:120],
        "callback_qualname": str(name)[:80],
        "callback_args_preview": str(args_preview)[:160],
    }


def emit_rec_card_widget_exec_probe(
    st: Any,
    session: dict[str, Any],
    *,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    callback_id: str,
    widget_kind: str,
    callback_fn: Any | None = None,
    disabled: bool = False,
    help_present: bool | None = None,
    help_variant: str = "",
    followed_widget_event: bool = False,
) -> None:
    """DOM probe co-emitted with st.button in the recommendation card body."""
    if not _solo_diag_enabled(st, session):
        return
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    paint = dict(session.get("_solo_stage1_last_recommendation_paint") or {})
    reg = _callback_registration_meta(callback_fn) if callback_fn is not None else {}
    st.markdown(
        f'<div class="rec-fragment-exec-probe-card" data-probe-element="{FRAGMENT_EXEC_PROBE_ELEMENT_ID}" '
        f'data-widget-kind="{safe(widget_kind)}" '
        f'data-room-id="{safe(room_id)}" '
        f'data-pick-index="{int(pick_index)}" '
        f'data-player-id="{safe(player_id)}" '
        f'data-player-name="{safe(player_name)}" '
        f'data-widget-key="{safe(widget_key)}" '
        f'data-callback-id="{safe(callback_id)}" '
        f'data-full-app-run-seq="{_full_app_run_seq(session)}" '
        f'data-recommendation-fragment-run-seq="{recommendation_fragment_run_seq(session)}" '
        f'data-fragment-render-ts="{time.time()}" '
        f'data-fragment-context="{1 if paint.get("fragment_context") else 0}" '
        f'data-paint-via="{safe(paint.get("via"))}" '
        f'data-streamlit-session-id="{safe(_streamlit_session_id())}" '
        f'data-followed-widget-event="{1 if followed_widget_event else 0}" '
        f'data-help-variant="{safe(help_variant)}" '
        f'data-help-present="{1 if help_present else 0 if help_present is not None else ""}" '
        f'data-disabled="{1 if disabled else 0}" '
        f'data-callback-module="{safe(reg.get("callback_module"))}" '
        f'data-callback-qualname="{safe(reg.get("callback_qualname"))}" '
        f'data-impl-rev="{FRAGMENT_EXEC_IMPL_REV}"></div>',
        unsafe_allow_html=True,
    )


def reemit_fragment_callback_ledger_probe(st: Any, session: dict[str, Any]) -> None:
    """Re-emit session-backed ledger DOM without repainting recommendation cards."""
    render_fragment_callback_ledger_probe(st, session)


def render_fragment_callback_ledger_probe(st: Any, session: dict[str, Any]) -> None:
    """Session-backed callback ledger — readable without outer full-app repaint."""
    if not _solo_diag_enabled(st, session):
        return
    export = fragment_callback_ledger_export(session)
    payload = json.dumps(export, default=str)[:16000]
    safe = lambda s: str(s or "").replace('"', "'")[:200]
    last = dict(session.get("_live_draft_rec_fragment_callback_ledger_last") or {})
    st.markdown(
        f'<div id="{FRAGMENT_CALLBACK_LEDGER_PROBE_ID}" '
        f'data-ledger-len="{len(session.get(FRAGMENT_CALLBACK_LEDGER_KEY) or [])}" '
        f'data-last-callback-entered="{1 if last.get("callback_entered") else 0}" '
        f'data-last-source="{safe(last.get("source"))}" '
        f'data-last-event-id="{safe(last.get("event_id"))}" '
        f'data-last-callback-id="{safe(last.get("callback_id"))}" '
        f'data-last-ts="{safe(last.get("ts"))}" '
        f'data-last-room-id="{safe(last.get("room_id"))}" '
        f'data-last-pick-index="{safe(last.get("pick_index"))}" '
        f'data-last-player-name="{safe(last.get("player_name"))}" '
        f'data-last-full-app-run-seq="{safe(last.get("full_app_run_seq"))}" '
        f'data-last-recommendation-fragment-run-seq="{safe(last.get("recommendation_fragment_run_seq"))}" '
        f'data-probe-click-count="{int(session.get(FRAGMENT_PROBE_COUNTER_KEY) or 0)}" '
        f'data-impl-rev="{FRAGMENT_EXEC_IMPL_REV}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )


def build_fragment_probe_widget_key(*, room_id: str, pick_index: int) -> str:
    rid = str(room_id or "noroom").strip().upper()[:16]
    return f"rec_fragment_widget_probe_{rid}_{int(pick_index)}_diag"
