"""Fantasy context source-of-truth — user-controlled priority across live, simulator, and saved drafts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

# User toggles (default True — live/simulator feed the app when available).
USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY = "use_live_draft_as_fantasy_context"
USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY = "use_simulator_board_as_fantasy_context"

SOURCE_LIVE_DRAFT = "live_draft"
SOURCE_SIMULATOR_BOARD = "simulator_board"
SOURCE_ACTIVE_DRAFT = "active_draft"
SOURCE_GENERIC = "generic"

_BADGE_PREFIX = "Fantasy Context Source:"


@dataclass(frozen=True)
class FantasyContextSource:
    """Resolved source controlling fantasy/research pages for this session."""

    kind: str
    label: str
    draft_label: str = ""

    @property
    def badge_text(self) -> str:
        """Compact badge without team — prefer ``fantasy_context_source_badge_text(session)``."""
        if self.kind == SOURCE_ACTIVE_DRAFT:
            name = self.draft_label or self.label
            return f"{_BADGE_PREFIX} **Saved Draft Library Active Draft** · Draft: **{name}**"
        if self.kind == SOURCE_LIVE_DRAFT:
            return f"{_BADGE_PREFIX} **Live Draft Room**"
        if self.kind == SOURCE_SIMULATOR_BOARD:
            return f"{_BADGE_PREFIX} **Draft Room Simulator Board (unsaved)**"
        return f"{_BADGE_PREFIX} **Generic/default simulator context**"


def live_draft_sync_enabled(session: dict[str, Any]) -> bool:
    return bool(session.get(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, True))


def simulator_board_sync_enabled(session: dict[str, Any]) -> bool:
    return bool(session.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, True))


def live_draft_context_available(session: dict[str, Any]) -> bool:
    """True when a resumable live draft with board state exists."""
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, has_active_live_draft

        if has_active_live_draft(session):
            return True
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict):
            status = str(room.get("status") or "").strip()
            if status in ("in_progress", "paused", "complete"):
                board = room.get("draft_board") or []
                if isinstance(board, list) and board:
                    return True
    except ImportError:
        pass
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        status = str(room.get("status") or "").strip()
        if status in ("in_progress", "paused", "complete"):
            board = room.get("draft_board") or []
            return isinstance(board, list) and bool(board)
    return False


def simulator_board_context_available(session: dict[str, Any]) -> bool:
    """True when the Draft Room Simulator board has at least one pick."""
    table = session.get("draft_room_table")
    if isinstance(table, pd.DataFrame) and not table.empty:
        if "Player" in table.columns:
            filled = table["Player"].astype(str).str.strip().ne("").sum()
            if int(filled) > 0:
                return True
    try:
        from draft_room_state import get_canonical_draft_board, table_pick_count

        board = get_canonical_draft_board(session)
        return table_pick_count(board) > 0
    except ImportError:
        return isinstance(table, pd.DataFrame) and not table.empty


def saved_active_draft_available(session: dict[str, Any]) -> bool:
    """True when Saved Draft Library has an Active Draft with a user team."""
    ctx = _get_saved_active_league_context(session)
    return isinstance(ctx, dict) and bool(str(ctx.get("my_team_name") or "").strip())


def _get_saved_active_league_context(session: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from fantasy_league_context import ensure_fantasy_league_context_state, get_league_context

        store = ensure_fantasy_league_context_state(session)
        active_id = str(store.get("active_league_context_id") or "").strip()
        if not active_id:
            return None
        return get_league_context(session, active_id)
    except ImportError:
        return None


def _active_draft_label(session: dict[str, Any], ctx: dict[str, Any]) -> str:
    label = str(ctx.get("display_name") or ctx.get("draft_name") or "").strip()
    if label:
        return label
    try:
        from draft_archive_state import get_active_draft_archive

        archive = get_active_draft_archive(session)
    except ImportError:
        archive = None
    if isinstance(archive, dict):
        label = str(archive.get("draft_name") or "").strip()
    return label or str(ctx.get("my_team_name") or "Active Draft").strip()


def resolve_fantasy_context_source(session: dict[str, Any]) -> FantasyContextSource:
    """Canonical priority: Live Draft > Simulator Board > Saved Active Draft > Generic."""
    if live_draft_sync_enabled(session) and live_draft_context_available(session):
        return FantasyContextSource(SOURCE_LIVE_DRAFT, "Live Draft Room")
    if simulator_board_sync_enabled(session) and simulator_board_context_available(session):
        return FantasyContextSource(SOURCE_SIMULATOR_BOARD, "Draft Room Simulator")
    saved = _get_saved_active_league_context(session)
    if isinstance(saved, dict) and str(saved.get("my_team_name") or "").strip():
        name = _active_draft_label(session, saved)
        return FantasyContextSource(
            SOURCE_ACTIVE_DRAFT,
            f"Active Draft: {name}",
            draft_label=name,
        )
    return FantasyContextSource(SOURCE_GENERIC, "Generic/default simulator context")


def _context_team_name(session: dict[str, Any]) -> str:
    saved = _get_saved_active_league_context(session)
    if isinstance(saved, dict):
        team = str(saved.get("my_team_name") or "").strip()
        if team:
            return team
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
        for key in ("user_team", "your_team"):
            val = cfg.get(key)
            if val:
                return str(val).strip()
    return str(session.get("room_your_team") or "").strip()


def fantasy_context_source_badge_text(session: dict[str, Any]) -> str:
    """Full context-source badge including team when known."""
    source = resolve_fantasy_context_source(session)
    team = _context_team_name(session)
    text = source.badge_text
    if team and "Team:" not in text:
        text = f"{text} · Team: **{team}**"
    return text


def _resolve_live_room(session: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, canonical_live_draft

        blob = canonical_live_draft(session)
        if isinstance(blob, dict) and blob.get("draft_room_id"):
            return blob
        room = session.get(LIVE_DRAFT_ROOM_KEY) or session.get("live_draft_room")
        return room if isinstance(room, dict) else None
    except ImportError:
        room = session.get("live_draft_room") or session.get(LIVE_DRAFT_ROOM_KEY)
        return room if isinstance(room, dict) else None


def _resolve_simulator_board(session: dict[str, Any]) -> pd.DataFrame:
    try:
        from draft_room_state import get_canonical_draft_board

        board = get_canonical_draft_board(session)
        return board if isinstance(board, pd.DataFrame) else pd.DataFrame()
    except ImportError:
        table = session.get("draft_room_table")
        return table.copy() if isinstance(table, pd.DataFrame) else pd.DataFrame()


def _resolve_my_team_for_ephemeral(session: dict[str, Any], *, source: FantasyContextSource) -> str:
    try:
        from global_fantasy_settings_state import get_active_fantasy_team

        team = str(get_active_fantasy_team(session) or "").strip()
        if team:
            return team
    except ImportError:
        pass
    return str(session.get("room_your_team") or "").strip()


def get_effective_fantasy_context(
    session: dict[str, Any],
    *,
    respect_source_priority: bool = True,
) -> dict[str, Any] | None:
    """Return the league context dict that should feed fantasy/research pages."""
    if not respect_source_priority:
        return _get_saved_active_league_context(session)

    source = resolve_fantasy_context_source(session)
    if source.kind == SOURCE_ACTIVE_DRAFT:
        return _get_saved_active_league_context(session)
    if source.kind == SOURCE_GENERIC:
        return None

    try:
        from fantasy_league_context import (
            create_league_context_from_live_room,
            create_league_context_from_simulator_board,
        )
    except ImportError:
        return _get_saved_active_league_context(session)

    my_team = _resolve_my_team_for_ephemeral(session, source=source)
    if source.kind == SOURCE_LIVE_DRAFT:
        room = _resolve_live_room(session)
        if not isinstance(room, dict):
            return _get_saved_active_league_context(session)
        cfg = dict(room.get("config") or {})
        label = str(cfg.get("league_name") or "Live Draft").strip() or "Live Draft"
        return create_league_context_from_live_room(
            session,
            room,
            my_team_name=my_team,
            display_name=f"{label} (live)",
            league_name=label,
            league_context_id="__ephemeral_live__",
        )
    if source.kind == SOURCE_SIMULATOR_BOARD:
        board = _resolve_simulator_board(session)
        if board.empty:
            return _get_saved_active_league_context(session)
        return create_league_context_from_simulator_board(
            session,
            board,
            my_team_name=my_team,
            display_name="Draft Room Simulator (board)",
            league_context_id="__ephemeral_simulator__",
        )
    return None


def prepare_fantasy_context_source_defaults(session: dict[str, Any]) -> None:
    """Default live/simulator context sync toggles to enabled."""
    session.setdefault(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, True)
    session.setdefault(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, True)
