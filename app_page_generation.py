"""Global application page identity — prevent cross-page fragment / renderer bleed."""

from __future__ import annotations

import time
import traceback
from typing import Any

ACTIVE_PAGE_NAME_KEY = "active_page_name"
ACTIVE_PAGE_GENERATION_KEY = "active_page_generation"
ACTIVE_PAGE_INSTANCE_ID_KEY = "active_page_instance_id"
PAGE_SNAPSHOT_KEY = "_app_page_snapshot"
PAGE_RENDER_PROVENANCE_KEY = "_page_render_provenance"
PAGE_RENDERER_COUNT_KEY = "_page_top_level_renderer_count"

# Temporarily reduce cross-page risk: non–Live-Draft pages must not keep draft fragments alive.
REQUIRE_PAGE_MATCH_FOR_FRAGMENTS = True


def _normalize_page(name: str) -> str:
    return str(name or "").strip()


def begin_page_run(session: dict[str, Any], selected_page: str) -> dict[str, Any]:
    """Call once per script run after the body page is finally resolved."""
    page = _normalize_page(selected_page)
    prev = _normalize_page(session.get(ACTIVE_PAGE_NAME_KEY) or "")
    gen = int(session.get(ACTIVE_PAGE_GENERATION_KEY) or 0)
    if page and page != prev:
        gen += 1
        session[ACTIVE_PAGE_GENERATION_KEY] = gen
        session[ACTIVE_PAGE_INSTANCE_ID_KEY] = f"{page}:{gen}:{int(time.time() * 1000) % 10_000_000}"
        # Leaving Live Draft — suppress draft fragments immediately.
        if prev == "Live Draft Room" and page != "Live Draft Room":
            try:
                from live_draft_termination import bump_live_draft_page_epoch

                bump_live_draft_page_epoch(session)
            except ImportError:
                session["_live_draft_suppress_fragments"] = True
    elif not session.get(ACTIVE_PAGE_GENERATION_KEY):
        gen = 1
        session[ACTIVE_PAGE_GENERATION_KEY] = gen
        session[ACTIVE_PAGE_INSTANCE_ID_KEY] = f"{page}:{gen}:boot"

    session[ACTIVE_PAGE_NAME_KEY] = page
    session["active_page"] = page
    session[PAGE_RENDERER_COUNT_KEY] = 0
    session[PAGE_RENDER_PROVENANCE_KEY] = []

    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    draft_id = ""
    room_id = ""
    if isinstance(room, dict):
        draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "").strip()
        room_id = str(room.get("room_id") or draft_id or "").strip()
        if not code:
            sync = room.get("sync") if isinstance(room.get("sync"), dict) else {}
            code = str(sync.get("room_code") or room.get("room_code") or "").strip().upper()
    lifecycle = "setup"
    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        lifecycle = resolve_live_draft_lifecycle(session, room=room if room else None)
    except ImportError:
        pass
    epoch = int(session.get("_live_draft_page_fragment_epoch") or 0)
    snapshot = {
        "page": page,
        "page_generation": int(session.get(ACTIVE_PAGE_GENERATION_KEY) or 0),
        "page_instance_id": str(session.get(ACTIVE_PAGE_INSTANCE_ID_KEY) or ""),
        "lifecycle": lifecycle,
        "room_id": room_id,
        "room_code": code,
        "draft_id": draft_id,
        "live_draft_epoch": epoch,
        "ts": time.time(),
    }
    session[PAGE_SNAPSHOT_KEY] = snapshot
    return snapshot


def get_page_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    snap = session.get(PAGE_SNAPSHOT_KEY)
    return dict(snap) if isinstance(snap, dict) else {}


def note_page_renderer(
    session: dict[str, Any],
    renderer_name: str,
    *,
    selected_page: str = "",
) -> None:
    """Record a top-level page body renderer; used to detect dual-page paint."""
    page = _normalize_page(selected_page or session.get(ACTIVE_PAGE_NAME_KEY) or "")
    count = int(session.get(PAGE_RENDERER_COUNT_KEY) or 0) + 1
    session[PAGE_RENDERER_COUNT_KEY] = count
    entry = {
        "selected_page": page,
        "renderer": str(renderer_name or ""),
        "page_generation": int(session.get(ACTIVE_PAGE_GENERATION_KEY) or 0),
        "live_draft_epoch": int(session.get("_live_draft_page_fragment_epoch") or 0),
        "room_code": str(session.get("active_shared_draft_room_code") or ""),
        "ts": time.time(),
        "stack": "".join(traceback.format_stack(limit=8)[-6:]),
    }
    ring = list(session.get(PAGE_RENDER_PROVENANCE_KEY) or [])
    ring.append(entry)
    session[PAGE_RENDER_PROVENANCE_KEY] = ring[-20:]
    # Hard fail signal for diagnostics when Historical paints under Live Draft.
    if page == "Live Draft Room" and "historical" in str(renderer_name or "").lower():
        session["_cross_page_render_leak"] = entry
    if count > 1:
        session["_multiple_page_renderers"] = True


def fragment_allowed(
    session: dict[str, Any],
    *,
    expected_page: str,
    expected_generation: int | None = None,
    expected_live_draft_epoch: int | None = None,
    expected_room_id: str = "",
) -> bool:
    """Every fragment must call this before painting or mutating."""
    if not REQUIRE_PAGE_MATCH_FOR_FRAGMENTS:
        return True
    active = _normalize_page(session.get(ACTIVE_PAGE_NAME_KEY) or session.get("active_page") or "")
    expected = _normalize_page(expected_page)
    if expected and active != expected:
        return False
    if expected_generation is not None:
        if int(session.get(ACTIVE_PAGE_GENERATION_KEY) or 0) != int(expected_generation):
            return False
    if expected_live_draft_epoch is not None:
        if int(session.get("_live_draft_page_fragment_epoch") or 0) != int(expected_live_draft_epoch):
            return False
    if expected_room_id:
        snap = get_page_snapshot(session)
        current = str(snap.get("room_id") or snap.get("draft_id") or "").strip()
        if current and current != str(expected_room_id).strip():
            return False
    try:
        from live_draft_termination import live_draft_fragments_suppressed

        if expected == "Live Draft Room" and live_draft_fragments_suppressed(session):
            return False
    except ImportError:
        pass
    return True


def capture_fragment_gate(session: dict[str, Any], *, expected_page: str) -> dict[str, Any]:
    """Snapshot identity at fragment mount time."""
    snap = get_page_snapshot(session)
    return {
        "expected_page": _normalize_page(expected_page or snap.get("page") or ""),
        "expected_generation": int(snap.get("page_generation") or session.get(ACTIVE_PAGE_GENERATION_KEY) or 0),
        "expected_live_draft_epoch": int(snap.get("live_draft_epoch") or session.get("_live_draft_page_fragment_epoch") or 0),
        "expected_room_id": str(snap.get("room_id") or snap.get("draft_id") or ""),
        "expected_room_code": str(snap.get("room_code") or ""),
    }
