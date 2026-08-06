"""Auth session finalization diagnostics (ledger + harness classification)."""

from __future__ import annotations

from typing import Any

AUTH_FINALIZE1 = "AUTH_FINALIZE1"
AUTH_FINALIZE2 = "AUTH_FINALIZE2"
AUTH_FINALIZE3 = "AUTH_FINALIZE3"
AUTH_FINALIZE4 = "AUTH_FINALIZE4"
AUTH_FINALIZE5 = "AUTH_FINALIZE5"
AUTH_FINALIZE6 = "AUTH_FINALIZE6"
AUTH_FINALIZE7 = "AUTH_FINALIZE7"
AUTH_FINALIZE8 = "AUTH_FINALIZE8"

APPLY_CHECKPOINTS = (
    "apply_authenticated_user_entry",
    "apply_authenticated_user_before_session_flag",
    "apply_authenticated_user_after_session_flag",
    "apply_authenticated_user_before_user_id",
    "apply_authenticated_user_after_user_id",
    "apply_authenticated_user_before_tokens",
    "apply_authenticated_user_after_tokens",
    "apply_authenticated_user_exit",
    "restore_auth_session_after_apply",
    "auth_session_complete_before_start_control",
)


def session_identity_fields(session: dict[str, Any], st: Any | None = None) -> dict[str, Any]:
    st_id = 0
    ids_match: bool | None = None
    if st is not None:
        try:
            st_id = id(st.session_state)
            ids_match = st_id == id(session)
        except Exception:
            pass
    return {
        "session_object_id": id(session),
        "st_session_state_object_id": st_id,
        "session_state_ids_match": ids_match,
    }


def emit_apply_write_checkpoint(
    session: dict[str, Any],
    checkpoint: str,
    *,
    st: Any | None = None,
    write_key: str = "",
    apply_return_ok: bool | None = None,
) -> None:
    try:
        from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint
        from live_draft_auth_snapshot_stage1_diag import auth_session_complete_breakdown

        extra: dict[str, Any] = {
            **session_identity_fields(session, st),
            **auth_session_complete_breakdown(session),
        }
        if write_key:
            extra["write_key"] = str(write_key)[:80]
        if apply_return_ok is not None:
            extra["apply_return_ok"] = bool(apply_return_ok)
        emit_prestart_hydration_checkpoint(session, checkpoint, st=st, extra=extra)
    except ImportError:
        pass


def classify_auth_finalize_from_ledger(rows: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    """Return (classification, detail, evidence) from hydration/mutation rows."""
    hydration = [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"]
    mutations = [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == "production_stage1_auth_prestart_mutation"]
    by_cp: dict[str, dict[str, Any]] = {}
    for r in hydration:
        cp = str(r.get("checkpoint") or "")
        if cp:
            by_cp[cp] = r

    exit_row = by_cp.get("apply_authenticated_user_exit") or {}
    before_start = next(
        (r for r in rows if str(r.get("event") or "") == "production_stage1_auth_state_before_start_control"),
        {},
    )
    evidence: dict[str, Any] = {
        "apply_exit_session_flag": _flag(exit_row, "session_flag_present"),
        "apply_exit_auth_complete": exit_row.get("auth_session_complete"),
        "before_start_session_flag": _flag(before_start, "session_flag_present"),
        "before_start_auth_complete": before_start.get("auth_session_complete"),
        "apply_exit_session_object_id": exit_row.get("session_object_id"),
        "before_start_session_object_id": before_start.get("session_object_id"),
    }

    if exit_row:
        if exit_row.get("session_state_ids_match") is False:
            return AUTH_FINALIZE3, "apply_target_not_st_session_state", evidence
        if _flag(exit_row, "session_flag_present") is False and exit_row.get("apply_return_ok") is True:
            return AUTH_FINALIZE1, "apply_return_ok_without_session_flag", evidence
        if _flag(exit_row, "session_flag_present") is False:
            after_flag = by_cp.get("apply_authenticated_user_after_session_flag") or {}
            if _flag(after_flag, "session_flag_present") is True:
                return AUTH_FINALIZE4, "session_flag_cleared_after_apply_write", evidence

    for m in mutations:
        if str(m.get("key") or "") != "_suite_auth_session":
            continue
        if m.get("value_present_before") and not m.get("value_present_after"):
            src = str(m.get("source_function") or "")
            if "apply_baseball_disk_state" in src or "enforce_identity" in src:
                return AUTH_FINALIZE5, f"disk_or_identity_apply:{src or 'mutation'}", evidence
            return AUTH_FINALIZE4, f"session_flag_cleared_by_{src or 'mutation'}", evidence

    after_disk = by_cp.get("after_apply_baseball_disk_state") or {}
    if after_disk and _flag(after_disk, "session_flag_present") is False and _flag(
        by_cp.get("apply_authenticated_user_exit"), "session_flag_present"
    ):
        return AUTH_FINALIZE5, "after_apply_baseball_disk_state", evidence

    if before_start and exit_row:
        if exit_row.get("session_object_id") and before_start.get("session_object_id"):
            if int(exit_row["session_object_id"]) != int(before_start["session_object_id"]):
                return AUTH_FINALIZE7, "before_start_different_session_object", evidence

    if _flag(exit_row, "session_flag_present") and not before_start.get("auth_session_complete"):
        missing = []
        if not _flag(before_start, "auth_user_id_present"):
            missing.append("auth_user_id")
        if not _flag(before_start, "access_token_present"):
            missing.append("access_token")
        if not _flag(before_start, "refresh_token_present"):
            missing.append("refresh_token")
        if not _flag(before_start, "session_flag_present"):
            missing.append("session_flag")
        if missing:
            if "session_flag" in missing and _flag(exit_row, "session_flag_present"):
                return AUTH_FINALIZE4, "session_flag_lost_before_start_control", evidence
            return AUTH_FINALIZE6, "incomplete_keys:" + ",".join(missing), evidence

    return AUTH_FINALIZE8, "start_disabled_or_unclassified_finalize_boundary", evidence


def _flag(row: dict[str, Any], key: str) -> bool | None:
    if not row:
        return None
    if key in row:
        return bool(row.get(key))
    prot = row.get("protected_keys")
    if isinstance(prot, dict) and key in prot:
        return bool(prot.get(key))
    return None
