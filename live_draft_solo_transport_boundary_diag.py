"""Stage 1A transport boundary — iframe postMessage → Python on_change (diag-gated)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

TRANSPORT_LOG_KEY = "_solo_transport_boundary_log"
TRANSPORT_META_KEY = "_solo_transport_boundary_meta"
TRANSPORT_SCRIPT_RUN_KEY = "_solo_transport_script_run_counter"
TRANSPORT_SEND_TS_KEY = "_solo_transport_client_send_ts"
TRANSPORT_PROBE_ID = "solo-transport-boundary-diag"
MINIMAL_WIDGET_KEY = "solo_countdown_wake_transport_minimal"
PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
MINIMAL_CALLBACK_FLAG = "_solo_transport_minimal_callback_registered"
PRODUCTION_CALLBACK_FLAG = "_solo_transport_production_callback_registered"
PARENT_LS_KEY = "solo_transport_parent_log"
IFRAME_TRANSPORT_LS_KEY = "solo_transport_iframe_log"


def transport_boundary_active(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return solo_component_diag_enabled(st, session)
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def bump_transport_script_run(session: dict[str, Any]) -> int:
    n = int(session.get(TRANSPORT_SCRIPT_RUN_KEY) or 0) + 1
    session[TRANSPORT_SCRIPT_RUN_KEY] = n
    return n


def _append_log(session: dict[str, Any], stage: str, **fields: Any) -> None:
    row = {"ts": time.time(), "stage": stage, **fields}
    log = list(session.get(TRANSPORT_LOG_KEY) or [])
    log.append(row)
    session[TRANSPORT_LOG_KEY] = log[-200:]


def build_minimal_control_token(production_token: str) -> str:
    parts = str(production_token or "").strip().split("|")
    if len(parts) == 3:
        return f"{parts[0]}|minimal|{parts[2]}"
    return f"minimal|0|{time.time():.3f}"


def _streamlit_session_id(st: Any) -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is not None:
            return str(getattr(ctx, "session_id", "") or "")[:80]
    except Exception:
        pass
    return ""


def build_minimal_vs_production_wiring_comparison() -> dict[str, Any]:
    """Line-level comparison: passing minimal_wake_repro vs production solo_countdown mount."""
    from pathlib import Path

    from minimal_component_wake_repro_core import COMPONENT_NAME as MIN_NAME

    prod_path = Path(__file__).resolve().parent / "solo_countdown_component" / "frontend"
    min_path = Path(__file__).resolve().parent / "minimal_wake_repro_component" / "frontend"
    return {
        "minimal_control_is_exact_passing_repro": True,
        "comparison": {
            "component_declaration_function": {
                "production": "solo_countdown_component.declare_component(solo_countdown_wake)",
                "minimal": f"minimal_component_wake_repro_core.declare_component({MIN_NAME})",
                "match": False,
            },
            "component_build_frontend": {
                "production": str(prod_path),
                "minimal": str(min_path),
                "match": False,
            },
            "python_key": {
                "production": PRODUCTION_WIDGET_KEY,
                "minimal": MINIMAL_WIDGET_KEY,
                "match": False,
            },
            "default": {"production": "None", "minimal": "None", "match": True},
            "returned_value": {
                "production": "solo_countdown _COMPONENT(...) return bound in record_production_component_declaration",
                "minimal": "minimal_wake_repro _COMPONENT(...) return (same Streamlit pattern)",
                "match": True,
            },
            "on_change_registration": {
                "production": "_production_deliver_callback via render_micro_isolation_once(deliver_callback=...)",
                "minimal": "mount_single_for_transport on_change=_minimal_on_change",
                "match": False,
            },
            "on_change_arguments": {
                "production": "reads st.session_state[production_key] inside deliver + audit",
                "minimal": "reads st.session_state[MINIMAL_WIDGET_KEY] in record_minimal_control_delivery",
                "match": True,
            },
            "render_location": {
                "production": "ldr_page_entry_early_persistent (try_solo_persistent_wake_ldr_entry)",
                "minimal": "same function immediately after production mount (transport_boundary_active)",
                "match": True,
            },
        },
        "note": (
            "Minimal control uses minimal_wake_repro component/frontend, not solo_countdown with a different token."
        ),
    }


def record_transport_post_send_snapshot(
    st: Any,
    session: dict[str, Any],
    *,
    production_key: str,
    expected_production_token: str,
    expected_minimal_token: str,
) -> None:
    """Earliest Python observation after client send — full widget/callback snapshot."""
    if not transport_boundary_active(st, session):
        return
    meta = dict(session.get(TRANSPORT_META_KEY) or {})
    if meta.get("post_send_snapshot_recorded"):
        return
    send_ts = float(meta.get("client_send_ts") or session.get(TRANSPORT_SEND_TS_KEY) or 0)
    prod_raw_s = str(prod_raw or "").strip()
    exp_prod = str(expected_production_token or "").strip()
    after_send = bool(send_ts and time.time() >= send_ts) or bool(exp_prod and prod_raw_s == exp_prod)
    exp_min = str(expected_minimal_token or "").strip()
    min_raw_s = str(min_raw or "").strip()
    if exp_min and min_raw_s == exp_min:
        after_send = True
    if not after_send:
        return
    run_n = bump_transport_script_run(session)
    prod_exists = production_key in st.session_state
    min_exists = MINIMAL_WIDGET_KEY in st.session_state
    prod_raw = st.session_state.get(production_key) if prod_exists else None
    min_raw = st.session_state.get(MINIMAL_WIDGET_KEY) if min_exists else None
    _append_log(
        session,
        "python_post_send_snapshot",
        script_run=run_n,
        streamlit_session_id=_streamlit_session_id(st),
        production_key=production_key,
        production_key_exists=prod_exists,
        production_raw_value=str(prod_raw or "")[:400],
        minimal_key=MINIMAL_WIDGET_KEY,
        minimal_key_exists=min_exists,
        minimal_raw_value=str(min_raw or "")[:400],
        production_component_return=str(prod_raw or "")[:400],
        minimal_component_return=str(min_raw or "")[:400],
        production_callback_registered=bool(session.get(PRODUCTION_CALLBACK_FLAG)),
        minimal_callback_registered=bool(session.get(MINIMAL_CALLBACK_FLAG)),
        production_callback_count=int(session.get(f"{PRODUCTION_CALLBACK_FLAG}_count") or 0),
        minimal_callback_count=int(session.get(f"{MINIMAL_CALLBACK_FLAG}_count") or 0),
        expected_production_token=str(expected_production_token or "")[:400],
        expected_minimal_token=str(expected_minimal_token or "")[:400],
        wiring_comparison=build_minimal_vs_production_wiring_comparison(),
    )
    meta["post_send_snapshot_recorded"] = True
    meta["first_post_send_run"] = run_n
    meta["first_post_send_raw"] = str(prod_raw or "")[:400]
    session[TRANSPORT_META_KEY] = meta


def record_transport_python_run(
    st: Any,
    session: dict[str, Any],
    *,
    production_key: str,
    expected_token: str,
    phase: str,
    on_change_registered: bool = True,
    expected_minimal_token: str = "",
) -> None:
    if not transport_boundary_active(st, session):
        return
    run_n = bump_transport_script_run(session)
    key_exists = production_key in st.session_state
    raw = st.session_state.get(production_key) if key_exists else None
    raw_s = str(raw or "").strip()
    expected = str(expected_token or "").strip()
    min_exists = MINIMAL_WIDGET_KEY in st.session_state
    min_raw = st.session_state.get(MINIMAL_WIDGET_KEY) if min_exists else None
    meta = dict(session.get(TRANSPORT_META_KEY) or {})
    send_ts = float(meta.get("client_send_ts") or session.get(TRANSPORT_SEND_TS_KEY) or 0)
    after_send = bool(send_ts and time.time() >= send_ts) or bool(expected and raw_s == expected)
    min_expected = str(
        expected_minimal_token
        or meta.get("minimal_token")
        or session.get(f"{TRANSPORT_META_KEY}_minimal_token")
        or ""
    ).strip()
    min_raw_s = str(min_raw or "").strip()
    if min_expected and min_raw_s == min_expected:
        after_send = True
    if after_send:
        record_transport_post_send_snapshot(
            st,
            session,
            production_key=production_key,
            expected_production_token=expected,
            expected_minimal_token=expected_minimal_token
            or str(meta.get("minimal_token") or session.get(f"{TRANSPORT_META_KEY}_minimal_token") or ""),
        )
    _append_log(
        session,
        "python_run_entry",
        script_run=run_n,
        phase=phase,
        streamlit_session_id=_streamlit_session_id(st),
        widget_key=production_key,
        key_in_session_state=key_exists,
        raw_value=raw_s[:400],
        expected_token=expected[:400],
        raw_equals_expected=bool(expected and raw_s == expected),
        default_equals_expected=bool(expected and raw_s == expected and key_exists),
        on_change_registered=on_change_registered,
        minimal_key=MINIMAL_WIDGET_KEY,
        minimal_key_in_session_state=min_exists,
        minimal_raw_value=str(min_raw or "")[:400],
        production_callback_registered=bool(session.get(PRODUCTION_CALLBACK_FLAG)),
        minimal_callback_registered=bool(session.get(MINIMAL_CALLBACK_FLAG)),
        after_client_send=after_send,
        send_to_run_ms=int((time.time() - send_ts) * 1000) if send_ts and after_send else None,
    )
    if after_send and not meta.get("first_post_send_run"):
        meta["first_post_send_run"] = run_n
        meta["first_post_send_raw"] = raw_s[:400]
        session[TRANSPORT_META_KEY] = meta


def record_production_component_declaration(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    expire_token: str,
    actionable: bool,
    component_return: Any,
    default_value: Any = None,
    mount_location: str,
) -> None:
    if not transport_boundary_active(st, session):
        return
    expected = str(expire_token or "").strip()
    pre_raw = st.session_state.get(widget_key) if widget_key in st.session_state else None
    ret_s = str(component_return or "").strip()
    _append_log(
        session,
        "production_component_declaration",
        widget_key=widget_key,
        expire_token_arg=expected[:400],
        actionable=actionable,
        default_value=repr(default_value)[:200],
        component_return=ret_s[:400],
        session_state_before_mount=repr(pre_raw)[:400],
        default_already_equals_token=bool(expected and str(pre_raw or "").strip() == expected),
        widget_already_had_token=bool(pre_raw),
        mount_location=mount_location,
    )


def record_minimal_control_delivery(session: dict[str, Any], *, raw: Any, token: str) -> None:
    if not transport_boundary_active(None, session):
        return
    meta = dict(session.get(TRANSPORT_META_KEY) or {})
    meta["minimal_on_change_fired"] = True
    meta["minimal_raw"] = str(raw or "")[:400]
    session[TRANSPORT_META_KEY] = meta
    _append_log(
        session,
        "minimal_control_on_change",
        widget_key=MINIMAL_WIDGET_KEY,
        raw_value=str(raw or "")[:400],
        expected_token=str(token or "")[:400],
    )


def mount_transport_minimal_control(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    production_expire_token: str,
    chain_persist_key: str,
) -> None:
    if not transport_boundary_active(st, session):
        return
    from minimal_component_wake_repro_core import mount_single_for_transport

    minimal_token = build_minimal_control_token(production_expire_token)
    session_key = f"{TRANSPORT_META_KEY}_minimal_token"
    session[session_key] = minimal_token
    meta = dict(session.get(TRANSPORT_META_KEY) or {})
    meta["minimal_token"] = minimal_token
    session[TRANSPORT_META_KEY] = meta

    def _minimal_on_change() -> None:
        session[f"{MINIMAL_CALLBACK_FLAG}_count"] = int(session.get(f"{MINIMAL_CALLBACK_FLAG}_count") or 0) + 1
        raw = st.session_state.get(MINIMAL_WIDGET_KEY)
        record_minimal_control_delivery(session, raw=raw, token=minimal_token)

    if not session.get(f"{MINIMAL_WIDGET_KEY}_mounted"):
        mount_single_for_transport(
            st,
            widget_key=MINIMAL_WIDGET_KEY,
            expire_token=minimal_token,
            on_change=_minimal_on_change,
        )
        session[f"{MINIMAL_WIDGET_KEY}_mounted"] = True
        session[MINIMAL_CALLBACK_FLAG] = True
        _append_log(
            session,
            "minimal_control_mounted",
            widget_key=MINIMAL_WIDGET_KEY,
            expire_token=minimal_token[:400],
            component_name="minimal_wake_repro",
            wiring_comparison=build_minimal_vs_production_wiring_comparison(),
        )


def render_transport_parent_listener(st: Any) -> None:
    """Capture-phase listener only; does not block Streamlit's handler."""
    import streamlit.components.v1 as components

    components.html(
        f"""<!DOCTYPE html><html><body><script>
        (function(){{
          var LS_KEY = "{PARENT_LS_KEY}";
          function persist(stage, extra) {{
            try {{
              var log = [];
              try {{ log = JSON.parse(localStorage.getItem(LS_KEY) || "[]"); }} catch(e) {{}}
              if (!Array.isArray(log)) log = [];
              log.push({{ ts: Date.now(), stage: stage, extra: String(extra||"").slice(0,1900) }});
              localStorage.setItem(LS_KEY, JSON.stringify(log.slice(-200)));
            }} catch(e) {{}}
            try {{
              var el = document.getElementById("{TRANSPORT_PROBE_ID}-parent");
              if (!el) return;
              var chain = el.getAttribute("data-chain") || "";
              el.setAttribute("data-last", stage);
              el.setAttribute("data-chain", chain ? chain + "|" + stage : stage);
              if (extra) el.setAttribute("data-extra", String(extra).slice(0,2000));
            }} catch(e2) {{}}
          }}
          function iframeHint(ev) {{
            try {{
              if (!ev || !ev.source) return "";
              var iframes = document.querySelectorAll("iframe");
              for (var i = 0; i < iframes.length; i++) {{
                try {{ if (iframes[i].contentWindow === ev.source) return "iframe_index=" + i; }} catch(e) {{}}
              }}
              return "source_not_enumerated";
            }} catch(e) {{ return ""; }}
          }}
          function onMsg(ev) {{
            var d = ev && ev.data;
            if (!d || !d.isStreamlitMessage) return;
            if (d.type !== "streamlit:setComponentValue") return;
            var val = d.value;
            var payload = JSON.stringify({{
              type: d.type,
              value: typeof val === "string" ? val.slice(0,400) : val,
              origin: String(ev.origin || ""),
              iframe: iframeHint(ev),
              ignored: false
            }});
            persist("parent_streamlit_setComponentValue", payload);
          }}
          window.addEventListener("message", onMsg, true);
          persist("transport_parent_listener_installed", String(window.location.pathname||""));
        }})();
        </script><div id="{TRANSPORT_PROBE_ID}-parent" data-chain="" data-last=""></div></body></html>""",
        height=0,
    )


def ingest_client_transport_hints(session: dict[str, Any], *, send_ts_ms: int | None) -> None:
    if send_ts_ms:
        session[TRANSPORT_SEND_TS_KEY] = float(send_ts_ms) / 1000.0
        meta = dict(session.get(TRANSPORT_META_KEY) or {})
        meta["client_send_ts"] = float(send_ts_ms) / 1000.0
        session[TRANSPORT_META_KEY] = meta


def transport_summary(session: dict[str, Any]) -> dict[str, Any]:
    log = list(session.get(TRANSPORT_LOG_KEY) or [])
    meta = dict(session.get(TRANSPORT_META_KEY) or {})
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    return {
        "script_run_counter": int(session.get(TRANSPORT_SCRIPT_RUN_KEY) or 0),
        "meta": meta,
        "stages": stages[-80:],
        "log_tail": log[-40:],
        "minimal_on_change": bool(meta.get("minimal_on_change_fired")),
        "wiring_comparison": build_minimal_vs_production_wiring_comparison(),
    }


def classify_transport_stage(
    *,
    iframe_entries: list[dict[str, Any]],
    parent_entries: list[dict[str, Any]],
    transport_log: list[dict[str, Any]],
    callback_count: int,
    iframe_has_component_sent: bool,
    send_ts_ms: int | None = None,
    immediate_parent_messages: list[dict[str, Any]] | None = None,
) -> str:
    iframe_stages = {str(e.get("stage") or "") for e in iframe_entries if isinstance(e, dict)}
    parent_stages = {str(e.get("stage") or "") for e in parent_entries if isinstance(e, dict)}

    posted = "transport_postmessage_invoked" in iframe_stages or iframe_has_component_sent
    if not posted:
        return "A"

    immediate_has_set = False
    if immediate_parent_messages is not None:
        immediate_has_set = any(
            isinstance(m, dict) and m.get("has_set_component_value") for m in immediate_parent_messages
        )
        if not immediate_has_set:
            return "B"
    elif "parent_streamlit_setComponentValue" not in parent_stages:
        return ""

    legacy_parent_heard = "parent_streamlit_setComponentValue" in parent_stages
    if immediate_parent_messages is not None and immediate_has_set and not legacy_parent_heard:
        pass

    post_send = [
        r
        for r in transport_log
        if isinstance(r, dict)
        and r.get("stage") in ("python_run_entry", "python_post_send_snapshot")
        and (r.get("after_client_send") or r.get("stage") == "python_post_send_snapshot" or (send_ts_ms and int(float(r.get("ts") or 0) * 1000) >= int(send_ts_ms) - 200))
    ]
    if iframe_has_component_sent and not post_send:
        return "C"

    if post_send and not any(r.get("key_in_session_state") or r.get("production_key_exists") for r in post_send):
        return "D"

    if callback_count == 0:
        minimal = any(
            isinstance(r, dict) and r.get("stage") == "minimal_control_on_change" for r in transport_log
        )
        if minimal:
            return "E"
        if post_send and any(str(r.get("raw_value") or r.get("production_raw_value") or "").strip() for r in post_send):
            return "E"
        if iframe_has_component_sent:
            return "E"
        return "E"

    return ""


def render_transport_boundary_probe(st: Any, session: dict[str, Any]) -> None:
    if not transport_boundary_active(st, session):
        return
    summary = transport_summary(session)
    payload = json.dumps(summary, default=str)[:14000]
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    run_n = int(session.get(TRANSPORT_SCRIPT_RUN_KEY) or 0)
    st.markdown(
        f'<div id="{TRANSPORT_PROBE_ID}" '
        f'data-script-run="{run_n}" '
        f'data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )
