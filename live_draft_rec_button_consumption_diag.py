"""Diagnostics: incoming Add-to-Queue trigger vs consuming-run registration (observability only)."""

from __future__ import annotations

import time
from typing import Any

CONSUMPTION_LEDGER_KEY = "_live_draft_rec_queue_button_consumption_ledger"
CONSUMPTION_LAST_KEY = "_live_draft_rec_queue_button_consumption_last"
MAX_LEDGER = 48


def _diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        return bool(stage1_production_ledger_enabled(st, session))
    except ImportError:
        return False


def _script_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _incoming_trigger_for_user_key(st: Any | None, user_key: str) -> dict[str, Any]:
    """Read whether Streamlit still holds trigger_value=true for this user key."""
    out: dict[str, Any] = {
        "incoming_trigger_seen": False,
        "incoming_widget_id": "",
        "incoming_trigger_value": None,
        "incoming_lookup_source": "",
    }
    uk = str(user_key or "").strip()
    if not uk:
        return out
    try:
        from live_draft_streamlit_widget_metadata_diag import (
            get_streamlit_session_state,
            resolve_authoritative_widget_id,
            snapshot_backend_widget_state,
        )

        ss = get_streamlit_session_state(st)
        wid, src = resolve_authoritative_widget_id(st, uk)
        if not wid and ss is not None:
            try:
                # Incoming wire id may exist in _new_widget_state before register_widget.
                suffix = f"-{uk}"
                states = getattr(getattr(ss, "_new_widget_state", None), "states", {}) or {}
                matches = [k for k in states if str(k).endswith(suffix)]
                if matches:
                    wid = str(matches[-1])
                    src = "new_widget_state_key_suffix"
            except Exception:
                pass
        out["incoming_widget_id"] = str(wid or "")[:200]
        out["incoming_lookup_source"] = str(src or "")
        if ss is not None and wid:
            snap = snapshot_backend_widget_state(ss, wid)
            out["incoming_trigger_seen"] = bool(snap.get("in_new_widget_state"))
            rep = str(snap.get("deserialized_value_repr") or "")
            if rep in ("True", "true"):
                out["incoming_trigger_value"] = True
                out["incoming_trigger_seen"] = True
            elif rep in ("False", "false"):
                out["incoming_trigger_value"] = False
            try:
                val = ss._new_widget_state.get(wid)
                if val is True:
                    out["incoming_trigger_value"] = True
                    out["incoming_trigger_seen"] = True
                elif val is False:
                    out["incoming_trigger_value"] = False
            except Exception:
                pass
    except ImportError:
        pass
    except Exception as exc:
        out["incoming_lookup_error"] = str(exc)[:160]
    return out


def _registered_widget_id(st: Any | None, user_key: str) -> tuple[str, str]:
    try:
        from live_draft_streamlit_widget_metadata_diag import resolve_authoritative_widget_id

        return resolve_authoritative_widget_id(st, user_key)
    except ImportError:
        return "", "unavailable"


def note_rec_queue_button_consumption(
    st: Any | None,
    session: dict[str, Any],
    *,
    widget_key: str,
    player_id: str = "",
    player_name: str = "",
    room_id: str = "",
    pick_index: int | None = None,
    button_return_value: bool | None = None,
    paint_via: str = "",
    interactive_owner: str = "",
    phase: str = "post_button",
) -> dict[str, Any]:
    """Ledger row: incoming trigger ↔ registered id ↔ st.button return (diag only)."""
    if not _diag_enabled(st, session):
        return {}
    wk = str(widget_key or "").strip()
    incoming = _incoming_trigger_for_user_key(st, wk)
    reg_id, reg_src = _registered_widget_id(st, wk)
    incoming_id = str(incoming.get("incoming_widget_id") or "")
    match = bool(incoming_id and reg_id and incoming_id == reg_id)
    suffix_match = bool(wk and ((incoming_id.endswith(wk) and reg_id.endswith(wk)) or (wk in incoming_id and wk in reg_id)))
    row: dict[str, Any] = {
        "ts": time.time(),
        "phase": str(phase or ""),
        "script_run_seq": _script_run_seq(session),
        "room_id": str(room_id or "").strip(),
        "pick_index": pick_index,
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip()[:80],
        "user_key": wk,
        "incoming_trigger_seen": bool(incoming.get("incoming_trigger_seen")),
        "incoming_trigger_value": incoming.get("incoming_trigger_value"),
        "incoming_widget_id": incoming_id,
        "registered_widget_id": str(reg_id or "")[:200],
        "registered_id_source": str(reg_src or ""),
        "incoming_id_matches_registered": match,
        "incoming_id_suffix_matches": suffix_match,
        "button_return_value": button_return_value,
        "paint_via": str(paint_via or session.get("_solo_stage1_last_recommendation_paint") or ""),
        "interactive_owner": str(
            interactive_owner or session.get("_live_draft_rec_queue_interactive_owner") or ""
        ),
        "heavy_paint_done": bool(session.get("_live_draft_heavy_paint_done")),
    }
    if isinstance(session.get("_solo_stage1_last_recommendation_paint"), dict):
        row["paint_via"] = str(
            (session.get("_solo_stage1_last_recommendation_paint") or {}).get("via") or row["paint_via"]
        )
    book = list(session.get(CONSUMPTION_LEDGER_KEY) or [])
    book.append(row)
    session[CONSUMPTION_LEDGER_KEY] = book[-MAX_LEDGER:]
    session[CONSUMPTION_LAST_KEY] = dict(row)
    return row
