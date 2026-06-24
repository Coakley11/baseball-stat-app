"""Supabase backend for shared live draft room documents (PR 4)."""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from typing import Any

from draft_room_json_sanitize import SharedRoomJsonSerializeError, prepare_supabase_json_body
from draft_room_supabase_errors import SharedRoomSupabaseError, shared_room_supabase_error_from_runtime
from draft_room_shared_state import sanitize_shared_room_document

_TABLE = "baseball_shared_draft_rooms"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _host_user_id() -> str:
    try:
        from suite_user import get_account_user_id

        return str(get_account_user_id() or "")
    except ImportError:
        return ""


def _request(method: str, path: str, **kwargs: Any) -> Any:
    from suite_storage_supabase import _invalidate_read_cache_for_table, _request as supabase_request

    try:
        result = supabase_request(method, path, **kwargs)
    except RuntimeError as exc:
        raise shared_room_supabase_error_from_runtime(exc) from exc
    if method.upper() != "GET":
        _invalidate_read_cache_for_table(_TABLE)
    return result


def document_to_row(document: dict[str, Any], *, created: bool = False) -> dict[str, Any]:
    doc = sanitize_shared_room_document(document)
    code = str(doc.get("room_code") or "").strip().upper()
    now = _utc_now_iso()
    row = {
        "room_code": code,
        "host_user_id": str(doc.get("host_user_id") or doc.get("host_participant_id") or _host_user_id()),
        "shared_room_json": doc,
        "revision": int(doc.get("revision") or 1),
        "status": str(doc.get("status") or "not_started"),
        "updated_at": str(doc.get("updated_at") or now),
    }
    if created:
        row["created_at"] = str(doc.get("created_at") or now)
    return prepare_supabase_json_body(row, path="$")


def _supabase_write_body(row: dict[str, Any], *, patch: bool) -> dict[str, Any]:
    if patch:
        body = {
            "host_user_id": row["host_user_id"],
            "shared_room_json": row["shared_room_json"],
            "revision": row["revision"],
            "status": row["status"],
            "updated_at": row["updated_at"],
        }
        return prepare_supabase_json_body(body, path="$.patch")
    return prepare_supabase_json_body(row, path="$.post")


def row_to_document(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    raw = row.get("shared_room_json")
    if not isinstance(raw, dict):
        return None
    doc = copy.deepcopy(raw)
    doc["room_code"] = str(row.get("room_code") or doc.get("room_code") or "").upper()
    doc["revision"] = int(row.get("revision") or doc.get("revision") or 1)
    doc["status"] = str(row.get("status") or doc.get("status") or "")
    doc["updated_at"] = str(row.get("updated_at") or doc.get("updated_at") or "")
    if row.get("host_user_id"):
        doc["host_user_id"] = str(row.get("host_user_id"))
    doc.setdefault("schema_version", 1)
    return doc


class SupabaseSharedRoomStore:
    """Cross-device shared draft room persistence via PostgREST."""

    def exists(self, room_code: str) -> bool:
        code = str(room_code or "").strip().upper()
        if not code:
            return False
        try:
            rows = _request(
                "GET",
                _TABLE,
                params={
                    "select": "room_code",
                    "room_code": f"eq.{code}",
                    "limit": "1",
                },
                prefer="return=representation",
            )
        except RuntimeError:
            return False
        return isinstance(rows, list) and bool(rows)

    def load(self, room_code: str) -> dict[str, Any] | None:
        code = str(room_code or "").strip().upper()
        if not code:
            return None
        try:
            rows = _request(
                "GET",
                _TABLE,
                params={
                    "select": "room_code,host_user_id,shared_room_json,revision,status,created_at,updated_at",
                    "room_code": f"eq.{code}",
                    "limit": "1",
                },
                prefer="return=representation",
            )
        except RuntimeError:
            return None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        return row_to_document(rows[0])

    def save(self, document: dict[str, Any]) -> dict[str, Any]:
        code = str(document.get("room_code") or "").strip().upper()
        if not code:
            raise ValueError("shared room document missing room_code")
        try:
            row = document_to_row(document, created=not self.exists(code))
        except SharedRoomJsonSerializeError as exc:
            raise ValueError(str(exc)) from exc
        if self.exists(code):
            rows = _request(
                "PATCH",
                _TABLE,
                params={"room_code": f"eq.{code}"},
                json_body=_supabase_write_body(row, patch=True),
                prefer="return=representation",
            )
        else:
            rows = _request(
                "POST",
                _TABLE,
                json_body=_supabase_write_body(row, patch=False),
                prefer="return=representation",
            )
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            saved = row_to_document(rows[0])
            if saved:
                return saved
        return sanitize_shared_room_document(document)

    def save_if_revision(
        self,
        document: dict[str, Any],
        *,
        expected_revision: int | None,
    ) -> tuple[bool, dict[str, Any] | None]:
        code = str(document.get("room_code") or "").strip().upper()
        if not code:
            return False, None
        current = self.load(code)
        if current is None:
            saved = self.save(document)
            return True, saved

        current_rev = int(current.get("revision") or 0)
        if expected_revision is not None and current_rev != int(expected_revision):
            return False, current

        row = document_to_row(document)
        try:
            patch_body = _supabase_write_body(row, patch=True)
        except SharedRoomJsonSerializeError as exc:
            raise ValueError(str(exc)) from exc
        try:
            rows = _request(
                "PATCH",
                _TABLE,
                params={
                    "room_code": f"eq.{code}",
                    "revision": f"eq.{current_rev}",
                },
                json_body=patch_body,
                prefer="return=representation",
            )
        except SharedRoomSupabaseError:
            refreshed = self.load(code)
            return False, refreshed
        except RuntimeError:
            refreshed = self.load(code)
            return False, refreshed

        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            saved = row_to_document(rows[0])
            return True, saved

        refreshed = self.load(code)
        return False, refreshed


_SUPABASE_STORE: SupabaseSharedRoomStore | None = None


def get_supabase_shared_room_store() -> SupabaseSharedRoomStore:
    global _SUPABASE_STORE
    if _SUPABASE_STORE is None:
        _SUPABASE_STORE = SupabaseSharedRoomStore()
    return _SUPABASE_STORE


def supabase_shared_room_backend_available() -> bool:
    if os.environ.get("BASEBALL_SHARED_DRAFT_ROOM_BACKEND", "").strip().lower() == "local":
        return False
    try:
        from suite_storage_config import cloud_storage_enabled

        return bool(cloud_storage_enabled())
    except ImportError:
        return False
