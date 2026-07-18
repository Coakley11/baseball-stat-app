"""Diagnostics + authoritative End/Delete for Everyone transaction."""

from __future__ import annotations

import time
import uuid
from typing import Any

DELETE_TRACE_KEY = "_live_draft_delete_trace"
DELETE_RECEIPT_KEY = "_live_draft_deletion_receipt"
DELETE_TRACE_MAX = 40


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def note_delete_trace(session: dict[str, Any], event: str, **fields: Any) -> None:
    """Append a structured delete-path event (no chat bodies / free text)."""
    row: dict[str, Any] = {
        "at": _utc_now_iso(),
        "event": str(event or "").strip(),
        "t_ms": int(time.time() * 1000),
    }
    for key, val in fields.items():
        if val is None:
            continue
        if isinstance(val, (str, int, float, bool)):
            row[key] = val
        else:
            row[key] = str(val)[:120]
    trace = session.get(DELETE_TRACE_KEY)
    if not isinstance(trace, list):
        trace = []
    trace.append(row)
    session[DELETE_TRACE_KEY] = trace[-DELETE_TRACE_MAX:]


def render_delete_trace_panel(st: Any, session: dict[str, Any]) -> None:
    """Developer Mode panel for the End/Delete click path."""
    receipt = session.get(DELETE_RECEIPT_KEY)
    trace = session.get(DELETE_TRACE_KEY)
    if not isinstance(receipt, dict) and not isinstance(trace, list):
        return
    with st.expander("End/Delete diagnostics", expanded=False):
        if isinstance(receipt, dict):
            st.write(
                {
                    "ok": receipt.get("ok"),
                    "room_code": receipt.get("room_code"),
                    "draft_id": receipt.get("draft_id"),
                    "deletion_generation": receipt.get("deletion_generation"),
                    "deleted_at": receipt.get("deleted_at"),
                    "backend_ok": receipt.get("backend_ok"),
                    "backend_error": receipt.get("backend_error"),
                    "auth_ok": receipt.get("auth_ok"),
                    "elapsed_ms": receipt.get("elapsed_ms"),
                }
            )
        if isinstance(trace, list) and trace:
            st.write(list(trace)[-20:])


def delete_shared_live_draft_for_everyone(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    room_id: str = "",
    draft_id: str = "",
    room_code: str = "",
    commissioner_participant_id: str = "",
    expected_room_revision: int | None = None,
    reason: str = "delete_shared_live_draft_for_everyone",
) -> dict[str, Any]:
    """One authoritative End/Delete transaction with a durable deletion receipt.

    UI must not treat local session clear as success — ``backend_ok`` is required
    for shared rooms. Solo rooms may succeed with local purge only.
    """
    started = time.time()
    session["_live_draft_deleting"] = "in_progress"
    session["_live_draft_controls_locked"] = True
    note_delete_trace(session, "delete_operation_entered", reason=reason)

    live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    code = str(
        room_code
        or session.get("active_shared_draft_room_code")
        or (live.get("room_code") if isinstance(live, dict) else "")
        or ((live.get("config") or {}).get("room_code") if isinstance(live, dict) else "")
        or ""
    ).strip().upper()
    d_id = str(
        draft_id
        or (live.get("draft_room_id") if isinstance(live, dict) else "")
        or (live.get("draft_id") if isinstance(live, dict) else "")
        or ""
    ).strip()
    r_id = str(room_id or d_id or "").strip()

    try:
        from draft_room_participant_state import resolve_participant_id

        pid = str(commissioner_participant_id or resolve_participant_id(session) or "").strip()
    except ImportError:
        pid = str(commissioner_participant_id or session.get("draft_room_participant_id") or "").strip()

    note_delete_trace(
        session,
        "ids_resolved",
        room_code=code or None,
        draft_id=d_id or None,
        room_id=r_id or None,
        commissioner_participant_id=pid or None,
        expected_revision=expected_room_revision,
        lifecycle_before=str(session.get("_live_draft_lifecycle_last") or ""),
    )

    document: dict[str, Any] | None = None
    host_pid = ""
    revision = int(expected_room_revision or 0)
    backend_ok = True
    backend_error = ""
    deletion_generation = f"del-{uuid.uuid4().hex[:12]}"
    deleted_at = _utc_now_iso()
    is_shared = bool(code)

    if is_shared:
        try:
            from draft_room_shared_state import (
                bump_revision,
                get_shared_room_store,
                invalidate_shared_room_document_cache,
                load_shared_room,
            )

            note_delete_trace(session, "backend_load_attempted", room_code=code)
            document = load_shared_room(code)
            if not isinstance(document, dict):
                backend_ok = False
                backend_error = "room_not_found"
                note_delete_trace(session, "backend_result", ok=False, error=backend_error)
            else:
                host_pid = str(
                    document.get("commissioner_participant_id")
                    or document.get("host_participant_id")
                    or document.get("host_user_id")
                    or ""
                ).strip()
                revision = int(document.get("revision") or revision or 0)
                note_delete_trace(
                    session,
                    "commissioner_check",
                    current_participant_id=pid or None,
                    authoritative_commissioner_id=host_pid or None,
                )
                auth_ok = False
                try:
                    from shared_draft_permissions import is_canonical_commissioner

                    auth_ok = bool(is_canonical_commissioner(session, document))
                except ImportError:
                    auth_ok = bool(pid and host_pid and pid == host_pid)
                note_delete_trace(session, "commissioner_authorization_result", auth_ok=auth_ok)
                if not auth_ok:
                    session["_live_draft_deleting"] = "failed"
                    receipt = {
                        "ok": False,
                        "error": "not_commissioner",
                        "auth_ok": False,
                        "room_code": code,
                        "draft_id": d_id or str(document.get("draft_room_id") or ""),
                        "room_id": r_id,
                        "backend_ok": False,
                        "elapsed_ms": int((time.time() - started) * 1000),
                    }
                    session[DELETE_RECEIPT_KEY] = receipt
                    return receipt

                if not d_id:
                    d_id = str(document.get("draft_room_id") or "").strip()
                if not r_id:
                    r_id = d_id

                updated = bump_revision(dict(document))
                updated["status"] = "deleted"
                updated["deleted_at"] = deleted_at
                updated["deleted_by"] = pid
                updated["deletion_generation"] = deletion_generation
                updated["termination"] = "deleted"
                updated["terminated_at"] = deleted_at
                updated["participants"] = {}
                updated["joined_participants"] = {}
                updated["team_claims"] = {}
                updated["resume_rejoined"] = {}
                room_blob = updated.get("room")
                if isinstance(room_blob, dict):
                    room_blob = dict(room_blob)
                    room_blob["status"] = "deleted"
                    updated["room"] = room_blob

                note_delete_trace(
                    session,
                    "backend_room_update_attempted",
                    room_code=code,
                    revision_before=revision,
                    deletion_generation=deletion_generation,
                )
                try:
                    backend = get_shared_room_store()
                    saved = None
                    cas_ok = False
                    if hasattr(backend, "save_if_revision") and revision > 0:
                        cas_ok, saved = backend.save_if_revision(
                            updated, expected_revision=revision
                        )
                        if not cas_ok:
                            # Reload and force-delete on latest revision.
                            fresh = load_shared_room(code)
                            if isinstance(fresh, dict):
                                updated = bump_revision(dict(fresh))
                                updated["status"] = "deleted"
                                updated["deleted_at"] = deleted_at
                                updated["deleted_by"] = pid
                                updated["deletion_generation"] = deletion_generation
                                updated["participants"] = {}
                                updated["joined_participants"] = {}
                                room_blob = updated.get("room")
                                if isinstance(room_blob, dict):
                                    room_blob = dict(room_blob)
                                    room_blob["status"] = "deleted"
                                    updated["room"] = room_blob
                                saved = backend.save(updated)
                                cas_ok = True
                    else:
                        saved = backend.save(updated)
                        cas_ok = True
                    if not cas_ok or not isinstance(saved, dict):
                        backend_ok = False
                        backend_error = "save_failed"
                    else:
                        # Read-back verification
                        invalidate_shared_room_document_cache(session, code)
                        verified = load_shared_room(code)
                        vstatus = str((verified or {}).get("status") or "").strip().lower()
                        if vstatus != "deleted":
                            backend_ok = False
                            backend_error = f"readback_status_{vstatus or 'missing'}"
                        else:
                            document = verified if isinstance(verified, dict) else saved
                            revision = int((document or {}).get("revision") or 0)
                            # Ensure participants stay cleared even if a later local close
                            # reloads a stale cached copy.
                            if (document or {}).get("participants"):
                                cleaned = bump_revision(dict(document))
                                cleaned["participants"] = {}
                                cleaned["joined_participants"] = {}
                                cleaned["status"] = "deleted"
                                get_shared_room_store().save(cleaned)
                                invalidate_shared_room_document_cache(session, code)
                                document = cleaned
                    note_delete_trace(
                        session,
                        "backend_result",
                        ok=backend_ok,
                        error=backend_error or None,
                        revision_after=revision or None,
                    )
                except Exception as exc:
                    backend_ok = False
                    backend_error = f"{type(exc).__name__}:{exc}"[:160]
                    note_delete_trace(session, "backend_result", ok=False, error=backend_error)
        except Exception as exc:
            backend_ok = False
            backend_error = f"load_exc:{type(exc).__name__}"
            note_delete_trace(session, "backend_result", ok=False, error=backend_error)

        if not backend_ok:
            session["_live_draft_deleting"] = "failed"
            receipt = {
                "ok": False,
                "error": "backend_delete_failed",
                "auth_ok": True,
                "backend_ok": False,
                "backend_error": backend_error,
                "room_code": code,
                "draft_id": d_id,
                "room_id": r_id,
                "deletion_generation": deletion_generation,
                "deleted_at": deleted_at,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
            session[DELETE_RECEIPT_KEY] = receipt
            note_delete_trace(session, "delete_aborted_no_receipt", error=backend_error)
            # Do not purge local state — commissioner stays in room and can retry.
            session.pop("_live_draft_controls_locked", None)
            return receipt

    # Tombstones + local purge only after authoritative success (or solo).
    try:
        from live_draft_termination import (
            discard_live_draft_and_start_over,
            persist_durable_tombstones,
        )

        persist_durable_tombstones(session, draft_id=d_id, room_id=r_id, room_code=code)
        note_delete_trace(session, "tombstones_written", room_code=code or None, draft_id=d_id or None)
        # Shared backend already deleted — discard clears local without re-saving active status.
        result = discard_live_draft_and_start_over(session, st=st, reason=reason)
        note_delete_trace(session, "session_purge_completed", discard_ok=bool(result.get("ok")))
    except Exception as exc:
        note_delete_trace(session, "session_purge_error", error=f"{type(exc).__name__}")
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)
        session.pop("active_shared_draft_room_code", None)
        session["_live_draft_deleting"] = "done"

    elapsed_ms = int((time.time() - started) * 1000)
    receipt = {
        "ok": True,
        "auth_ok": True,
        "backend_ok": backend_ok if is_shared else True,
        "backend_error": backend_error or None,
        "room_code": code or None,
        "draft_id": d_id or None,
        "room_id": r_id or None,
        "deletion_generation": deletion_generation,
        "deleted_at": deleted_at,
        "deleted_by": pid or None,
        "revision_after": revision or None,
        "elapsed_ms": elapsed_ms,
        "reason": reason,
    }
    session[DELETE_RECEIPT_KEY] = receipt
    session["_live_draft_deleting"] = "done"
    session["_live_draft_force_setup_after_delete"] = True
    note_delete_trace(session, "deletion_receipt_stored", elapsed_ms=elapsed_ms, ok=True)
    note_delete_trace(session, "full_app_rerun_requested")
    return receipt


def on_confirm_end_delete_for_everyone() -> None:
    """Streamlit on_click: run authoritative delete before the next script body."""
    try:
        import streamlit as st_mod
    except Exception:
        return
    session = st_mod.session_state
    note_delete_trace(session, "confirmation_accepted_on_click")
    note_delete_trace(
        session,
        "button_clicked",
        widget_key="live_draft_discard_confirm_btn",
    )
    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        session["_live_draft_lifecycle_last"] = resolve_live_draft_lifecycle(session)
    except Exception:
        pass
    live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    meta = session.get("draft_room_shared_meta") if isinstance(session.get("draft_room_shared_meta"), dict) else {}
    receipt = delete_shared_live_draft_for_everyone(
        session,
        st=st_mod,
        room_code=code,
        draft_id=str((live or {}).get("draft_room_id") or ""),
        room_id=str((live or {}).get("draft_room_id") or ""),
        expected_room_revision=int(meta.get("revision") or 0) or None,
        reason="on_click_end_delete_for_everyone",
    )
    session.pop("_live_draft_discard_confirm", None)
    if receipt.get("ok"):
        try:
            st_mod.rerun()
        except Exception:
            pass
    else:
        session["_live_draft_delete_error"] = str(
            receipt.get("backend_error") or receipt.get("error") or "Delete failed"
        )


def on_show_end_delete_confirm() -> None:
    try:
        import streamlit as st_mod
    except Exception:
        return
    note_delete_trace(st_mod.session_state, "button_clicked", widget_key="live_draft_discard_btn")
    note_delete_trace(st_mod.session_state, "confirmation_shown")
    st_mod.session_state["_live_draft_discard_confirm"] = True
    st_mod.session_state.pop("_live_draft_replace_resumable_confirm", None)
    st_mod.session_state.pop("_live_draft_leave_confirm", None)
