"""Shared live draft room document — board, clock, rosters visible to all participants.

Phase 1 multi-user foundation. Reuses the existing ``live_draft_room`` shape so
pick engines, board sync, and AMI board context work without rewrites.
"""

from __future__ import annotations

import copy
import json
import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    repair_stale_live_draft_progress,
    room_from_persist_dict,
    room_to_persist_dict,
)

DATA_DIR = Path(__file__).resolve().parent / "data" / "draft_rooms"
ROOM_CODE_LEN = 6
ROOM_CODE_ALPHABET = string.ascii_uppercase + string.digits

SHARED_ROOM_META_KEY = "draft_room_shared_meta"
ACTIVE_SHARED_ROOM_CODE_KEY = "active_shared_draft_room_code"
PARTICIPANT_MEMBERSHIP_KEY = "draft_room_participant_membership"

_PRIVATE_DOCUMENT_KEYS = frozenset(
    {
        "draft_queue",
        "queue",
        "watchlist",
        "watchlist_focus",
        "watchlist_favorites",
        "workflow",
        "notes",
        "tracked_players",
        "draft_room_participant_state",
        "draft_assistant_focus_players",
        "workflow_recently_viewed",
    }
)

_PARTICIPANT_PUBLIC_KEYS = frozenset({"assigned_team", "display_name", "joined_at", "participant_id"})


def shared_room_document_private_leaks(document: dict[str, Any] | None, *, prefix: str = "") -> list[str]:
    """Return dotted paths of private participant fields present in a shared room document."""
    if not isinstance(document, dict):
        return []
    leaks: list[str] = []
    for key in document:
        path = f"{prefix}.{key}" if prefix else str(key)
        if key in _PRIVATE_DOCUMENT_KEYS:
            leaks.append(path)
            continue
        val = document[key]
        if key == "participants" and isinstance(val, dict):
            for pid, meta in val.items():
                if isinstance(meta, dict):
                    for sub_key in meta:
                        sub_path = f"{path}.{pid}.{sub_key}"
                        if sub_key in _PRIVATE_DOCUMENT_KEYS:
                            leaks.append(sub_path)
        elif key == "room" and isinstance(val, dict):
            leaks.extend(shared_room_document_private_leaks(val, prefix=path))
        elif isinstance(val, dict):
            leaks.extend(shared_room_document_private_leaks(val, prefix=path))
    return leaks


def sanitize_shared_room_document(document: dict[str, Any]) -> dict[str, Any]:
    """Strip private participant strategy fields and coerce to strict JSON-safe values."""
    if not isinstance(document, dict):
        return {}
    out = copy.deepcopy(document)
    for key in _PRIVATE_DOCUMENT_KEYS:
        out.pop(key, None)
    participants = out.get("participants")
    if isinstance(participants, dict):
        cleaned: dict[str, Any] = {}
        for pid, meta in participants.items():
            if not isinstance(meta, dict):
                continue
            cleaned[str(pid)] = {k: meta[k] for k in _PARTICIPANT_PUBLIC_KEYS if k in meta}
        out["participants"] = cleaned
    room = out.get("room")
    if isinstance(room, dict):
        for key in _PRIVATE_DOCUMENT_KEYS:
            room.pop(key, None)
        try:
            from live_draft_state import is_runtime_room, room_to_persist_dict

            if is_runtime_room(room):
                out["room"] = room_to_persist_dict(room, compact_pool=True)
        except ImportError:
            pass
    try:
        from draft_room_json_sanitize import sanitize_shared_room_json

        sanitized = sanitize_shared_room_json(out)
        return sanitized if isinstance(sanitized, dict) else {}
    except ImportError:
        return out


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def generate_room_code(*, exists: Callable[[str], bool] | None = None) -> str:
    """Create a short join code, optionally avoiding collisions."""
    checker = exists or (lambda _code: False)
    for _ in range(64):
        code = "".join(random.SystemRandom().choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LEN))
        if not checker(code):
            return code
    raise RuntimeError("Unable to allocate unique draft room code")


def shared_room_document(
    *,
    room_code: str,
    host_participant_id: str,
    live_room: dict[str, Any],
    revision: int = 1,
) -> dict[str, Any]:
    """Wrap canonical live draft blob with multiplayer metadata."""
    blob = room_to_persist_dict(live_room, compact_pool=True) if live_room.get("pool") is not None else copy.deepcopy(live_room)
    blob.pop("pool", None)
    return {
        "schema_version": 1,
        "room_code": str(room_code).strip().upper(),
        "draft_room_id": str(live_room.get("draft_room_id") or room_code).strip(),
        "revision": int(revision or 1),
        "status": str(live_room.get("status") or "not_started"),
        "host_participant_id": str(host_participant_id),
        "updated_at": _utc_now_iso(),
        "room": blob,
    }


def document_to_runtime_room(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rebuild runtime ``live_draft_room`` from a shared room document."""
    if not isinstance(document, dict):
        return None
    room_blob = document.get("room")
    if not isinstance(room_blob, dict):
        return None
    runtime = room_from_persist_dict(copy.deepcopy(room_blob))
    if not isinstance(runtime, dict):
        return None
    runtime["draft_room_id"] = str(document.get("draft_room_id") or document.get("room_code") or "")
    meta = dict(runtime.get("meta") or {})
    sync = dict(meta.get("sync") or {})
    sync["revision"] = int(document.get("revision") or 1)
    sync["room_code"] = str(document.get("room_code") or "")
    sync["storage_backend"] = str(document.get("_storage_backend") or sync.get("storage_backend") or "shared_room")
    meta["sync"] = sync
    runtime["meta"] = meta
    return runtime


def bump_revision(document: dict[str, Any], *, live_room: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return an updated shared document after a pick or settings change."""
    out = copy.deepcopy(document)
    out["revision"] = int(out.get("revision") or 0) + 1
    out["updated_at"] = _utc_now_iso()
    if live_room is not None:
        out["room"] = room_to_persist_dict(live_room, compact_pool=True)
        out["status"] = str(live_room.get("status") or out.get("status") or "")
    return out


@runtime_checkable
class SharedRoomStore(Protocol):
    def exists(self, room_code: str) -> bool: ...

    def load(self, room_code: str) -> dict[str, Any] | None: ...

    def load_head(self, room_code: str) -> dict[str, Any] | None: ...

    def save(self, document: dict[str, Any]) -> dict[str, Any]: ...

    def save_if_revision(
        self,
        document: dict[str, Any],
        *,
        expected_revision: int | None,
    ) -> tuple[bool, dict[str, Any] | None]: ...


class LocalFileSharedRoomStore:
    """Dev/test backend — one JSON file per room code."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DATA_DIR

    def _path(self, room_code: str) -> Path:
        code = str(room_code or "").strip().upper()
        return self.root / f"{code}.json"

    def exists(self, room_code: str) -> bool:
        return self._path(room_code).is_file()

    def load(self, room_code: str) -> dict[str, Any] | None:
        result = self.load_with_diagnostics(room_code)
        doc = result.get("document")
        return doc if isinstance(doc, dict) else None

    def load_with_diagnostics(self, room_code: str) -> dict[str, Any]:
        code = str(room_code or "").strip().upper()
        if not code:
            return {
                "found": False,
                "document": None,
                "reason": "invalid_code",
                "query_error": None,
                "backend": "local_file",
                "room_code_queried": "",
            }
        path = self._path(code)
        if not path.is_file():
            return {
                "found": False,
                "document": None,
                "reason": "not_found",
                "query_error": None,
                "backend": "local_file",
                "room_code_queried": code,
            }
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "found": False,
                "document": None,
                "reason": "query_error",
                "query_error": str(exc),
                "backend": "local_file",
                "room_code_queried": code,
            }
        if not isinstance(raw, dict):
            return {
                "found": False,
                "document": None,
                "reason": "invalid_row",
                "query_error": None,
                "backend": "local_file",
                "room_code_queried": code,
            }
        return {
            "found": True,
            "document": raw,
            "reason": None,
            "query_error": None,
            "backend": "local_file",
            "room_code_queried": code,
        }

    def load_head(self, room_code: str) -> dict[str, Any] | None:
        path = self._path(room_code)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return {
            "room_code": str(raw.get("room_code") or room_code).upper(),
            "revision": int(raw.get("revision") or 1),
            "status": str(raw.get("status") or ""),
            "updated_at": str(raw.get("updated_at") or ""),
        }

    def save(self, document: dict[str, Any]) -> dict[str, Any]:
        code = str(document.get("room_code") or "").strip().upper()
        if not code:
            raise ValueError("shared room document missing room_code")
        payload = sanitize_shared_room_document(document)
        payload["_storage_backend"] = "local_file"
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(code)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def save_if_revision(
        self,
        document: dict[str, Any],
        *,
        expected_revision: int | None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Optimistic concurrency — refuse stale writes."""
        code = str(document.get("room_code") or "").strip().upper()
        current = self.load(code)
        if current is None:
            self.save(document)
            return True, document
        current_rev = int(current.get("revision") or 0)
        if expected_revision is not None and current_rev != int(expected_revision):
            return False, current
        self.save(document)
        return True, document


_DEFAULT_STORE: SharedRoomStore | None = None
_LOCAL_STORE: LocalFileSharedRoomStore | None = None


def get_local_shared_room_store() -> LocalFileSharedRoomStore:
    global _LOCAL_STORE
    if _LOCAL_STORE is None:
        _LOCAL_STORE = LocalFileSharedRoomStore()
    return _LOCAL_STORE


def shared_room_backend_name() -> str:
    import os

    explicit = os.environ.get("BASEBALL_SHARED_DRAFT_ROOM_BACKEND", "").strip().lower()
    if explicit in ("local", "file"):
        return "local_file"
    if explicit == "supabase":
        return "supabase"
    try:
        from draft_room_supabase_store import supabase_shared_room_backend_available

        if supabase_shared_room_backend_available():
            return "supabase"
    except ImportError:
        pass
    return "local_file"


def get_shared_room_store() -> SharedRoomStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is not None:
        return _DEFAULT_STORE
    if shared_room_backend_name() == "supabase":
        try:
            from draft_room_supabase_store import get_supabase_shared_room_store

            _DEFAULT_STORE = get_supabase_shared_room_store()
            return _DEFAULT_STORE
        except Exception:
            pass
    _DEFAULT_STORE = get_local_shared_room_store()
    return _DEFAULT_STORE


def reset_shared_room_store_for_tests(store: SharedRoomStore | None = None) -> None:
    """Test helper — inject store backend or reset factory cache."""
    global _DEFAULT_STORE
    _DEFAULT_STORE = store


def create_shared_room(
    live_room: dict[str, Any],
    *,
    host_participant_id: str,
    store: SharedRoomStore | None = None,
) -> dict[str, Any]:
    """Persist a new shared room and return the shared document."""
    backend = store or get_shared_room_store()
    code = generate_room_code(exists=backend.exists)
    document = shared_room_document(
        room_code=code,
        host_participant_id=host_participant_id,
        live_room=live_room,
        revision=1,
    )
    document["created_at"] = _utc_now_iso()
    try:
        from suite_user import get_account_user_id

        document["host_user_id"] = str(get_account_user_id() or "")
    except ImportError:
        document["host_user_id"] = ""
    document["_storage_backend"] = shared_room_backend_name()
    saved = backend.save(document)
    return saved


def load_shared_room(room_code: str, *, store: SharedRoomStore | None = None) -> dict[str, Any] | None:
    backend = store or get_shared_room_store()
    return backend.load(str(room_code or "").strip().upper())


def _merge_runtime_pool(existing: dict[str, Any], runtime: dict[str, Any]) -> None:
    """Keep richer scoring columns from the local pool when a compact shared sync is thinner."""
    import pandas as pd

    existing_pool = existing.get("pool")
    incoming = runtime.get("pool")
    if not isinstance(incoming, pd.DataFrame) or incoming.empty:
        return
    if not isinstance(existing_pool, pd.DataFrame) or existing_pool.empty:
        return
    if "playerID" not in incoming.columns or "playerID" not in existing_pool.columns:
        return
    try:
        from draft_scoring_pool import LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS, _RANK_DEFAULT
    except ImportError:
        return

    ex = existing_pool.copy()
    inc = incoming.copy()
    ex["playerID"] = ex["playerID"].astype(str)
    inc["playerID"] = inc["playerID"].astype(str)
    ex = ex.set_index("playerID")
    inc = inc.set_index("playerID")
    shared_ids = inc.index.intersection(ex.index)
    if shared_ids.empty:
        return
    for col in LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS:
        if col not in ex.columns:
            continue
        if col not in inc.columns:
            inc[col] = ex[col]
            continue
        inc_vals = pd.to_numeric(inc[col], errors="coerce") if col != "Primary Position" else inc[col]
        if col in ("Model Rank", "Market Rank"):
            bad = inc_vals.isna() | inc_vals.ge(_RANK_DEFAULT)
        elif col == "Fantasy Edge":
            bad = inc_vals.isna() | inc_vals.eq(0)
        else:
            bad = inc_vals.isna() if hasattr(inc_vals, "isna") else inc[col].isna()
        if bad.any():
            inc.loc[bad, col] = ex.loc[bad, col]
    runtime["pool"] = inc.reset_index()


def publish_shared_room_runtime(
    session: dict[str, Any],
    document: dict[str, Any],
    *,
    reason: str = "shared_room_sync",
) -> dict[str, Any] | None:
    """Mirror shared room document into session runtime keys used by existing engines."""
    try:
        from draft_room_create_verify import validate_shared_room_document

        ok, err = validate_shared_room_document(document)
        if not ok:
            session["_draft_room_publish_error"] = err
            if reason in ("shared_room_poll", "global_context_prepare"):
                existing = session.get(LIVE_DRAFT_ROOM_KEY)
                return existing if isinstance(existing, dict) else None
            return None
    except ImportError:
        pass

    runtime = document_to_runtime_room(document)
    if runtime is None:
        session["_draft_room_publish_error"] = "Shared room JSON could not be converted to a live draft room."
        existing = session.get(LIVE_DRAFT_ROOM_KEY)
        if reason in ("shared_room_poll", "global_context_prepare") and isinstance(existing, dict):
            return existing
        return None

    repair_stale_live_draft_progress(runtime)
    doc_status = str(document.get("status") or "").strip()
    if doc_status and doc_status != str(runtime.get("status") or "").strip():
        if doc_status == "closed":
            runtime["status"] = "complete"
        elif doc_status in ("in_progress", "paused", "not_started", "complete"):
            runtime["status"] = doc_status

    existing = session.get(LIVE_DRAFT_ROOM_KEY)
    if (
        reason in ("shared_room_poll", "global_context_prepare")
        and isinstance(existing, dict)
        and len(existing.get("draft_board") or []) > len(runtime.get("draft_board") or [])
    ):
        return existing

    if isinstance(existing, dict):
        _merge_runtime_pool(existing, runtime)

    session.pop("_draft_room_publish_error", None)
    session[LIVE_DRAFT_ROOM_KEY] = runtime
    session[ACTIVE_SHARED_ROOM_CODE_KEY] = str(document.get("room_code") or "").strip().upper()
    meta = {
        "room_code": document.get("room_code"),
        "revision": document.get("revision"),
        "updated_at": document.get("updated_at"),
        "last_sync_at": _utc_now_iso(),
        "reason": reason,
        "storage_backend": shared_room_backend_name(),
    }
    session[SHARED_ROOM_META_KEY] = meta
    if reason not in ("shared_room_poll",):
        try:
            from live_draft_state import write_canonical_live_draft_state

            write_canonical_live_draft_state(session, runtime, reason=reason)
        except ImportError:
            pass
    return runtime


def commit_shared_room_pick(
    session: dict[str, Any],
    live_room: dict[str, Any],
    *,
    expected_revision: int | None = None,
    store: SharedRoomStore | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Write pick to shared store with revision check, then refresh session."""
    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if not code:
        return False, None
    backend = store or get_shared_room_store()
    current = backend.load(code)
    if not isinstance(current, dict):
        return False, None
    updated = bump_revision(current, live_room=live_room)
    ok, saved = backend.save_if_revision(updated, expected_revision=expected_revision)
    if not ok or saved is None:
        if isinstance(saved, dict):
            publish_shared_room_runtime(session, saved, reason="shared_room_conflict")
        return False, saved
    publish_shared_room_runtime(session, saved, reason="shared_room_pick")
    return True, saved
