"""Staged Solo component → Python delivery isolation (query-param gated)."""

from __future__ import annotations

import json
import time
from typing import Any

SOLO_DELIVERY_LOG_KEY = "_solo_delivery_stage_log"
SOLO_DELIVERY_META_KEY = "_solo_delivery_meta"
SOLO_DELIVERY_RERUN_KEY = "_solo_delivery_rerun_count"
COMPONENT_NAME = "solo_countdown_wake"


def _qp_get(st: Any, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as _get

        return _get(st, name)
    except ImportError:
        return ""


def _qp_flag(st: Any, name: str) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_flag as _flag

        return _flag(st, name)
    except ImportError:
        return False


def delivery_diag_active(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get("_solo_delivery_diag_enabled"):
        return True
    return st is not None and _qp_flag(st, "solo_delivery_diag")


def delivery_case(st: Any | None) -> str:
    raw = (_qp_get(st, "solo_delivery_case") if st is not None else "").strip().upper()
    return raw if raw in ("A", "B", "C", "D") else "D"


def delivery_matrix_cell(st: Any | None) -> int:
    """2×2 matrix: 1 app+minimal, 2 app+solo_wake, 3 route+minimal, 4 route+solo_wake."""
    raw = (_qp_get(st, "solo_delivery_matrix") if st is not None else "").strip()
    if raw.isdigit():
        cell = int(raw)
        if 1 <= cell <= 4:
            return cell
    letter = delivery_case(st) if st is not None else ""
    if letter == "A":
        return 1
    if letter == "B":
        return 4
    return 0


def _solo_room_ready(session: dict[str, Any]) -> dict[str, Any] | None:
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return None
    if str(room.get("status") or "") != "in_progress":
        return None
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return None
    except ImportError:
        pass
    return room


def widget_key_for_room(room: dict[str, Any]) -> str:
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()
    pick_index = int(room.get("current_pick_index") or 0)
    return f"solo_countdown_wake_{draft_id}_{pick_index}"


def note_delivery_stage(session: dict[str, Any], stage: str, **fields: Any) -> None:
    row = {"ts": time.time(), "stage": stage, **fields}
    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    log.append(row)
    session[SOLO_DELIVERY_LOG_KEY] = log[-120:]
    if stage == "on_change_callback_entry":
        meta = dict(session.get(SOLO_DELIVERY_META_KEY) or {})
        meta["on_change_entered"] = True
        meta["on_change_ts"] = row["ts"]
        session[SOLO_DELIVERY_META_KEY] = meta


def bump_delivery_rerun(session: dict[str, Any]) -> int:
    count = int(session.get(SOLO_DELIVERY_RERUN_KEY) or 0) + 1
    session[SOLO_DELIVERY_RERUN_KEY] = count
    return count


def _coerce_wake_token(component_value: Any) -> str:
    from live_draft_solo_heartbeat import _coerce_wake_token as _coerce

    return _coerce(component_value)


def note_production_on_change_if_diag(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    key: str,
) -> None:
    if not delivery_diag_active(st, session) or delivery_case(st) != "D":
        return
    note_delivery_stage(
        session,
        "on_change_callback_entry",
        registration="live_draft_solo_heartbeat.render_solo_countdown_wake_component",
        widget_key_registered=key,
        widget_key_inspected=key,
        raw_session_state=repr(st.session_state.get(key))[:800],
    )
    raw = st.session_state.get(key)
    note_delivery_stage(
        session,
        "session_state_raw_received",
        key=key,
        raw_type=type(raw).__name__ if raw is not None else "NoneType",
    )


def make_traced_on_change(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    key: str,
    *,
    registration: str,
) -> Any:
    def _on_change() -> None:
        note_delivery_stage(
            session,
            "on_change_callback_entry",
            registration=registration,
            widget_key_registered=key,
            widget_key_inspected=key,
            raw_session_state=repr(st.session_state.get(key))[:800],
        )
        raw = st.session_state.get(key)
        note_delivery_stage(
            session,
            "session_state_raw_received",
            key=key,
            raw_type=type(raw).__name__ if raw is not None else "NoneType",
        )
        token = _coerce_wake_token(raw)
        note_delivery_stage(session, "token_coercion_complete", token=token)
        if not token:
            return
        note_delivery_stage(session, "process_solo_component_wake_entered", token=token)
        from live_draft_solo_heartbeat import process_solo_component_wake

        process_solo_component_wake(st, session, room, token)

    return _on_change


def _record_mount_meta(
    session: dict[str, Any],
    *,
    case: str,
    key: str,
    registration: str,
    location: str,
    in_fragment: bool = False,
) -> None:
    session[SOLO_DELIVERY_META_KEY] = {
        "case": case,
        "component_name": COMPONENT_NAME,
        "widget_key_registered": key,
        "widget_key_inspected": key,
        "registration_location": registration,
        "mount_location": location,
        "in_fragment": in_fragment,
        "rerun_count": bump_delivery_rerun(session),
        "session_has_key_before_mount": key in session,
        "duplicate_key_users": _find_duplicate_key_users(session, key),
    }


def _find_duplicate_key_users(session: dict[str, Any], key: str) -> list[str]:
    hits: list[str] = []
    for k in session.keys():
        if k == key:
            hits.append(f"session_state:{k}")
    return hits[:12]


def render_parent_postmessage_listener(st: Any) -> None:
    import streamlit.components.v1 as components

    components.html(
        """<!DOCTYPE html><html><body><script>
        (function(){
          function note(stage, extra){
            try {
              var el = document.getElementById('solo-delivery-parent');
              if (!el) return;
              var chain = el.getAttribute('data-chain') || '';
              el.setAttribute('data-last', stage);
              el.setAttribute('data-chain', chain ? chain + '|' + stage : stage);
              if (extra) el.setAttribute('data-extra', String(extra).slice(0,2000));
            } catch(e){}
          }
          function onMsg(ev){
            var d = ev && ev.data;
            if (!d || d.type !== 'streamlit:setComponentValue') return;
            note('parent_postmessage_received', JSON.stringify({value: d.value}).slice(0,500));
            note('streamlit_frontend_widget_update', 'value_received');
          }
          window.addEventListener('message', onMsg, true);
          note('parent_listener_installed', String(window.location.href||''));
        })();
        </script><div id="solo-delivery-parent" data-chain="" data-last=""></div></body></html>""",
        height=0,
    )


def render_delivery_probe(st: Any, session: dict[str, Any], *, case: str, key: str) -> None:
    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    meta = dict(session.get(SOLO_DELIVERY_META_KEY) or {})
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-40:])
    payload = json.dumps({"log": log[-24:], "meta": meta}, default=str)[:5000]
    st.markdown(
        f'<div id="solo-delivery-diag" '
        f'data-case="{case}" '
        f'data-key="{key.replace(chr(34), chr(39))}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-on-change="{1 if meta.get("on_change_entered") else 0}" '
        f'data-rerun="{int(meta.get("rerun_count") or session.get(SOLO_DELIVERY_RERUN_KEY) or 0)}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )


def _mount_direct_component(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    case: str,
    registration: str,
    location: str,
) -> bool:
    from live_draft_solo_component_diagnostics import bootstrap_solo_component_diag

    bootstrap_solo_component_diag(st, session)
    key = widget_key_for_room(room)
    _record_mount_meta(session, case=case, key=key, registration=registration, location=location)
    render_parent_postmessage_listener(st)
    on_change = make_traced_on_change(st, session, room, key, registration=registration)
    from solo_countdown_component import mount_solo_countdown_wake_direct

    value = mount_solo_countdown_wake_direct(room, key=key, on_change=on_change)
    mounted = value is not None or key in session
    note_delivery_stage(
        session,
        "component_mounted",
        case=case,
        key=key,
        mounted=bool(mounted is not None),
        registration=registration,
    )
    render_delivery_probe(st, session, case=case, key=key)
    return mounted is not None


def render_matrix_probe(
    st: Any,
    session: dict[str, Any],
    *,
    matrix_cell: int,
    component_name: str,
    result: Any,
    passed: bool,
    case_label: str,
) -> None:
    import json

    from minimal_component_wake_repro_core import REQUIRED_CYCLES

    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    meta = dict(session.get(SOLO_DELIVERY_META_KEY) or {})
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-80:])
    callbacks = getattr(result, "callbacks", None) or []
    payload = json.dumps(
        {
            "matrix_cell": matrix_cell,
            "log": log[-40:],
            "meta": meta,
            "diag": getattr(result, "diag", {}),
            "callbacks": callbacks,
            "cycles_done": getattr(result, "cycles_done", 0),
            "required_cycles": REQUIRED_CYCLES,
            "passed": passed,
            "mount_count": getattr(result, "mount_count", meta.get("mount_count")),
        },
        default=str,
    )[:8000]
    wkey = str(getattr(result, "widget_key", "") or "")
    token = str(getattr(result, "token", "") or "")
    st.markdown(
        f'<div id="solo-matrix-diag" '
        f'data-matrix-cell="{matrix_cell}" '
        f'data-case="{case_label}" '
        f'data-passed="{1 if passed else 0}" '
        f'data-callbacks="{len(callbacks)}" '
        f'data-cycles-done="{getattr(result, "cycles_done", 0)}" '
        f'data-component-name="{component_name}" '
        f'data-key="{wkey.replace(chr(34), chr(39))}" '
        f'data-token="{token.replace(chr(34), chr(39))}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-rerun="{int(meta.get("rerun_count") or session.get(SOLO_DELIVERY_RERUN_KEY) or 0)}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
    render_delivery_probe(st, session, case=case_label, key=wkey)


def render_case_a_app_shell_probe(
    st: Any,
    session: dict[str, Any],
    *,
    result: Any,
    passed: bool,
) -> None:
    import json

    from minimal_component_wake_repro_core import COMPONENT_NAME, REQUIRED_CYCLES

    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    meta = dict(session.get(SOLO_DELIVERY_META_KEY) or {})
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-60:])
    payload = json.dumps(
        {
            "log": log[-40:],
            "meta": meta,
            "diag": result.diag,
            "callbacks": result.callbacks,
            "cycles_done": result.cycles_done,
            "required_cycles": REQUIRED_CYCLES,
            "passed": passed,
        },
        default=str,
    )[:8000]
    st.markdown(
        f'<div id="solo-case-a-diag" '
        f'data-case="A" '
        f'data-passed="{1 if passed else 0}" '
        f'data-callbacks="{len(result.callbacks)}" '
        f'data-cycles-done="{result.cycles_done}" '
        f'data-component-name="{COMPONENT_NAME}" '
        f'data-key="{result.widget_key.replace(chr(34), chr(39))}" '
        f'data-token="{result.token.replace(chr(34), chr(39))}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-rerun="{int(meta.get("rerun_count") or session.get(SOLO_DELIVERY_RERUN_KEY) or 0)}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
    render_delivery_probe(st, session, case="A", key=result.widget_key)


def try_delivery_diag_case_a_app(st: Any, session: dict[str, Any]) -> bool:
    """Matrix cell 1: app-shell minimal_wake_repro (Case A control)."""
    if not delivery_diag_active(st, session) or delivery_matrix_cell(st) != 1:
        return False

    from minimal_component_wake_repro_core import (
        COMPONENT_NAME,
        REQUIRED_CYCLES,
        render_one_cycle,
    )

    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "case": "A",
        "matrix_cell": 1,
        "component_name": "minimal_wake_repro",
        "mount_location": "streamlit_app_top",
        "registration": "minimal_component_wake_repro_core.render_one_cycle",
        "rerun_count": bump_delivery_rerun(session),
    }

    def _record(stage: str, fields: dict[str, Any]) -> None:
        note_delivery_stage(session, stage, **fields)

    render_parent_postmessage_listener(st)
    result = render_one_cycle(st, session, record_stage=_record)

    if result.passed_all:
        st.success(
            f"Solo delivery diag Case A — PASS ({REQUIRED_CYCLES}/{REQUIRED_CYCLES} tokens delivered)"
        )
        if result.callbacks:
            st.dataframe(result.callbacks, use_container_width=True)
        render_case_a_app_shell_probe(st, session, result=result, passed=True)
        return True

    st.caption(
        f"Solo delivery diag Case A — app shell minimal repro "
        f"({result.cycles_done}/{REQUIRED_CYCLES} deliveries, key `{result.widget_key}`)"
    )
    render_case_a_app_shell_probe(st, session, result=result, passed=False)
    if result.should_rerun:
        st.rerun()
    return True


def try_delivery_diag_case_a(st: Any, session: dict[str, Any]) -> bool:
    """Legacy entry — Case A is app-shell only (no Solo room)."""
    return try_delivery_diag_case_a_app(st, session)


def _solo_route_matrix_early_ok(st: Any, session: dict[str, Any]) -> bool:
    """Matrix cells 3–4 mount on Live Draft Room entry (setup or in-progress), then st.stop()."""
    if not delivery_diag_active(st, session):
        return False
    return delivery_matrix_cell(st) in (3, 4)


def _solo_route_room_ok(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    if _solo_route_matrix_early_ok(st, session):
        return True
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        return bool(is_solo_live_draft(session, room))
    except ImportError:
        return True


def try_delivery_diag_app_shell_solo_wake(st: Any, session: dict[str, Any]) -> bool:
    """Matrix cell 2: app shell + solo_countdown_wake, four 5s cycles."""
    if not delivery_diag_active(st, session) or delivery_matrix_cell(st) != 2:
        return False
    from solo_countdown_wake_matrix_core import COMPONENT_NAME, REQUIRED_CYCLES, render_one_cycle

    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "case": "M2",
        "matrix_cell": 2,
        "component_name": COMPONENT_NAME,
        "mount_location": "streamlit_app_top",
        "registration": "solo_countdown_wake_matrix_core.render_one_cycle",
        "rerun_count": bump_delivery_rerun(session),
    }

    def _record(stage: str, fields: dict[str, Any]) -> None:
        note_delivery_stage(session, stage, **fields)

    render_parent_postmessage_listener(st)
    result = render_one_cycle(st, session, route=False, record_stage=_record)
    passed = result.passed_all
    if passed:
        st.success(f"Matrix cell 2 — PASS ({REQUIRED_CYCLES}/{REQUIRED_CYCLES})")
    else:
        st.caption(f"Matrix cell 2 — app shell solo_countdown_wake ({result.cycles_done}/{REQUIRED_CYCLES})")
    render_matrix_probe(
        st,
        session,
        matrix_cell=2,
        component_name=COMPONENT_NAME,
        result=result,
        passed=passed,
        case_label="M2",
    )
    if result.should_rerun:
        st.rerun()
    return True


def try_delivery_diag_app_shell_matrix(st: Any, session: dict[str, Any]) -> bool:
    cell = delivery_matrix_cell(st)
    if not delivery_diag_active(st, session):
        return False
    if cell == 1:
        return try_delivery_diag_case_a_app(st, session)
    if cell == 2:
        return try_delivery_diag_app_shell_solo_wake(st, session)
    return False


def try_delivery_diag_solo_route_minimal(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Matrix cell 3: Solo route early mount + minimal_wake_repro, four cycles."""
    if not delivery_diag_active(st, session) or delivery_matrix_cell(st) != 3:
        return False
    if not _solo_route_room_ok(st, session, room):
        return False
    from minimal_component_wake_repro_core import COMPONENT_NAME, REQUIRED_CYCLES, render_one_cycle

    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "case": "M3",
        "matrix_cell": 3,
        "component_name": COMPONENT_NAME,
        "mount_location": "solo_route_before_heavy_ui",
        "registration": "minimal_component_wake_repro_core.render_one_cycle",
        "rerun_count": bump_delivery_rerun(session),
    }

    def _record(stage: str, fields: dict[str, Any]) -> None:
        note_delivery_stage(session, stage, **fields)

    render_parent_postmessage_listener(st)
    result = render_one_cycle(st, session, record_stage=_record)
    passed = result.passed_all
    if passed:
        st.success(f"Matrix cell 3 — PASS ({REQUIRED_CYCLES}/{REQUIRED_CYCLES})")
    else:
        st.caption(f"Matrix cell 3 — Solo route minimal ({result.cycles_done}/{REQUIRED_CYCLES})")
    render_matrix_probe(
        st,
        session,
        matrix_cell=3,
        component_name=COMPONENT_NAME,
        result=result,
        passed=passed,
        case_label="M3",
    )
    if result.should_rerun:
        st.rerun()
    return True


def try_delivery_diag_solo_route_solo_wake(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Matrix cell 4: Solo route early mount + solo_countdown_wake, four cycles."""
    if not delivery_diag_active(st, session) or delivery_matrix_cell(st) != 4:
        return False
    if not _solo_route_room_ok(st, session, room):
        return False
    from solo_countdown_wake_matrix_core import COMPONENT_NAME, REQUIRED_CYCLES, render_one_cycle

    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "case": "M4",
        "matrix_cell": 4,
        "component_name": COMPONENT_NAME,
        "mount_location": "solo_route_before_heavy_ui",
        "registration": "solo_countdown_wake_matrix_core.render_one_cycle",
        "rerun_count": bump_delivery_rerun(session),
    }

    def _record(stage: str, fields: dict[str, Any]) -> None:
        note_delivery_stage(session, stage, **fields)

    render_parent_postmessage_listener(st)
    result = render_one_cycle(st, session, route=True, record_stage=_record)
    passed = result.passed_all
    if passed:
        st.success(f"Matrix cell 4 — PASS ({REQUIRED_CYCLES}/{REQUIRED_CYCLES})")
    else:
        st.caption(f"Matrix cell 4 — Solo route solo_countdown_wake ({result.cycles_done}/{REQUIRED_CYCLES})")
    render_matrix_probe(
        st,
        session,
        matrix_cell=4,
        component_name=COMPONENT_NAME,
        result=result,
        passed=passed,
        case_label="M4",
    )
    if result.should_rerun:
        st.rerun()
    return True


def try_delivery_diag_solo_route_matrix(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    cell = delivery_matrix_cell(st)
    if cell == 3:
        return try_delivery_diag_solo_route_minimal(st, session, room)
    if cell == 4:
        return try_delivery_diag_solo_route_solo_wake(st, session, room)
    return False


def try_delivery_diag_case_b(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    if delivery_matrix_cell(st) == 4:
        return try_delivery_diag_solo_route_solo_wake(st, session, room)
    if not delivery_diag_active(st, session) or delivery_case(st) != "B":
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return False
    except ImportError:
        return False
    _mount_direct_component(
        st,
        session,
        room,
        case="B",
        registration="live_draft_solo_delivery_diag.case_b_pre_ui",
        location="solo_route_before_heavy_ui",
    )
    st.caption("Solo delivery diag Case B — pre-UI mount, page truncated.")
    return True


def try_delivery_diag_mount_cd(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    if not delivery_diag_active(st, session):
        return False
    try:
        from live_draft_solo_placement_micro import micro_blocks_placement_ladder

        if micro_blocks_placement_ladder(session):
            return False
    except ImportError:
        pass
    try:
        from live_draft_solo_placement_ladder import placement_ladder_active

        if placement_ladder_active(st, session):
            return False
    except ImportError:
        pass
    case = delivery_case(st)
    if case not in ("C", "D"):
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft
        from live_draft_solo_expire_chain import solo_expire_owner

        if not is_solo_live_draft(session, room):
            return False
        if solo_expire_owner(session) != "wake":
            note_delivery_stage(session, "mount_skipped", reason="owner_not_wake", owner=solo_expire_owner(session))
            return False
    except ImportError:
        return False
    if str(room.get("status") or "") != "in_progress":
        return False

    if case == "C":
        _mount_direct_component(
            st,
            session,
            room,
            case="C",
            registration="live_draft_solo_delivery_diag.case_c_direct",
            location="production_timer_slot_direct",
        )
        return True

    key = widget_key_for_room(room)
    _record_mount_meta(
        session,
        case="D",
        key=key,
        registration="live_draft_solo_heartbeat.render_solo_countdown_wake_component",
        location="production_timer_slot_wrapper",
    )
    render_parent_postmessage_listener(st)
    from live_draft_solo_heartbeat import render_solo_expire_owner

    render_solo_expire_owner(st, session, room)
    note_delivery_stage(session, "component_mounted", case="D", key=key, mounted=True)
    render_delivery_probe(st, session, case="D", key=key)
    return True


def note_pick_committed_if_diag(session: dict[str, Any], *, source: str = "") -> None:
    if not session.get("_solo_delivery_diag_enabled") and not session.get(SOLO_DELIVERY_LOG_KEY):
        return
    if delivery_diag_active(None, session) or session.get(SOLO_DELIVERY_LOG_KEY):
        note_delivery_stage(session, "pick_committed", source=source)


def enable_delivery_diag_from_query(st: Any, session: dict[str, Any]) -> None:
    if _qp_flag(st, "solo_delivery_diag"):
        session["_solo_delivery_diag_enabled"] = True
    try:
        from live_draft_solo_placement_ladder import enable_placement_ladder_from_query

        enable_placement_ladder_from_query(st, session)
    except ImportError:
        pass
    try:
        from live_draft_solo_placement_micro import enable_micro_isolation_from_query

        enable_micro_isolation_from_query(st, session)
    except ImportError:
        pass
    try:
        from live_draft_solo_early_bridge_diag import enable_early_bridge_from_query

        enable_early_bridge_from_query(st, session)
    except ImportError:
        pass
    if _qp_flag(st, "solo_delivery_diag") or bool(_qp_get(st, "solo_bridge_transition").strip()):
        try:
            from live_draft_solo_bridge_transition_diag import enable_bridge_transition_from_query

            enable_bridge_transition_from_query(st, session)
        except ImportError:
            pass
    try:
        from live_draft_room_mutation_audit import enable_room_mutation_audit

        if session.get("_solo_delivery_diag_enabled") or session.get("_solo_bridge_transition_enabled"):
            enable_room_mutation_audit(session)
    except ImportError:
        pass
    try:
        from live_draft_callback_boundary_diag import enable_callback_boundary_diag

        if session.get("_solo_delivery_diag_enabled") or session.get("_solo_bridge_transition_enabled"):
            enable_callback_boundary_diag(session)
    except ImportError:
        pass
    try:
        from live_draft_key_ownership_diag import enable_key_ownership_diag

        if session.get("_solo_delivery_diag_enabled") or session.get("_solo_bridge_transition_enabled"):
            enable_key_ownership_diag(session)
    except ImportError:
        pass
    try:
        from live_draft_paired_transition_diag import enable_paired_transition_diag

        if session.get("_solo_delivery_diag_enabled") or session.get("_solo_bridge_transition_enabled"):
            enable_paired_transition_diag(session)
    except ImportError:
        pass
    try:
        from live_draft_solo_component_diagnostics import bootstrap_solo_component_diag

        bootstrap_solo_component_diag(st, session)
    except ImportError:
        pass
