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
SHARED_DOC_SOFT_CACHE_KEY = "_shared_room_doc_soft_cache"
LEFT_PARTICIPANTS_KEY = "left_participants"
REJOINED_PARTICIPANTS_KEY = "rejoined_participants"
LEAVE_REJOIN_GENERATION_KEY = "leave_rejoin_generation"

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

# Never persist reconstructible / heavy scoring payloads on the shared wire.
_SHARED_ROOM_HEAVY_KEYS = frozenset(
    {
        "pool",
        "pool_records",
        "pool_columns",
        "recommendations",
        "top_rec",
        "best_avail",
        "pos_fit",
        "value_sleep",
        "_live_draft_rec_cache",
        "available_df",
        "player_photos",
        "photos",
        "headshots",
    }
)


def strip_shared_room_heavy_payload(room_blob: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only canonical shared draft state — drop pools and derived tables."""
    if not isinstance(room_blob, dict):
        return {}
    out = dict(room_blob)
    for key in _SHARED_ROOM_HEAVY_KEYS:
        out.pop(key, None)
    out.pop("pool", None)
    return out

_PARTICIPANT_PUBLIC_KEYS = frozenset(
    {
        "assigned_team",
        "display_name",
        "joined_at",
        "last_seen_at",
        "participant_id",
        "user_id",
        "account_user_id",
        "external_id",
        "email",
        "workspace_id",
        "seat_kind",
        "team_kind",
        "is_cpu",
    }
)


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
                out["room"] = strip_shared_room_heavy_payload(
                    room_to_persist_dict(room, compact_pool=True)
                )
            else:
                out["room"] = strip_shared_room_heavy_payload(room)
        except ImportError:
            out["room"] = strip_shared_room_heavy_payload(room)
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
    blob = strip_shared_room_heavy_payload(blob)
    # Guarantee team list on the shared document so guest open-team lookup cannot
    # diverge from the host session lobby (empty document.room.teams → "No teams").
    try:
        from live_draft_team_ownership import list_room_teams

        teams = list_room_teams(blob) or list_room_teams(live_room)
        if teams:
            blob["teams"] = list(teams)
            cfg = dict(blob.get("config") or {})
            cfg["teams"] = list(teams)
            cfg.setdefault("num_teams", len(teams))
            blob["config"] = cfg
    except ImportError:
        pass
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


def shared_document_room_blob(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Persisted live-draft room payload inside a shared room document."""
    if not isinstance(document, dict):
        return None
    room = document.get("room")
    if isinstance(room, dict):
        return room
    legacy = document.get("live_room")
    return legacy if isinstance(legacy, dict) else None


def document_to_runtime_room(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rebuild runtime ``live_draft_room`` from a shared room document."""
    if not isinstance(document, dict):
        return None
    room_blob = shared_document_room_blob(document)
    if not isinstance(room_blob, dict):
        return None
    runtime = room_from_persist_dict(copy.deepcopy(room_blob))
    if not isinstance(runtime, dict):
        return None
    room_code = str(document.get("room_code") or "").strip().upper()
    runtime["draft_room_id"] = str(document.get("draft_room_id") or room_code or "")
    # Stamp share code on every common reader path (top-level, config, meta.sync, sync).
    if room_code:
        runtime["room_code"] = room_code
        runtime["share_code"] = room_code
        cfg = dict(runtime.get("config") or {})
        cfg["share_code"] = room_code
        cfg["room_code"] = room_code
        runtime["config"] = cfg
    meta = dict(runtime.get("meta") or {})
    sync = dict(meta.get("sync") or {})
    sync["revision"] = int(document.get("revision") or 1)
    sync["room_code"] = room_code
    sync["storage_backend"] = str(document.get("_storage_backend") or sync.get("storage_backend") or "shared_room")
    meta["sync"] = sync
    runtime["meta"] = meta
    runtime["sync"] = dict(sync)
    return runtime


def bump_revision(document: dict[str, Any], *, live_room: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return an updated shared document after a pick or settings change."""
    out = copy.deepcopy(document)
    out["revision"] = int(out.get("revision") or 0) + 1
    out["updated_at"] = _utc_now_iso()
    if live_room is not None:
        out["room"] = strip_shared_room_heavy_payload(
            room_to_persist_dict(live_room, compact_pool=True)
        )
        out["status"] = str(live_room.get("status") or out.get("status") or "")
    elif isinstance(out.get("room"), dict):
        out["room"] = strip_shared_room_heavy_payload(out.get("room"))
    return out


def preserve_shared_room_chat(
    outgoing: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep the newer chat sidecar when board/settings writers use a stale soft-cached doc.

    Live Draft Chat updates ``chat`` / ``chat_revision`` without bumping board ``revision``.
    Soft-cached pick commits must not wipe messages.
    """
    if not isinstance(outgoing, dict):
        return {}
    if not isinstance(existing, dict):
        return outgoing
    existing_chat = existing.get("chat")
    if not isinstance(existing_chat, dict):
        return outgoing
    out_chat = outgoing.get("chat")
    try:
        existing_rev = int(existing_chat.get("chat_revision") or 0)
    except (TypeError, ValueError):
        existing_rev = 0
    try:
        out_rev = int(out_chat.get("chat_revision") or 0) if isinstance(out_chat, dict) else 0
    except (TypeError, ValueError):
        out_rev = 0
    if existing_rev > out_rev or (existing_rev == out_rev and not isinstance(out_chat, dict)):
        merged = copy.deepcopy(outgoing)
        merged["chat"] = copy.deepcopy(existing_chat)
        return merged
    return outgoing


def normalize_left_participants(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize the durable leave ledger that blocks seat resurrection on merge."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        pid = str(key or "").strip()
        if not pid:
            continue
        if isinstance(val, dict):
            rec = dict(val)
            rec.setdefault("participant_id", pid)
            out[pid] = rec
        else:
            out[pid] = {"participant_id": pid, "left_at": str(val or "")}
    return out


def _left_participant_ids(*maps: Any) -> set[str]:
    ids: set[str] = set()
    for raw in maps:
        for pid, rec in normalize_left_participants(raw).items():
            ids.add(str(pid).strip())
            if isinstance(rec, dict):
                for key in ("participant_id", "user_id", "account_user_id"):
                    alias = str(rec.get(key) or "").strip()
                    if alias:
                        ids.add(alias)
    ids.discard("")
    return ids


def _int_generation(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def document_leave_rejoin_generation(document: dict[str, Any] | None) -> int:
    """Highest causal leave/rejoin generation present on a document."""
    if not isinstance(document, dict):
        return 0
    n = _int_generation(document.get(LEAVE_REJOIN_GENERATION_KEY))
    for rec in normalize_left_participants(document.get(LEFT_PARTICIPANTS_KEY)).values():
        n = max(n, _int_generation((rec or {}).get("leave_generation")))
    for rec in normalize_left_participants(document.get(REJOINED_PARTICIPANTS_KEY)).values():
        n = max(n, _int_generation((rec or {}).get("rejoin_generation")))
    return n


def next_leave_rejoin_generation(document: dict[str, Any] | None) -> int:
    return document_leave_rejoin_generation(document) + 1


def merge_left_ledgers(*maps: Any) -> dict[str, dict[str, Any]]:
    """Union leave ledgers, keeping the higher leave_generation per id."""
    combined: dict[str, dict[str, Any]] = {}
    for raw in maps:
        for pid, rec in normalize_left_participants(raw).items():
            prev = combined.get(pid)
            if prev is None or _int_generation((rec or {}).get("leave_generation")) >= _int_generation(
                (prev or {}).get("leave_generation")
            ):
                combined[pid] = rec
    return combined


def record_shared_room_participant_left(
    document: dict[str, Any],
    participant_id: str,
    *,
    aliases: Any = (),
    released_team: str = "",
    left_at: str = "",
) -> dict[str, Any]:
    """Stamp an explicit leave so later stale saves cannot resurrect the seat."""
    if not isinstance(document, dict):
        return {}
    pid = str(participant_id or "").strip()
    if not pid:
        return document
    stamp = str(left_at or "").strip() or _utc_now_iso()
    generation = next_leave_rejoin_generation(document)
    left = normalize_left_participants(document.get(LEFT_PARTICIPANTS_KEY))
    tokens = {pid}
    for raw in aliases or ():
        token = str(raw or "").strip()
        if token:
            tokens.add(token)
    for token in tokens:
        rec = dict(left.get(token) or {})
        rec["participant_id"] = pid
        rec["left_at"] = stamp
        rec["leave_generation"] = generation
        if released_team:
            rec["released_team"] = str(released_team).strip()
        left[token] = rec
    document[LEFT_PARTICIPANTS_KEY] = left
    document[LEAVE_REJOIN_GENERATION_KEY] = generation
    # A later leave supersedes any prior rejoin marker for these ids.
    rejoined = normalize_left_participants(document.get(REJOINED_PARTICIPANTS_KEY))
    token_l = {t.lower() for t in tokens}
    for key in list(rejoined.keys()):
        rec = rejoined.get(key) or {}
        rec_pid = str((rec or {}).get("participant_id") or "").strip().lower()
        if str(key).strip().lower() in token_l or rec_pid in token_l or rec_pid == pid.lower():
            rejoined.pop(key, None)
    document[REJOINED_PARTICIPANTS_KEY] = rejoined
    return document


def clear_shared_room_participant_left(
    document: dict[str, Any],
    participant_id: str,
    *,
    aliases: Any = (),
) -> dict[str, Any]:
    """Explicit rejoin: clear leave ledger entries and stamp a rejoin marker.

    Merge honors this stamp — not mere presence of the participant on an
    arbitrary outgoing save — so a stale host document cannot resurrect a seat.
    The marker carries a monotonic generation greater than the leave it cleared,
    so a replayed prior-rejoin document cannot beat a later leave.
    """
    if not isinstance(document, dict):
        return {}
    pid = str(participant_id or "").strip()
    tokens = {pid.lower()}
    for raw in aliases or ():
        token = str(raw or "").strip().lower()
        if token:
            tokens.add(token)
    tokens.discard("")
    left = normalize_left_participants(document.get(LEFT_PARTICIPANTS_KEY))
    generation_floor = document_leave_rejoin_generation(document)
    cleared_any = False
    for key in list(left.keys()):
        rec = left.get(key) or {}
        rec_pid = str((rec or {}).get("participant_id") or "").strip().lower()
        if str(key).strip().lower() in tokens or rec_pid in tokens:
            left.pop(key, None)
            cleared_any = True
    document[LEFT_PARTICIPANTS_KEY] = left
    if not cleared_any:
        # First join is not a rejoin — do not stamp a marker that can beat a later leave.
        return document
    generation = generation_floor + 1
    stamp = _utc_now_iso()
    rejoined = normalize_left_participants(document.get(REJOINED_PARTICIPANTS_KEY))
    for token in {pid, *[str(a).strip() for a in (aliases or ()) if str(a).strip()]}:
        rec = dict(rejoined.get(token) or {})
        rec["participant_id"] = pid
        rec["rejoined_at"] = stamp
        rec["rejoin_generation"] = generation
        rejoined[token] = rec
    document[REJOINED_PARTICIPANTS_KEY] = rejoined
    document[LEAVE_REJOIN_GENERATION_KEY] = generation
    return document


def preserve_shared_room_participants(
    outgoing: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge participants + joined_participants so stale host saves cannot drop guests.

    Exception: terminal rooms (deleted/ended/closed) must keep the outgoing
    participant wipe. Merging existing seats back was the deployed End/Delete
    failure mode — status became deleted while memberships stayed alive, and
    local clients kept drafting against the resurrected seat map.

    Explicit leaves are a second exception: ``left_participants`` is a durable
    ledger so a guest Leave is not undone by the stale-host merge.

    A later save that still lists the guest is **not** a rejoin. Only
    ``clear_shared_room_participant_left`` (the registration path) stamps
    ``rejoined_participants``. That marker wins only when its monotonic
    ``rejoin_generation`` is strictly greater than the leave it would clear.
    A replayed prior-rejoin document cannot beat a later leave.
    """
    if not isinstance(outgoing, dict):
        return {}
    if not isinstance(existing, dict):
        return outgoing
    out_status = str(outgoing.get("status") or "").strip().lower()
    if out_status in ("deleted", "ended", "closed") or outgoing.get("deletion_generation"):
        return outgoing
    room_blob = outgoing.get("room") if isinstance(outgoing.get("room"), dict) else {}
    if str(room_blob.get("status") or "").strip().lower() in ("deleted", "ended", "closed"):
        return outgoing

    merged = copy.deepcopy(outgoing)

    existing_parts = dict(existing.get("participants") or {})
    outgoing_parts = dict(outgoing.get("participants") or {})
    left = merge_left_ledgers(existing.get(LEFT_PARTICIPANTS_KEY), outgoing.get(LEFT_PARTICIPANTS_KEY))
    # Only the writer that called clear_shared_room_participant_left may
    # resurrect a seat. Existing rejoin markers are stale-host/first-join noise.
    # Outgoing markers still lose when their generation is not strictly later
    # than the current leave (replayed prior-rejoin after a second leave).
    rejoined = normalize_left_participants(outgoing.get(REJOINED_PARTICIPANTS_KEY))

    def _rejoin_generation_for(pid: str, rec: dict[str, Any]) -> int:
        target = {
            str(pid or "").strip().lower(),
            str((rec or {}).get("participant_id") or "").strip().lower(),
        }
        target.discard("")
        latest = 0
        for rpid, rrec in rejoined.items():
            aliases = {
                str(rpid or "").strip().lower(),
                str((rrec or {}).get("participant_id") or "").strip().lower(),
            }
            aliases.discard("")
            if target & aliases:
                latest = max(latest, _int_generation((rrec or {}).get("rejoin_generation")))
        return latest

    # Explicit rejoin wins only when its generation is strictly later than the leave.
    # Presence on outgoing_parts or a replayed older rejoin marker must not drop it.
    for pid in list(left.keys()):
        rec = left.get(pid) or {}
        leave_gen = _int_generation((rec or {}).get("leave_generation"))
        rejoin_gen = _rejoin_generation_for(pid, rec)
        if rejoin_gen > leave_gen:
            left.pop(pid, None)

    left_ids = {str(pid).strip().lower() for pid in _left_participant_ids(left)}
    merged[LEFT_PARTICIPANTS_KEY] = left
    for rpid in list(rejoined.keys()):
        if str(rpid).strip().lower() in left_ids:
            rejoined.pop(rpid, None)
    merged[REJOINED_PARTICIPANTS_KEY] = rejoined
    merged[LEAVE_REJOIN_GENERATION_KEY] = max(
        document_leave_rejoin_generation(existing),
        document_leave_rejoin_generation(outgoing),
        document_leave_rejoin_generation(merged),
    )

    combined: dict[str, Any] = {}
    for pid, meta in existing_parts.items():
        if str(pid).strip().lower() in left_ids:
            continue
        if isinstance(meta, dict):
            combined[str(pid)] = copy.deepcopy(meta)
    for pid, meta in outgoing_parts.items():
        if not isinstance(meta, dict):
            continue
        if str(pid).strip().lower() in left_ids:
            continue
        prev = combined.get(str(pid))
        if isinstance(prev, dict):
            entry = dict(prev)
            entry.update({k: v for k, v in meta.items() if v not in (None, "")})
            # Prefer non-empty assigned_team from either side.
            team = str(meta.get("assigned_team") or prev.get("assigned_team") or "").strip()
            if team:
                entry["assigned_team"] = team
            combined[str(pid)] = entry
        else:
            combined[str(pid)] = copy.deepcopy(meta)
    merged["participants"] = combined

    claims = merged.get("team_claims")
    if isinstance(claims, dict):
        released = {
            str((rec or {}).get("released_team") or "").strip()
            for rec in left.values()
            if isinstance(rec, dict)
        }
        released.discard("")
        for team in list(claims.keys()):
            owner = claims.get(team)
            owner_id = (
                str(owner).strip()
                if not isinstance(owner, dict)
                else str(owner.get("participant_id") or owner.get("user_id") or "").strip()
            )
            if team in released or owner_id.lower() in left_ids:
                claims.pop(team, None)
        merged["team_claims"] = claims

    try:
        from live_draft_presence import JOINED_PARTICIPANTS_KEY, merge_joined_participants

        joined = merge_joined_participants(outgoing, existing)
        for uid in list(joined.keys()):
            if str(uid).strip().lower() in left_ids:
                joined.pop(uid, None)
        merged[JOINED_PARTICIPANTS_KEY] = joined
    except ImportError:
        existing_joined = existing.get("joined_participants")
        if isinstance(existing_joined, dict) and existing_joined:
            out_joined = outgoing.get("joined_participants")
            if not isinstance(out_joined, dict) or not out_joined:
                merged["joined_participants"] = {
                    uid: copy.deepcopy(meta)
                    for uid, meta in existing_joined.items()
                    if str(uid).strip().lower() not in left_ids
                }

    return merged


def preserve_shared_room_timer_authority(
    outgoing: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep the newer timer_authority lease when board writers omit it."""
    if not isinstance(outgoing, dict):
        return {}
    if not isinstance(existing, dict):
        return outgoing
    existing_auth = existing.get("timer_authority")
    out_auth = outgoing.get("timer_authority")
    if not isinstance(existing_auth, dict):
        return outgoing
    if not isinstance(out_auth, dict):
        merged = copy.deepcopy(outgoing)
        merged["timer_authority"] = copy.deepcopy(existing_auth)
        return merged
    try:
        existing_lease = float(existing_auth.get("lease_expires_at") or 0)
    except (TypeError, ValueError):
        existing_lease = 0.0
    try:
        out_lease = float(out_auth.get("lease_expires_at") or 0)
    except (TypeError, ValueError):
        out_lease = 0.0
    if existing_lease > out_lease:
        merged = copy.deepcopy(outgoing)
        merged["timer_authority"] = copy.deepcopy(existing_auth)
        return merged
    return outgoing


def preserve_shared_room_sidecars(
    outgoing: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Preserve chat + participants + timer authority when writing a potentially stale document.

    Terminal deletions skip participant/chat/timer resurrection entirely.
    """
    if not isinstance(outgoing, dict):
        return {}
    out_status = str(outgoing.get("status") or "").strip().lower()
    if out_status in ("deleted", "ended", "closed") or outgoing.get("deletion_generation"):
        return outgoing
    return preserve_shared_room_timer_authority(
        preserve_shared_room_chat(
            preserve_shared_room_participants(outgoing, existing),
            existing,
        ),
        existing,
    )


@runtime_checkable
class SharedRoomStore(Protocol):
    def exists(self, room_code: str) -> bool: ...

    def load(self, room_code: str) -> dict[str, Any] | None: ...

    def load_head(self, room_code: str) -> dict[str, Any] | None: ...

    def load_chat_sidecar(self, room_code: str) -> dict[str, Any] | None: ...

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
        head = {
            "room_code": str(raw.get("room_code") or room_code).upper(),
            "revision": int(raw.get("revision") or 1),
            "status": str(raw.get("status") or ""),
            "updated_at": str(raw.get("updated_at") or ""),
        }
        try:
            from live_draft_timer_authority import extract_live_head_fields

            head.update(extract_live_head_fields(raw))
            head["revision"] = int(head.get("room_revision") or head.get("revision") or 1)
        except ImportError:
            room = raw.get("room") if isinstance(raw.get("room"), dict) else {}
            if isinstance(room, dict):
                head["current_pick_index"] = int(room.get("current_pick_index") or 0)
                head["timer_deadline"] = room.get("timer_deadline")
        return head

    def load_chat_sidecar(self, room_code: str) -> dict[str, Any] | None:
        """Chat + lightweight membership — never a full shared_room_json download."""
        doc = self.load(room_code)
        if not isinstance(doc, dict):
            return None
        chat = doc.get("chat") if isinstance(doc.get("chat"), dict) else {}
        joined = doc.get("joined_participants") if isinstance(doc.get("joined_participants"), dict) else {}
        participants = doc.get("participants") if isinstance(doc.get("participants"), dict) else {}
        return {
            "room_code": str(doc.get("room_code") or room_code).upper(),
            "revision": int(doc.get("revision") or 0),
            "status": str(doc.get("status") or ""),
            "updated_at": str(doc.get("updated_at") or ""),
            "host_user_id": str(doc.get("host_user_id") or ""),
            "host_participant_id": str(doc.get("host_participant_id") or ""),
            "joined_participants": copy.deepcopy(joined),
            "participants": copy.deepcopy(participants),
            "chat": copy.deepcopy(chat),
            "_egress_kind": "chat_sidecar",
        }

    def save(self, document: dict[str, Any]) -> dict[str, Any]:
        code = str(document.get("room_code") or "").strip().upper()
        if not code:
            raise ValueError("shared room document missing room_code")
        existing = None
        path = self._path(code)
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                existing = raw if isinstance(raw, dict) else None
            except (OSError, json.JSONDecodeError):
                existing = None
        payload = sanitize_shared_room_document(preserve_shared_room_sidecars(document, existing))
        payload["_storage_backend"] = "local_file"
        self.root.mkdir(parents=True, exist_ok=True)
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
            saved = self.save(document)
            return True, saved
        current_rev = int(current.get("revision") or 0)
        if expected_revision is not None and current_rev != int(expected_revision):
            return False, current
        saved = self.save(preserve_shared_room_sidecars(document, current))
        return True, saved


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


def load_shared_room_document(
    session: dict[str, Any] | None,
    room_code: str,
    *,
    force: bool = False,
    max_age_sec: float = 2.0,
    store: SharedRoomStore | None = None,
) -> dict[str, Any] | None:
    """Load shared room doc with a short session soft-cache to avoid triple network reads on autopick."""
    code = str(room_code or "").strip().upper()
    if not code:
        return None
    now = datetime.now(timezone.utc).timestamp()
    # During active expiration, prefer a fresher head so guests do not sit on stale soft cache.
    try:
        if isinstance(session, dict):
            room = session.get("live_draft_room")
            if isinstance(room, dict) and str(room.get("status") or "") == "in_progress":
                dl = room.get("timer_deadline")
                if dl is not None and float(dl) <= now + 1.5:
                    max_age_sec = min(float(max_age_sec), 0.35)
    except Exception:
        pass
    if isinstance(session, dict) and not force:
        cache = session.get(SHARED_DOC_SOFT_CACHE_KEY)
        if isinstance(cache, dict) and str(cache.get("room_code") or "") == code:
            try:
                age = now - float(cache.get("loaded_at") or 0)
            except (TypeError, ValueError):
                age = max_age_sec + 1
            if age <= max_age_sec and isinstance(cache.get("document"), dict):
                return cache["document"]
    backend = store or get_shared_room_store()
    document = backend.load(code)
    if isinstance(session, dict):
        session[SHARED_DOC_SOFT_CACHE_KEY] = {
            "room_code": code,
            "loaded_at": now,
            "document": document if isinstance(document, dict) else None,
        }
    return document if isinstance(document, dict) else None


def peek_shared_room_document_cache(
    session: dict[str, Any] | None,
    room_code: str = "",
) -> dict[str, Any] | None:
    """Return soft-cached shared document without network I/O."""
    if not isinstance(session, dict):
        return None
    code = str(room_code or "").strip().upper()
    cache = session.get(SHARED_DOC_SOFT_CACHE_KEY)
    if not isinstance(cache, dict):
        return None
    if code and str(cache.get("room_code") or "").strip().upper() != code:
        return None
    doc = cache.get("document")
    return doc if isinstance(doc, dict) else None


def invalidate_shared_room_document_cache(session: dict[str, Any] | None, room_code: str = "") -> None:
    if not isinstance(session, dict):
        return
    code = str(room_code or "").strip().upper()
    cache = session.get(SHARED_DOC_SOFT_CACHE_KEY)
    if not code or (isinstance(cache, dict) and str(cache.get("room_code") or "") == code):
        session.pop(SHARED_DOC_SOFT_CACHE_KEY, None)
    # Also drop Supabase GET cache so host lobby polls cannot keep a pre-claim row.
    try:
        from suite_storage_supabase import invalidate_shared_draft_room_read_cache

        invalidate_shared_draft_room_read_cache()
    except ImportError:
        pass


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


def find_shared_room_document_by_draft_room_id(
    draft_room_id: str,
    *,
    store: SharedRoomStore | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve a shared room document from internal draft_room_id (not join code)."""
    rid = str(draft_room_id or "").strip().upper()
    if not rid:
        return None, ""
    backend = store or get_shared_room_store()

    load_by_id = getattr(backend, "load_by_draft_room_id", None)
    if callable(load_by_id):
        doc = load_by_id(rid)
        if isinstance(doc, dict):
            doc_rid = str(doc.get("draft_room_id") or "").strip().upper()
            if doc_rid == rid:
                return doc, "supabase_draft_room_id"

    if hasattr(backend, "root"):
        import json

        root = getattr(backend, "root", None)
        if root is not None:
            for path in root.glob("*.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("draft_room_id") or "").strip().upper() == rid:
                    return raw, "local_file_draft_room_id"

    if len(rid) == ROOM_CODE_LEN:
        doc = backend.load(rid)
        if isinstance(doc, dict):
            doc_rid = str(doc.get("draft_room_id") or "").strip().upper()
            if doc_rid == rid or str(doc.get("room_code") or "").strip().upper() == rid:
                return doc, "shared_room_code"

    return None, ""


def _merge_runtime_pool(existing: dict[str, Any], runtime: dict[str, Any]) -> None:
    """Keep local scoring pool when shared docs omit pools; merge when both exist."""
    import pandas as pd

    existing_pool = existing.get("pool")
    incoming = runtime.get("pool")
    # Egress hotfix: shared documents no longer carry pool_records — preserve local.
    if incoming is None or (isinstance(incoming, pd.DataFrame) and incoming.empty):
        if isinstance(existing_pool, pd.DataFrame) and not existing_pool.empty:
            runtime["pool"] = existing_pool
        return
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
    code = str(
        (document or {}).get("room_code")
        or session.get(ACTIVE_SHARED_ROOM_CODE_KEY)
        or ""
    ).strip().upper()
    draft_id = str((document or {}).get("draft_room_id") or "").strip()
    try:
        from live_draft_termination import is_live_draft_permanently_retired

        if is_live_draft_permanently_retired(
            session, draft_id=draft_id, room_code=code, room=document if isinstance(document, dict) else None
        ):
            session.pop(LIVE_DRAFT_ROOM_KEY, None)
            session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
            session["_draft_room_publish_error"] = "Room was permanently deleted."
            return None
    except ImportError:
        pass
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
        if reason in ("shared_room_poll", "global_context_prepare"):
            existing = session.get(LIVE_DRAFT_ROOM_KEY)
            if isinstance(existing, dict):
                return existing
        return None

    repair_stale_live_draft_progress(runtime)
    try:
        from draft_room_runtime_diagnostics import record_scoring_pipeline_stage

        pool = runtime.get("pool")
        if pool is not None and hasattr(pool, "columns"):
            record_scoring_pipeline_stage(session, "restored", pool)
    except ImportError:
        pass
    try:
        import json

        session["_shared_room_last_payload_bytes"] = len(
            json.dumps(document, ensure_ascii=False, default=str).encode("utf-8")
        )
    except Exception:
        pass
    doc_status = str(document.get("status") or "").strip()
    if doc_status and doc_status != str(runtime.get("status") or "").strip():
        # Terminal shared-room statuses must never hydrate an active/complete live room.
        if doc_status in ("closed", "ended", "deleted"):
            try:
                from live_draft_termination import handle_shared_document_terminal

                if handle_shared_document_terminal(session, document):
                    return None
            except ImportError:
                runtime["status"] = doc_status
        elif doc_status in (
            "in_progress",
            "paused",
            "not_started",
            "waiting",
            "complete",
            "saved_for_later",
            "parked",
        ):
            runtime["status"] = doc_status
            if doc_status in ("saved_for_later", "parked"):
                # Guests must leave the live room when the commissioner parks.
                session["_live_draft_saved_for_later_notice"] = (
                    "The commissioner saved this draft for later. Returning to Draft Setup…"
                )
                # Clear resume-lobby auto-entry so lifecycle parks everyone to setup.
                session.pop("_live_draft_resume_lobby", None)

    existing = session.get(LIVE_DRAFT_ROOM_KEY)
    doc_rev = int(document.get("revision") or 0)
    local_rev = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
    if (
        reason in ("shared_room_poll", "global_context_prepare")
        and isinstance(existing, dict)
        and doc_rev <= local_rev
        and len(existing.get("draft_board") or []) > len(runtime.get("draft_board") or [])
    ):
        return existing

    if isinstance(existing, dict):
        _merge_runtime_pool(existing, runtime)
    try:
        from shared_draft_local_pool import ensure_local_shared_player_pool

        ensure_local_shared_player_pool(session, runtime)
    except ImportError:
        incoming_pool = runtime.get("pool")
        if incoming_pool is None or getattr(incoming_pool, "empty", True):
            fallback = session.get("draft_room_player_pool")
            if fallback is not None and not getattr(fallback, "empty", True):
                runtime["pool"] = fallback

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
    # Prefer soft-cached document (same revision head recently loaded by sync_expected_revision /
    # commit_shared_room_state) so autopick does not pay a second network round-trip.
    current = load_shared_room_document(session, code, store=backend)
    if not isinstance(current, dict):
        return False, None
    head_rev = int(current.get("revision") or 0)
    use_rev = head_rev if expected_revision is None else int(expected_revision)
    updated = bump_revision(current, live_room=live_room)
    ok, saved = backend.save_if_revision(updated, expected_revision=use_rev)
    invalidate_shared_room_document_cache(session, code)
    if not ok or saved is None:
        if isinstance(saved, dict):
            publish_shared_room_runtime(session, saved, reason="shared_room_conflict")
            # Cache the conflict head so the next sync/revisit doesn't reload immediately.
            session[SHARED_DOC_SOFT_CACHE_KEY] = {
                "room_code": code,
                "loaded_at": datetime.now(timezone.utc).timestamp(),
                "document": saved,
            }
        return False, saved
    publish_shared_room_runtime(session, saved, reason="shared_room_pick")
    session[SHARED_DOC_SOFT_CACHE_KEY] = {
        "room_code": code,
        "loaded_at": datetime.now(timezone.utc).timestamp(),
        "document": saved,
    }
    return True, saved
