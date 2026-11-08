"""A non-secret trace of the last sign-in attempt (real-phone sign-in, owner 2026-11-08).

The owner can't sign in on a physical Android phone, but desktop phone emulation works, so we need to see
which step fails on the device. Each step records only a step name, ok/failed, a sanitized reason code and a
few booleans or small numbers from an allowlist. It never stores passwords, tokens, the session id, user ids
or the email address.

The trace is shown under the sign-in error ("Sign-in details") so the owner can read it on the phone, and
each step is printed as one ``[signin-trace]`` line so it also appears in the Streamlit Cloud app logs.
"""

from __future__ import annotations

import re
import time
from typing import Any, MutableMapping

TRACE_KEY = "_suite_auth_signin_trace"
MAX_ENTRIES = 20
# Only these fields are kept; values are coerced to bool / int / short sanitized strings.
_BOOL_FIELDS = ("email_present", "password_present", "was_signed_in", "write_committed", "fresh_sid",
                "persistence_succeeded", "handoff_reset")
_INT_FIELDS = ("readback_rows", "token_generation")
_TEXT_FIELDS = ("reason", "sid_source", "exception", "write_mode", "handoff_phase")
_SAFE = re.compile(r"[^A-Za-z0-9:_.\-]")


def _clean(value: Any) -> str:
    return _SAFE.sub("", str(value or ""))[:80]


def record(session: MutableMapping[str, Any] | None, step: str, ok: bool, **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"step": _clean(step), "ok": bool(ok), "t": time.strftime("%H:%M:%S")}
    for k in _BOOL_FIELDS:
        if k in fields:
            entry[k] = bool(fields[k])
    for k in _INT_FIELDS:
        if k in fields:
            try:
                entry[k] = int(fields[k])
            except (TypeError, ValueError):
                pass
    for k in _TEXT_FIELDS:
        if k in fields and fields[k] not in (None, ""):
            entry[k] = _clean(fields[k])
    if session is not None:
        try:
            trail = session.get(TRACE_KEY)
            trail = list(trail) if isinstance(trail, list) else []
            session[TRACE_KEY] = (trail + [entry])[-MAX_ENTRIES:]
        except Exception:
            pass
    try:
        bits = " ".join(f"{k}={v}" for k, v in entry.items() if k not in ("step", "t"))
        print(f"[signin-trace] step={entry['step']} {bits}", flush=True)
    except Exception:
        pass
    return entry


def start(session: MutableMapping[str, Any] | None) -> None:
    """A new attempt starts a new trace."""
    if session is not None:
        try:
            session[TRACE_KEY] = []
        except Exception:
            pass


def entries(session: MutableMapping[str, Any] | None) -> list[dict[str, Any]]:
    trail = (session or {}).get(TRACE_KEY) if session is not None else None
    return [e for e in trail if isinstance(e, dict)] if isinstance(trail, list) else []


def lines(session: MutableMapping[str, Any] | None) -> list[str]:
    out = []
    for e in entries(session):
        extra = ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("step", "ok", "t"))
        out.append(f"{e.get('t', '')} · {e.get('step')} · {'ok' if e.get('ok') else 'FAILED'}" + (f" · {extra}" if extra else ""))
    return out
