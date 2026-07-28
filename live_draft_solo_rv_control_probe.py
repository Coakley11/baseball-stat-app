"""Native Streamlit RV control ledger (diag-only) — no HTML/localStorage probe."""

from __future__ import annotations

import base64
import html
import json
import time
from typing import Any, Callable

RV_LEDGERS_BY_RUN_KEY = "solo_rv_control_ledgers_v1"
RV_SCRIPT_RUN_SEQ_KEY = "_solo_rv_control_script_run_seq"
RV_LEDGER_B64_PREFIX = "SOLO_RV_CONTROL_LEDGER_B64:"
MAX_LEDGER_ROWS = 200


def _qp_run_id(st: Any, session: dict[str, Any]) -> str:
    rid = str(session.get("_solo_rv_run_id") or "").strip()
    if rid:
        return rid
    try:
        from live_draft_solo_rv_binding_ladder import RV_RUN_ID_QP, _qp_get

        return str(_qp_get(st, RV_RUN_ID_QP) or "").strip()
    except ImportError:
        return ""


def rv_control_probe_active(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_rv_binding_ladder import rv_ladder_requested

        return rv_ladder_requested(st, session)
    except ImportError:
        return bool(session.get("_solo_rv_ladder_step"))


def _streamlit_session_id(st: Any | None) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(st.session_state if hasattr(st, "session_state") else {}) or "")
    except ImportError:
        pass
    try:
        return str(getattr(st, "session_state", {}).get("_live_draft_script_run_id") or "")
    except Exception:
        return ""


def _next_script_run_seq(session: dict[str, Any]) -> int:
    n = int(session.get(RV_SCRIPT_RUN_SEQ_KEY) or 0) + 1
    session[RV_SCRIPT_RUN_SEQ_KEY] = n
    return n


def _ledger_for_run(session: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    if not run_id:
        return []
    store = dict(session.get(RV_LEDGERS_BY_RUN_KEY) or {})
    return list(store.get(run_id) or [])


def _persist_ledger(session: dict[str, Any], run_id: str, rows: list[dict[str, Any]]) -> None:
    store = dict(session.get(RV_LEDGERS_BY_RUN_KEY) or {})
    store[run_id] = rows[-MAX_LEDGER_ROWS:]
    session[RV_LEDGERS_BY_RUN_KEY] = store


def build_control_probe_payload(session: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "step": str(session.get("_solo_rv_ladder_step") or ""),
        "script_run_seq": int(session.get(RV_SCRIPT_RUN_SEQ_KEY) or 0),
        "rows": _ledger_for_run(session, run_id),
    }


def encode_control_probe_payload(payload: dict[str, Any]) -> str:
    """Full ledger JSON → base64 (never truncate — 48k cap caused invalid PROBE_DECODE_FAILED on Cloud)."""
    raw = json.dumps(payload, default=str, separators=(",", ":"))
    return RV_LEDGER_B64_PREFIX + base64.b64encode(raw.encode("utf-8")).decode("ascii")


_B64_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


def _b64_after_prefix(raw: str, idx: int) -> str:
    tail = raw[idx + len(RV_LEDGER_B64_PREFIX) :]
    chars: list[str] = []
    i = 0
    while i < len(tail):
        rest = tail[i:]
        stripped = rest.lstrip()
        if stripped.startswith(RV_LEDGER_B64_PREFIX):
            break
        ch = tail[i]
        if ch in _B64_ALPHABET:
            chars.append(ch)
        elif ch.isspace():
            pass
        else:
            break
        i += 1
    return "".join(chars)


def extract_ledger_b64_payload(text: str) -> tuple[str, str]:
    """Extract base64 after the last prefix (newest st.code render wins)."""
    raw = html.unescape(str(text or ""))
    best_b64 = ""
    best_idx = -1
    start = 0
    while start < len(raw):
        idx = raw.find(RV_LEDGER_B64_PREFIX, start)
        if idx < 0:
            break
        b64 = _b64_after_prefix(raw, idx)
        best_b64 = b64
        best_idx = idx
        start = idx + len(RV_LEDGER_B64_PREFIX)
    if best_idx < 0:
        return "", ""
    snippet_end = best_idx + len(RV_LEDGER_B64_PREFIX) + min(len(best_b64), 240)
    snippet = raw[best_idx:snippet_end]
    return best_b64, snippet


def playwright_ledger_scrape_script() -> str:
    """JS body: return page text preferring longest st.code block that contains the ledger prefix."""
    prefix = RV_LEDGER_B64_PREFIX
    return f"""() => {{
      const prefix = {json.dumps(prefix)};
      function extractB64(t) {{
        let lastIdx = t.lastIndexOf(prefix);
        if (lastIdx < 0) return '';
        let tail = t.slice(lastIdx + prefix.length);
        let b64 = '';
        const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
        for (let i = 0; i < tail.length; i++) {{
          const rest = tail.slice(i).replace(/^\\s+/, '');
          if (rest.startsWith(prefix)) break;
          const ch = tail[i];
          if (alphabet.includes(ch)) b64 += ch;
          else if (/\\s/.test(ch)) continue;
          else break;
        }}
        return b64;
      }}
      let best = '';
      let bestEl = null;
      const roots = [document];
      for (const f of document.querySelectorAll('iframe')) {{
        try {{ if (f.contentDocument) roots.push(f.contentDocument); }} catch (e) {{}}
      }}
      for (const root of roots) {{
        if (!root) continue;
        for (const el of root.querySelectorAll('[data-testid="stCodeBlock"] pre, pre, code')) {{
          const t = el.textContent || '';
          if (!t.includes(prefix)) continue;
          bestEl = el;
        }}
      }}
      if (bestEl) {{
        const b64 = extractB64(bestEl.textContent || '');
        if (b64.length) return prefix + b64;
      }}
      try {{
        if (window.__soloRvLedgerB64 && String(window.__soloRvLedgerB64).includes(prefix)) {{
          return String(window.__soloRvLedgerB64);
        }}
      }} catch (e) {{}}
      let t = document.body ? document.body.innerText : '';
      for (const f of document.querySelectorAll('iframe')) {{
        try {{
          if (f.contentDocument && f.contentDocument.body) {{
            t += '\\n' + f.contentDocument.body.innerText;
          }}
        }} catch (e) {{}}
      }}
      return t;
    }}"""


def _decode_b64_json_payload(b64: str) -> dict[str, Any]:
    """Decode base64 JSON; trim trailing junk characters if innerText picked up extras."""
    cleaned = "".join(ch for ch in b64 if ch in _B64_ALPHABET)
    last_err: Exception | None = None
    for trim in range(0, min(len(cleaned), 8)):
        candidate = cleaned[: len(cleaned) - trim] if trim else cleaned
        if not candidate:
            continue
        pad = candidate + "=" * ((4 - len(candidate) % 4) % 4)
        try:
            decoded = json.loads(base64.b64decode(pad).decode("utf-8"))
        except Exception as exc:
            last_err = exc
            continue
        if isinstance(decoded, dict):
            return decoded
    if last_err:
        raise last_err
    raise ValueError("empty_b64")


def decode_control_probe_text_with_meta(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode ledger from page text; meta includes decode_error and matched snippet."""
    meta: dict[str, Any] = {
        "decode_ok": False,
        "decode_error": "",
        "matched_snippet": "",
        "raw_b64_payload": "",
        "raw_b64_len": 0,
        "prefix_found": False,
    }
    if not text:
        meta["decode_error"] = "empty_text"
        return {}, meta
    b64, snippet = extract_ledger_b64_payload(text)
    meta["matched_snippet"] = snippet[:500]
    meta["raw_b64_payload"] = b64[:8000]
    meta["raw_b64_len"] = len(b64)
    meta["prefix_found"] = RV_LEDGER_B64_PREFIX in html.unescape(str(text))
    if not b64:
        meta["decode_error"] = "no_b64_after_prefix" if meta["prefix_found"] else "prefix_missing"
        return {}, meta
    try:
        decoded = _decode_b64_json_payload(b64)
    except Exception as exc:
        meta["decode_error"] = f"PROBE_DECODE_FAILED:{type(exc).__name__}:{exc}"
        return {}, meta
    if not isinstance(decoded, dict):
        meta["decode_error"] = "PROBE_DECODE_FAILED:not_object"
        return {}, meta
    meta["decode_ok"] = True
    return decoded, meta


def decode_control_probe_text(text: str) -> dict[str, Any]:
    payload, meta = decode_control_probe_text_with_meta(text)
    if meta.get("decode_ok"):
        return payload
    return {}


def render_native_control_probe(st: Any, session: dict[str, Any], probe_placeholder: Any) -> None:
    """Render ledger via st.code; mirror payload on window for runner scrape (diag-only)."""
    if probe_placeholder is None:
        return
    run_id = _qp_run_id(st, session)
    payload = build_control_probe_payload(session, run_id)
    line = encode_control_probe_payload(payload)
    probe_placeholder.code(line, language=None)
    try:
        import json as _json

        import streamlit.components.v1 as components

        row_count = len(payload.get("rows") or [])
        components.html(
            f"""<script>
            window.__soloRvLedgerB64 = {_json.dumps(line)};
            window.__soloRvLedgerRowCount = {int(row_count)};
            window.__soloRvLedgerRunId = {_json.dumps(run_id)};
            </script>""",
            height=0,
            width=0,
        )
    except Exception:
        pass
    try:
        store = dict(session.get(RV_LEDGERS_BY_RUN_KEY) or {})
        if run_id:
            session["_solo_rv_control_ledger_export_row_count"] = len(store.get(run_id) or [])
    except Exception:
        pass


def append_control_event(
    st: Any,
    session: dict[str, Any],
    event: str,
    *,
    control_name: str = "",
    widget_key: str = "",
    room: dict[str, Any] | None = None,
    expected_token: str = "",
    component_return: Any = None,
    coalesced_value: str = "",
    callback_mode: str = "on_change=None",
    component_widget_id: str = "",
    browser_send_seen: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = _qp_run_id(st, session)
    if not run_id:
        return {}
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    ss_before = ""
    ss_after = ""
    if widget_key:
        ss_before = repr(session.get(widget_key))[:400] if widget_key in session else "missing"
        ss_after = ss_before
    if browser_send_seen is None:
        browser_send_seen = bool(
            session.get("_solo_rv_browser_delivery_recorded")
            or session.get("_solo_rv_prior_declaration_returned")
        )
    rows = _ledger_for_run(session, run_id)
    event_seq = len(rows) + 1
    decl_num = None
    if event == "declaration_attempt":
        if extra and extra.get("declaration_occurrence_number") is not None:
            decl_num = int(extra.get("declaration_occurrence_number") or 0)
        else:
            decl_num = sum(1 for r in rows if r.get("event") == "declaration_attempt") + 1
    row: dict[str, Any] = {
        "event": event,
        "event_sequence": event_seq,
        "declaration_occurrence_number": decl_num if event == "declaration_attempt" else None,
        "ts": time.time(),
        "streamlit_session_id": _streamlit_session_id(st),
        "script_run_seq": int(session.get(RV_SCRIPT_RUN_SEQ_KEY) or 0),
        "run_id": run_id,
        "control_name": control_name or str(session.get("_solo_rv_ladder_step") or ""),
        "room_id": str(live.get("draft_room_id") or live.get("draft_id") or ""),
        "pick_index": int(live.get("current_pick_index") or 0),
        "deadline": live.get("timer_deadline"),
        "expected_token": (expected_token or str(session.get("_solo_persistent_wake_last_token") or ""))[:400],
        "widget_key": widget_key,
        "session_state_before": ss_before,
        "session_state_after": ss_after,
        "browser_send_seen": browser_send_seen,
        "component_return": repr(component_return)[:400] if component_return is not None else "",
        "coalesced_value": str(coalesced_value or "")[:400],
        "component_widget_id": component_widget_id[:120],
        "callback_mode": callback_mode,
    }
    if extra:
        for key, val in extra.items():
            if key not in row or row.get(key) in ("", None):
                row[key] = val
        row["extra"] = extra
        if extra.get("session_state_after"):
            row["session_state_after"] = str(extra.get("session_state_after") or "")[:400]
        if extra.get("declaration_occurrence_number") is not None and event in (
            "declaration_attempt",
            "declaration_returned",
            "post_delivery_redeclaration",
        ):
            row["declaration_occurrence_number"] = int(extra.get("declaration_occurrence_number") or 0)
    rows.append(row)
    _persist_ledger(session, run_id, rows)
    return row


def rv_ultra_early_probe_hook(st: Any, session: dict[str, Any]) -> None:
    """Latch RV query params only — native probe renders in dedicated entrypoint."""
    if not rv_control_probe_active(st, session):
        return
    try:
        from live_draft_solo_rv_binding_ladder import enable_rv_ladder_session

        enable_rv_ladder_session(st, session)
    except ImportError:
        pass
    _next_script_run_seq(session)


def mount_with_rv_control_declaration(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    widget_key: str,
    mount_fn: Callable[[], Any],
    control_name: str,
    location: str,
    probe_placeholder: Any = None,
) -> Any:
    expected = str(session.get("_solo_persistent_wake_last_token") or session.get("_solo_parity_expected_token") or "")
    if str(session.get("_solo_rv_ladder_step") or control_name or "") == "RV3" or control_name == "RV3":
        from live_draft_solo_rv3_phase import (
            is_rv3_rejected_token,
            mark_rv3_production_declared,
            rv3_declaration_allowed,
            set_rv3_phase,
            RV3_PHASE_POST_DELIVERY,
        )
        from live_draft_solo_rv3_room_continuity import record_rv3_room_checkpoint

        allowed, invalid = rv3_declaration_allowed(
            session, expected_token=expected, location=location
        )
        try:
            from live_draft_solo_rv3_phase import trace_rv3_decl

            trace_rv3_decl(
                st,
                session,
                "mount_with_rv_control_declaration",
                rv3_declaration_allowed=allowed,
                rv3_declaration_invalid=invalid,
                expected_token=str(expected or "")[:120],
                location=location,
            )
        except ImportError:
            pass
        if not allowed:
            append_control_event(
                st,
                session,
                "rv3_premature_component_declaration",
                control_name="RV3",
                widget_key=widget_key,
                room=room,
                expected_token=expected,
                extra={
                    "invalid": invalid,
                    "location": location,
                    "component_type": "blocked",
                },
            )
            render_native_control_probe(st, session, probe_placeholder)
            return None
        if is_rv3_rejected_token(expected):
            try:
                from live_draft_solo_rv3_phase import trace_rv3_decl

                trace_rv3_decl(
                    st,
                    session,
                    "mount_with_rv_control_declaration",
                    exit=False,
                    reason="is_rv3_rejected_token",
                    expected_token=str(expected or "")[:120],
                )
            except ImportError:
                pass
            append_control_event(
                st,
                session,
                "rv3_premature_component_declaration",
                control_name="RV3",
                widget_key=widget_key,
                expected_token=expected,
                extra={"invalid": "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION", "location": location},
            )
            render_native_control_probe(st, session, probe_placeholder)
            return None
        record_rv3_room_checkpoint(st, session, "before_production_declaration", probe_placeholder=probe_placeholder)
        try:
            from live_draft_solo_rv3_phase import trace_rv3_decl

            trace_rv3_decl(st, session, "mount_with_rv_control_declaration", before="declaration_attempt")
        except ImportError:
            pass
    run_id = _qp_run_id(st, session)
    from live_draft_solo_rv_declaration_ledger import (
        browser_send_observed_for_declaration,
        evaluate_post_delivery_proof,
        increment_declaration_occurrence,
        micro_cycle_to_ledger_fields,
        note_browser_send_observed,
    )

    ss_before_decl = repr(session.get(widget_key))[:400] if widget_key in session else "missing"
    occurrence = increment_declaration_occurrence(session, run_id)
    browser_send_seen = browser_send_observed_for_declaration(
        session,
        widget_key=widget_key,
        expected_token=expected,
        ss_before=ss_before_decl,
    )
    append_control_event(
        st,
        session,
        "declaration_attempt",
        control_name=control_name,
        widget_key=widget_key,
        room=room,
        expected_token=expected,
        browser_send_seen=browser_send_seen,
        extra={
            "location": location,
            "placement_label": location,
            "solo_rv_run_id": run_id,
            "declaration_occurrence_number": occurrence,
        },
    )
    if browser_send_seen:
        note_browser_send_observed(session)
    render_native_control_probe(st, session, probe_placeholder)
    raw = mount_fn()
    micro = micro_cycle_to_ledger_fields(raw)
    coerced = str(micro.get("coalesced_value_exact") or micro.get("micro_cycle_component_return") or "").strip()
    if not coerced and raw is not None:
        coerced = raw.strip() if isinstance(raw, str) else str(raw).strip()
    ss_after = repr(session.get(widget_key))[:400] if widget_key in session else "missing"
    if not coerced and ss_after not in ("missing", "None", "''", '""'):
        coerced = ss_after.strip("'\"")
    if micro.get("raw_received"):
        note_browser_send_observed(session)
    proven, proof_source = evaluate_post_delivery_proof(
        expected_token=expected,
        widget_key=widget_key,
        location=location,
        occurrence=occurrence,
        micro=micro,
        ss_after=ss_after,
        coalesced=coerced,
        browser_send_observed=bool(session.get("_solo_rv_browser_send_observed")),
    )
    decl_extra = {
        "location": location,
        "placement_label": location,
        "session_state_after": ss_after,
        "solo_rv_run_id": run_id,
        "declaration_occurrence_number": occurrence,
        "micro_cycle_component_return": micro.get("micro_cycle_component_return"),
        "raw_received": micro.get("raw_received"),
        "delivered": micro.get("delivered"),
        "on_change_fired": micro.get("on_change_fired"),
        "post_delivery_redeclaration_proven": proven,
        "proof_source": proof_source if proven else "",
    }
    append_control_event(
        st,
        session,
        "declaration_returned",
        control_name=control_name,
        widget_key=widget_key,
        room=room,
        expected_token=expected,
        component_return=raw,
        coalesced_value=coerced,
        browser_send_seen=browser_send_seen,
        extra=decl_extra,
    )
    if proven:
        append_control_event(
            st,
            session,
            "post_delivery_redeclaration",
            control_name=control_name,
            widget_key=widget_key,
            room=room,
            expected_token=expected,
            component_return=raw,
            coalesced_value=coerced,
            browser_send_seen=True,
            extra={
                **decl_extra,
                "proof_source": proof_source,
                "post_delivery_redeclaration_proven": True,
            },
        )
        session["_solo_rv_post_delivery_redeclaration_proven"] = True
    elif not session.get("_solo_rv_prior_declaration_returned"):
        session["_solo_rv_prior_declaration_returned"] = True
    if str(session.get("_solo_rv_ladder_step") or control_name or "") == "RV3" or control_name == "RV3":
        from live_draft_solo_rv3_phase import mark_rv3_production_declared, set_rv3_phase, RV3_PHASE_POST_DELIVERY
        from live_draft_solo_rv3_room_continuity import record_rv3_room_checkpoint

        mark_rv3_production_declared(session)
        record_rv3_room_checkpoint(st, session, "after_component_return_processing", probe_placeholder=probe_placeholder)
        if proven or session.get("_solo_rv_post_delivery_redeclaration_proven"):
            set_rv3_phase(session, RV3_PHASE_POST_DELIVERY)
    if coerced and proven:
        session["_solo_rv_browser_delivery_recorded"] = True
    render_native_control_probe(st, session, probe_placeholder)
    return raw


def ledger_rows_for_probe_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload.get("rows") or [])


def ledger_to_declaration_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for row in rows:
        ev = str(row.get("event") or "")
        phase = ev
        if ev == "declaration_attempt":
            phase = "before_mount"
        elif ev == "declaration_returned":
            phase = "after_mount"
        elif ev == "post_delivery_redeclaration":
            phase = "post_delivery_redeclaration"
        mapped.append(
            {
                **row,
                "phase": phase,
                "script_run_id": row.get("streamlit_session_id"),
                "rv_ladder_step": row.get("control_name"),
                "browser_delivery_seen": bool(row.get("browser_send_seen") or ev == "post_delivery_redeclaration"),
                "before_browser_send": ev == "declaration_attempt" and not row.get("browser_send_seen"),
            }
        )
    return mapped
