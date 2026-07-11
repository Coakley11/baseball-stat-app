"""Fantasy Lineup page performance helpers — caches and invalidation."""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

LINEUP_RESOLVED_CTX_KEY = "_lineup_resolved_page_context"
LINEUP_CTX_RUN_KEY = "_lineup_ctx_resolved_for_run"
LINEUP_BOARD_PAYLOAD_CACHE_KEY = "_lineup_board_payload_cache"
LINEUP_FACE_PHOTO_CACHE_KEY = "_lineup_face_photo_cache"


def _page_run_token(session: dict[str, Any]) -> float:
    ns = session.get("_page_perf_ns")
    if isinstance(ns, dict):
        started = float(ns.get("started_at") or 0.0)
        if started:
            return started
    return float(session.get("_lineup_fallback_run_token") or 0.0)


def invalidate_lineup_page_caches(session: dict[str, Any]) -> None:
    """Clear per-run lineup caches after context or assignment writes."""
    session.pop(LINEUP_RESOLVED_CTX_KEY, None)
    session.pop(LINEUP_CTX_RUN_KEY, None)
    session.pop(LINEUP_BOARD_PAYLOAD_CACHE_KEY, None)


def get_cached_lineup_page_context(session: dict[str, Any]) -> dict[str, Any] | None:
    run_token = _page_run_token(session)
    if session.get(LINEUP_CTX_RUN_KEY) != run_token:
        return None
    cached = session.get(LINEUP_RESOLVED_CTX_KEY)
    return cached if isinstance(cached, dict) else None


def store_lineup_page_context(session: dict[str, Any], context: dict[str, Any] | None) -> None:
    session[LINEUP_CTX_RUN_KEY] = _page_run_token(session)
    if isinstance(context, dict):
        session[LINEUP_RESOLVED_CTX_KEY] = context
    else:
        session.pop(LINEUP_RESOLVED_CTX_KEY, None)


def roster_payload_fingerprint(
    *,
    slot_labels: list,
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
    editable: bool,
) -> str:
    from fantasy_weekly_lineup import roster_player_names

    slot_keys = [label.key for label in slot_labels]
    assign_bits = "|".join(f"{k}={str(assignments.get(k) or '').strip()}" for k in slot_keys)
    names = ",".join(roster_player_names(roster_df))
    raw = f"{assign_bits}|{names}|{len(roster_df)}|{bool(editable)}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def get_cached_board_payload(session: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    entry = session.get(LINEUP_BOARD_PAYLOAD_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("fp") == fingerprint:
        payload = entry.get("payload")
        if isinstance(payload, dict):
            try:
                from page_perf_phases import record_cache_event

                record_cache_event(session, "lineup_board_payload", hit=True)
            except ImportError:
                pass
            return payload
    return None


def store_board_payload(session: dict[str, Any], fingerprint: str, payload: dict[str, Any]) -> None:
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, "lineup_board_payload", hit=False)
    except ImportError:
        pass
    session[LINEUP_BOARD_PAYLOAD_CACHE_KEY] = {"fp": fingerprint, "payload": payload}


def get_cached_face_photo(session: dict[str, Any], cache_key: str) -> dict[str, Any] | None:
    bucket = session.get(LINEUP_FACE_PHOTO_CACHE_KEY)
    if not isinstance(bucket, dict):
        return None
    row = bucket.get(cache_key)
    return row if isinstance(row, dict) else None


def store_face_photo(session: dict[str, Any], cache_key: str, face: dict[str, Any]) -> None:
    bucket = session.get(LINEUP_FACE_PHOTO_CACHE_KEY)
    if not isinstance(bucket, dict):
        bucket = {}
    bucket[cache_key] = face
    if len(bucket) > 120:
        bucket = dict(list(bucket.items())[-80:])
    session[LINEUP_FACE_PHOTO_CACHE_KEY] = bucket
