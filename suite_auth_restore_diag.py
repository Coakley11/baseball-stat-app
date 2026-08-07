"""Sanitized Supabase auth restore diagnostics (no token/email exposure)."""

from __future__ import annotations

import re
from typing import Any

_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-+/=]{20,}")


def sanitize_auth_exception(exc: BaseException, *, phase: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "exception_class": type(exc).__name__,
        "phase": str(phase or "set_session")[:32],
        "refresh_attempted": False,
        "refresh_ok": None,
    }
    for attr in ("status", "code", "name"):
        if hasattr(exc, attr):
            val = getattr(exc, attr, None)
            if val is not None:
                out[f"auth_{attr}"] = str(val)[:120]
    msg = str(exc)[:400]
    msg = _JWT_RE.sub("[redacted_jwt]", msg)
    out["message_sanitized"] = msg[:240]
    try:
        from suite_deploy_marker import resolve_git_commit_short

        out["deployment_sha"] = str(resolve_git_commit_short() or "")[:7]
    except Exception:
        out["deployment_sha"] = ""
    return out


def emit_restore_auth_exception_checkpoint(
    session_state: dict[str, Any],
    exc: BaseException,
    *,
    phase: str,
    st: Any | None = None,
    refresh_attempted: bool = False,
    refresh_ok: bool | None = None,
) -> None:
    payload = sanitize_auth_exception(exc, phase=phase)
    payload["refresh_attempted"] = bool(refresh_attempted)
    if refresh_ok is not None:
        payload["refresh_ok"] = bool(refresh_ok)
    try:
        from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

        emit_prestart_hydration_checkpoint(
            session_state,
            "restore_auth_session_exception",
            st=st,
            extra=payload,
        )
    except ImportError:
        pass
