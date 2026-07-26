"""One-variable production-parity ladder from passing synthetic B2 (query-param gated)."""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any, Callable

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    SOLO_PERSISTENT_WAKE_WIDGET_KEY,
)

PARITY_QP = "solo_persistent_parity"
PARITY_LOG_KEY = "_solo_parity_ladder_log"
PARITY_META_KEY = "_solo_parity_ladder_meta"
PARITY_PROBE_ID = "solo-persistent-parity-diag"
PARITY_STOP_KEY = "_solo_parity_ladder_stop_page"
PARITY_CONTROL_KEY = "_solo_parity_ladder_control"
PARITY_CALLBACKS_KEY = "_solo_parity_ladder_callbacks"
PARITY_MOUNTED_KEY = "_solo_parity_ladder_mounted"
PARITY_SKIP_CLAIM_KEY = "_solo_parity_skip_delivery_claim"
PARITY_TRANSPORT_ONLY_KEY = "_solo_parity_transport_only_deliver"
PARITY_HANDLED_WAKE_KEY = "_solo_parity_handled_persistent_wake"
SYNTHETIC_SECONDS = 10
VALID = frozenset({"P0", "P1", "P2", "P3", "P4", "P5", "P6"})


def _qp_get(st: Any | None, name: str) -> str:
    if st is None:
        return ""
    try:
        from live_draft_cloud_diagnostics import _qp_get as get_qp

        return get_qp(st, name)
    except ImportError:
        return ""


def parity_control(st: Any | None, session: dict[str, Any]) -> str:
    cached = str(session.get(PARITY_CONTROL_KEY) or "").strip().upper()
    if cached in VALID:
        return cached
    raw = _qp_get(st, PARITY_QP).strip().upper()
    if raw in VALID:
        session[PARITY_CONTROL_KEY] = raw
    return raw if raw in VALID else ""


def parity_ladder_active(st: Any | None, session: dict[str, Any]) -> bool:
    return parity_control(st, session) in VALID


def parity_should_stop_page(session: dict[str, Any]) -> bool:
    return bool(session.get(PARITY_STOP_KEY))


def _append_log(session: dict[str, Any], stage: str, **fields: Any) -> None:
    row = {"ts": time.time(), "stage": stage, **fields}
    log = list(session.get(PARITY_LOG_KEY) or [])
    log.append(row)
    session[PARITY_LOG_KEY] = log[-200:]


def _snapshot_session(st: Any, session: dict[str, Any], key: str, label: str) -> None:
    _append_log(
        session,
        f"session_snapshot_{label}",
        widget_key=key,
        key_in_session=key in st.session_state,
        raw_value=repr(st.session_state.get(key))[:400] if key in st.session_state else "",
    )


def _synthetic_room(*, deadline: float) -> dict[str, Any]:
    return {
        "draft_room_id": "PARITY",
        "draft_id": "PARITY",
        "status": "in_progress",
        "current_pick_index": 0,
        "timer_deadline": deadline,
        "config": {"draft_setup_mode": "solo", "timer_seconds": SYNTHETIC_SECONDS},
    }


def build_parity_token(control: str) -> tuple[str, float]:
    deadline = time.time() + float(SYNTHETIC_SECONDS)
    token = f"WIRING_{control.upper()}|0|{deadline:.3f}"
    return token, deadline


def _clear_widget(st: Any, session: dict[str, Any], key: str) -> None:
    prior = repr(st.session_state.get(key))[:200] if key in st.session_state else ""
    try:
        del st.session_state[key]
    except Exception:
        st.session_state.pop(key, None)
    _append_log(session, "widget_key_cleared_pre_mount", widget_key=key, prior_raw=prior)


def _resolve_widget_key(control: str, st: Any, session: dict[str, Any]) -> str:
    if control in ("P1", "P3", "P4", "P5", "P6"):
        return SOLO_PERSISTENT_WAKE_WIDGET_KEY
    qp = _qp_get(st, "solo_parity_widget_key").strip()
    if qp:
        return qp[:120]
    existing = str(session.get("_solo_parity_widget_key") or "").strip()
    if existing:
        return existing
    key = f"solo_parity_{control.lower()}_{uuid.uuid4().hex[:10]}"
    session["_solo_parity_widget_key"] = key
    return key


def _parity_simple_deliver(st: Any, session: dict[str, Any], raw: Any, key: str, *, control: str) -> None:
    expected = str(session.get("_solo_parity_expected_token") or "")
    seq = int(session.get(f"{key}_parity_callback_seq") or 0) + 1
    session[f"{key}_parity_callback_seq"] = seq
    row = {
        "ts": time.time(),
        "seq": seq,
        "expected_token": expected,
        "actual_raw": repr(raw)[:400],
        "source": "parity_simple_on_change",
        "control": control,
    }
    callbacks = list(session.get(PARITY_CALLBACKS_KEY) or [])
    callbacks.append(row)
    session[PARITY_CALLBACKS_KEY] = callbacks[-50:]
    _append_log(session, "parity_callback", widget_key=key, **row)


def _production_state_snapshot(session: dict[str, Any], room: dict[str, Any] | None = None) -> dict[str, Any]:
    owners = session.get("_solo_token_delivery_owner")
    rejected = session.get("_solo_wake_rejected_tokens")
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    deadline = None
    pick = None
    if isinstance(live, dict):
        pick = live.get("current_pick_index")
        deadline = live.get("timer_deadline")
        try:
            from live_draft_timer_logic import live_draft_timer_deadline

            deadline = live_draft_timer_deadline(live) or deadline
        except ImportError:
            pass
    return {
        "SOLO_PERSISTENT_WAKE_TOKEN_KEY": str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or "")[:400],
        "stable_widget_key_raw": str(session.get(SOLO_PERSISTENT_WAKE_WIDGET_KEY) or "")[:200],
        "delivery_owner_tokens": dict(owners) if isinstance(owners, dict) else owners,
        "rejected_tokens": dict(rejected) if isinstance(rejected, dict) else rejected,
        "skip_late_flush_token": str(session.get("_solo_skip_late_flush_token") or "")[:400],
        "pending_callback_source": str(session.get("_solo_pending_callback_source") or ""),
        "pick_latch": session.get("_solo_persistent_wake_pick_latch"),
        "actionable_key": session.get("_solo_persistent_wake_actionable"),
        "component_wake_seen": str(session.get("_solo_component_wake_seen_token") or "")[:400],
        "last_processed_token": str(session.get("_solo_component_wake_seen_token") or "")[:400],
        "expected_room_pick": pick,
        "expected_timer_deadline": deadline,
    }


def _mount_b2_style(
    st: Any,
    session: dict[str, Any],
    *,
    control: str,
    key: str,
    token: str,
    ls_key: str,
    deliver: Callable[[Any, dict[str, Any], Any, str], None],
) -> Any:
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    room = _synthetic_room(deadline=float(token.split("|")[2]))
    return render_micro_isolation_once(
        st,
        session,
        placement=control,
        location=f"parity_ladder_{control.lower()}",
        draft_id="PARITY",
        route=True,
        persistent=control in ("P3", "P4", "P5"),
        session_prefix=f"_solo_parity_micro_{control.lower()}_",
        widget_key=key,
        production_room=room,
        production_expire_token=token,
        production_actionable=True,
        production_delivery_only=False,
        deliver_callback=deliver,
        suppress_immediate_session_on_change=True,
        chain_persist_key=ls_key,
    )


def _run_p6_persistent_wake(st: Any, session: dict[str, Any], room: Any, *, key: str) -> str:
    from live_draft_solo_persistent_wake import try_solo_persistent_wake_ldr_entry

    deadline = time.time() + float(SYNTHETIC_SECONDS)
    synth = _synthetic_room(deadline=deadline)
    session["live_draft_room"] = synth
    session["live_draft_setup_mode"] = "solo"
    session.pop("active_shared_draft_room_code", None)
    from solo_countdown_component import build_solo_expire_token

    token = build_solo_expire_token(synth)
    session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] = token
    session["_solo_parity_expected_token"] = token
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True
    session["_solo_expire_owner"] = "wake"
    session.pop("_solo_persistent_wake_flush_disabled", None)
    session[PARITY_HANDLED_WAKE_KEY] = True
    _snapshot_session(st, session, key, "before_mount")
    try_solo_persistent_wake_ldr_entry(st, session, synth)
    _snapshot_session(st, session, key, "after_mount")
    return token


def _record_production_callback(session: dict[str, Any], *, raw: Any, key: str, control: str) -> None:
    expected = str(session.get("_solo_parity_expected_token") or "")
    seq = int(session.get(f"{key}_parity_callback_seq") or 0) + 1
    session[f"{key}_parity_callback_seq"] = seq
    prod_n = int(session.get("_solo_transport_production_on_change_count") or 0)
    try:
        from live_draft_solo_transport_boundary_diag import PRODUCTION_CALLBACK_FLAG

        prod_n = max(prod_n, int(session.get(f"{PRODUCTION_CALLBACK_FLAG}_count") or 0))
    except ImportError:
        pass
    row = {
        "ts": time.time(),
        "seq": seq,
        "expected_token": expected,
        "actual_raw": repr(raw)[:400],
        "source": "production_deliver_callback",
        "control": control,
        "production_on_change_count": prod_n,
    }
    callbacks = list(session.get(PARITY_CALLBACKS_KEY) or [])
    callbacks.append(row)
    session[PARITY_CALLBACKS_KEY] = callbacks[-50:]
    _append_log(session, "parity_production_callback", widget_key=key, **row)


def try_parity_ladder_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    control = parity_control(st, session)
    if control not in VALID:
        return False

    try:
        from live_draft_solo_delivery_diag import delivery_diag_active

        if not delivery_diag_active(st, session):
            return False
    except ImportError:
        pass

    session[PARITY_CONTROL_KEY] = control
    session["_solo_persistent_wake_flush_disabled"] = control not in ("P6",)
    session[PARITY_STOP_KEY] = control in ("P0", "P1", "P2", "P3")
    session.pop(PARITY_SKIP_CLAIM_KEY, None)
    session.pop(PARITY_TRANSPORT_ONLY_KEY, None)

    latched = str(session.get("_solo_parity_expected_token") or "").strip()
    if latched:
        token = latched
    else:
        token, _deadline = build_parity_token(control)
        session["_solo_parity_expected_token"] = token

    key = _resolve_widget_key(control, st, session)
    ls_key = str(session.get("_solo_parity_ls_key") or f"solo_parity_ls_{control.lower()}_{uuid.uuid4().hex[:10]}")
    session["_solo_parity_ls_key"] = ls_key

    _snapshot_session(st, session, key, "script_beginning")
    _append_log(session, "parity_control_start", control=control, widget_key=key, expire_token=token[:400])

    try:
        from live_draft_solo_transport_boundary_diag import bootstrap_transport_diagnostics, render_transport_parent_listener
        from live_draft_solo_transport_boundary_diag import transport_logging_active, render_transport_boundary_probe

        bootstrap_transport_diagnostics(st, session)
        if transport_logging_active(st, session):
            render_transport_parent_listener(st)
    except ImportError:
        pass

    try:
        from live_draft_solo_delivery_diag import render_parent_postmessage_listener

        render_parent_postmessage_listener(st)
    except ImportError:
        pass

    delivered = key in st.session_state and str(st.session_state.get(key) or "").strip("'\"") == token
    already = bool(session.get(PARITY_MOUNTED_KEY))

    if control == "P6":
        key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
        if not already:
            if key in st.session_state:
                _clear_widget(st, session, key)
            token = _run_p6_persistent_wake(st, session, room, key=key)
            session[PARITY_MOUNTED_KEY] = True
        else:
            token = str(session.get("_solo_parity_expected_token") or "")
        live = session.get("live_draft_room")
        meta = {
            "control": control,
            "widget_key": key,
            "expire_token": token,
            "session_state_value": repr(st.session_state.get(key))[:400] if key in st.session_state else "",
            "callback_count": int(session.get(f"{key}_parity_callback_seq") or 0),
            "callback_log": list(session.get(PARITY_CALLBACKS_KEY) or []),
            "production_state": _production_state_snapshot(session, live if isinstance(live, dict) else None),
            "page_stopped": parity_should_stop_page(session),
        }
        session[PARITY_META_KEY] = meta
        render_parity_probe(st, session)
        try:
            from live_draft_solo_transport_boundary_diag import render_transport_boundary_probe, transport_logging_active

            if transport_logging_active(st, session):
                render_transport_boundary_probe(st, session)
        except ImportError:
            pass
        return True

    if control == "P1" and not already and not delivered:
        _clear_widget(st, session, key)

    _snapshot_session(st, session, key, "before_mount")

    def deliver_factory(use_production: bool, *, use_claim: bool) -> Callable[[Any, dict[str, Any], Any, str], None]:
        if not use_production:

            def _simple(st2: Any, sess: dict[str, Any], raw: Any, k: str) -> None:
                _parity_simple_deliver(st2, sess, raw, k, control=control)

            return _simple

        def _prod(st2: Any, sess: dict[str, Any], raw: Any, k: str) -> None:
            if not use_claim:
                sess[PARITY_SKIP_CLAIM_KEY] = True
            else:
                sess.pop(PARITY_SKIP_CLAIM_KEY, None)
            from live_draft_solo_persistent_wake import _production_deliver_callback

            _snapshot_session(st2, sess, k, "callback_entry")
            _production_deliver_callback(st2, sess, raw, k)
            _record_production_callback(sess, raw=raw, key=k, control=control)
            owners = sess.get("_solo_token_delivery_owner")
            expected_tok = str(sess.get("_solo_parity_expected_token") or "")
            claim = ""
            if isinstance(owners, dict) and expected_tok:
                claim = str(owners.get(expected_tok) or "")
            _append_log(
                sess,
                "parity_production_deliver_done",
                widget_key=k,
                raw=repr(raw)[:200],
                ownership_claim_result=claim,
            )

        return _prod

    use_prod_cb = control in ("P2", "P3", "P4", "P5")
    use_claim = control in ("P5",)
    deliver = deliver_factory(use_prod_cb, use_claim=use_claim)

    comp_return: Any = None
    if not delivered:
        comp_return = _mount_b2_style(
            st, session, control=control, key=key, token=token, ls_key=ls_key, deliver=deliver
        )
        session[PARITY_MOUNTED_KEY] = True
    else:
        comp_return = st.session_state.get(key) if key in st.session_state else None

    _snapshot_session(st, session, key, "after_mount")

    meta = {
        "control": control,
        "widget_key": key,
        "local_storage_key": ls_key,
        "expire_token": token,
        "component_return": repr(comp_return)[:400],
        "session_state_value": repr(st.session_state.get(key))[:400] if key in st.session_state else "",
        "callback_count": int(session.get(f"{key}_parity_callback_seq") or 0),
        "callback_log": list(session.get(PARITY_CALLBACKS_KEY) or []),
        "production_state": _production_state_snapshot(session, _synthetic_room(deadline=float(token.split("|")[2]))),
        "page_stopped": parity_should_stop_page(session),
    }
    session[PARITY_META_KEY] = meta
    _append_log(session, "parity_mount_complete", control=control, widget_key=key)
    render_parity_probe(st, session)
    try:
        from live_draft_solo_transport_boundary_diag import render_transport_boundary_probe, transport_logging_active

        if transport_logging_active(st, session):
            render_transport_boundary_probe(st, session)
    except ImportError:
        pass
    return True


def render_parity_probe(st: Any, session: dict[str, Any]) -> None:
    meta = dict(session.get(PARITY_META_KEY) or {})
    log = list(session.get(PARITY_LOG_KEY) or [])
    payload = json.dumps({"meta": meta, "log_tail": log[-50:]}, default=str)[:14000]
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    control = str(meta.get("control") or session.get(PARITY_CONTROL_KEY) or "")
    key = str(meta.get("widget_key") or "")
    token = str(meta.get("expire_token") or "")
    st.markdown(
        f'<div id="{PARITY_PROBE_ID}" '
        f'data-control="{control}" '
        f'data-key="{key.replace(chr(34), chr(39))}" '
        f'data-expected-token="{token.replace(chr(34), chr(39))[:200]}" '
        f'data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )
