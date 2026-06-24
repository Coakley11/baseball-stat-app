"""User-facing Supabase errors for shared draft room persistence."""

from __future__ import annotations

import json
import re
from typing import Any

_PARSE_RE = re.compile(
    r"Supabase\s+(\w+)\s+(\S+)\s+failed\s+\((\d+)\):\s*(.*)",
    re.DOTALL,
)


class SharedRoomSupabaseError(RuntimeError):
    """Raised when PostgREST rejects a shared draft room write."""

    def __init__(
        self,
        method: str,
        path: str,
        status_code: int,
        detail: str,
        *,
        user_message: str = "",
    ) -> None:
        self.method = str(method or "").upper()
        self.path = str(path or "")
        self.status_code = int(status_code or 0)
        self.detail = str(detail or "").strip()
        self.user_message = user_message or friendly_supabase_message(self.status_code, self.detail)
        super().__init__(
            f"Supabase {self.method} {self.path} failed ({self.status_code}): {self.detail}"
        )

    def to_diag_dict(self) -> dict[str, Any]:
        parsed: Any = self.detail
        try:
            parsed = json.loads(self.detail)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return {
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "detail": self.detail,
            "parsed_detail": parsed,
            "user_message": self.user_message,
        }


def friendly_supabase_message(status_code: int, detail: str) -> str:
    """Map PostgREST/Supabase failures to setup guidance."""
    low = str(detail or "").lower()
    if status_code == 404 or "pgrst205" in low or "could not find the table" in low:
        return (
            "Shared draft room table is missing in Supabase. "
            "Run scripts/sql/baseball_shared_draft_rooms.sql in the Supabase SQL editor, then retry."
        )
    if status_code in (401, 403) or "permission denied" in low or "row-level security" in low or "rls" in low:
        return (
            "Supabase denied access to shared draft rooms (HTTP "
            f"{status_code}). Check API key permissions and table grants/RLS policies."
        )
    if status_code == 409 or "duplicate key" in low:
        return "That room code already exists. Refresh and try creating a new shared room."
    if status_code == 400:
        if "invalid input syntax" in low or "json" in low:
            return "Shared draft room payload was rejected by Supabase (invalid JSON/column value)."
        return f"Supabase rejected the shared room payload (HTTP 400). Check table column types."
    if status_code >= 500:
        return f"Supabase server error (HTTP {status_code}). Try again in a moment."
    if status_code:
        return f"Could not save shared draft room to Supabase (HTTP {status_code})."
    return "Could not save shared draft room to Supabase."


def shared_room_supabase_error_from_runtime(exc: BaseException) -> SharedRoomSupabaseError:
    if isinstance(exc, SharedRoomSupabaseError):
        return exc
    msg = str(exc or "")
    match = _PARSE_RE.match(msg)
    if match:
        method, path, status_code, detail = match.groups()
        return SharedRoomSupabaseError(method, path, int(status_code), detail)
    return SharedRoomSupabaseError("?", "baseball_shared_draft_rooms", 0, msg)


def record_shared_room_supabase_error(session: dict[str, Any], exc: SharedRoomSupabaseError) -> str:
    session["_draft_room_last_error"] = exc.user_message
    session["_draft_room_supabase_error"] = exc.to_diag_dict()
    return exc.user_message
