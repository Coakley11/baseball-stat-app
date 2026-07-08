"""Fantasy context source-of-truth — user-controlled priority across live, simulator, and saved drafts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

# User toggles — persisted in cloud/disk; default False (explicit opt-in).
USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY = "use_live_draft_as_fantasy_context"
USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY = "use_simulator_board_as_fantasy_context"
FANTASY_CONTEXT_TOGGLE_DEFAULT = False

SOURCE_LIVE_DRAFT = "live_draft"
SOURCE_SIMULATOR_BOARD = "simulator_board"
SOURCE_ACTIVE_DRAFT = "active_draft"
SOURCE_GENERIC = "generic"

CORE_FANTASY_PAGES: frozenset[str] = frozenset({
    "Fantasy Standings Tracker",
    "Fantasy Lineup Assistant",
    "Waiver Wire",
    "Trades",
})

DRAFT_ASSISTANT_PAGE = "Draft Assistant Simulator"

# Broader research/recommendation pages — require Research Mode Sync.
BROADER_RESEARCH_FANTASY_PAGES: frozenset[str] = frozenset({
    "Comparison Tool",
    "Trend Value",
    "Valuation",
    "Fantasy Sleepers & Busts",
    "Rankings",
    "Leaderboards",
    "Player Search",
})

RESEARCH_FANTASY_PAGES: frozenset[str] = BROADER_RESEARCH_FANTASY_PAGES | {DRAFT_ASSISTANT_PAGE}

_BADGE_PREFIX = "Fantasy Context Source:"


@dataclass(frozen=True)
class FantasyContextSource:
    """Resolved source controlling fantasy/research pages for this session."""

    kind: str
    label: str
    draft_label: str = ""
    # How this source was selected: "override" (explicit checkbox), "natural"
    # (unsaved board used because there is no Active Draft), "active_draft", or "generic".
    origin: str = ""

    @property
    def badge_text(self) -> str:
        """Compact badge without team — prefer ``fantasy_context_source_badge_text(session)``."""
        if self.kind == SOURCE_ACTIVE_DRAFT:
            name = self.draft_label or self.label
            return f"{_BADGE_PREFIX} **Saved Draft Library Active Draft** · Draft: **{name}**"
        if self.kind == SOURCE_LIVE_DRAFT:
            return f"{_BADGE_PREFIX} **Live Draft Room (temporary / unsaved)**"
        if self.kind == SOURCE_SIMULATOR_BOARD:
            return f"{_BADGE_PREFIX} **Draft Room Simulator Board (temporary / unsaved)**"
        return f"{_BADGE_PREFIX} **Generic/default simulator context**"


def live_draft_sync_enabled(session: dict[str, Any]) -> bool:
    return bool(session.get(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, FANTASY_CONTEXT_TOGGLE_DEFAULT))


def simulator_board_sync_enabled(session: dict[str, Any]) -> bool:
    return bool(session.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, FANTASY_CONTEXT_TOGGLE_DEFAULT))


def _simulator_board_table(session: dict[str, Any]) -> pd.DataFrame:
    """Raw simulator board only — never hydrate/sync from live or saved archive."""
    try:
        from draft_room_state import DRAFT_ROOM_TABLE_KEY, coerce_board_table

        return coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    except ImportError:
        table = session.get("draft_room_table")
        return table.copy() if isinstance(table, pd.DataFrame) else pd.DataFrame()


def _simulator_board_pick_count(session: dict[str, Any]) -> int:
    table = _simulator_board_table(session)
    if table.empty or "Player" not in table.columns:
        return 0
    return int(table["Player"].astype(str).str.strip().ne("").sum())


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


def simulator_board_context_available(session: dict[str, Any], *, ignore_live_override: bool = False) -> bool:
    """True when the Draft Room Simulator workspace has picks."""
    if _simulator_board_pick_count(session) <= 0:
        return False
    if ignore_live_override:
        return True
    try:
        from draft_room_state import is_live_draft_runtime_active

        if is_live_draft_runtime_active(session) and live_draft_sync_enabled(session):
            return False
    except ImportError:
        pass
    return True


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


def _resolve_override_source(session: dict[str, Any]) -> FantasyContextSource | None:
    """Temporary override only — user explicitly checked a workspace override box."""
    if live_draft_sync_enabled(session) and live_draft_context_available(session):
        return FantasyContextSource(
            SOURCE_LIVE_DRAFT, "Live Draft Room (temporary override)", origin="override"
        )
    if simulator_board_sync_enabled(session) and simulator_board_context_available(session):
        return FantasyContextSource(
            SOURCE_SIMULATOR_BOARD, "Draft Room Simulator (temporary override)", origin="override"
        )
    return None


def _resolve_natural_board_source(session: dict[str, Any]) -> FantasyContextSource | None:
    """Unsaved workspace boards when there is no Saved Active Draft (no override required)."""
    if saved_active_draft_available(session):
        return None
    if live_draft_context_available(session):
        return FantasyContextSource(SOURCE_LIVE_DRAFT, "Live Draft Room", origin="natural")
    if simulator_board_context_available(session, ignore_live_override=True):
        return FantasyContextSource(SOURCE_SIMULATOR_BOARD, "Draft Room Simulator", origin="natural")
    return None


def resolve_fantasy_context_source(session: dict[str, Any]) -> FantasyContextSource:
    """Canonical priority for core fantasy + research (when Research Mode Sync is on).

    1. Temporary workspace override (Live or Simulator checkbox), if enabled.
    2. Saved Active Draft / Active League.
    3. Current unsaved Live or Simulator board when no Active Draft exists.
    4. Generic/default team context.
    """
    override = _resolve_override_source(session)
    if override is not None:
        return override

    saved = _get_saved_active_league_context(session)
    if isinstance(saved, dict) and str(saved.get("my_team_name") or "").strip():
        name = _active_draft_label(session, saved)
        return FantasyContextSource(
            SOURCE_ACTIVE_DRAFT,
            f"Active Draft: {name}",
            draft_label=name,
            origin="active_draft",
        )

    natural = _resolve_natural_board_source(session)
    if natural is not None:
        return natural

    return FantasyContextSource(SOURCE_GENERIC, "Generic/default simulator context", origin="generic")


def is_core_fantasy_page(page_name: str) -> bool:
    return str(page_name or "").strip() in CORE_FANTASY_PAGES


def is_research_fantasy_page(page_name: str) -> bool:
    return str(page_name or "").strip() in RESEARCH_FANTASY_PAGES


def is_broader_research_fantasy_page(page_name: str) -> bool:
    return str(page_name or "").strip() in BROADER_RESEARCH_FANTASY_PAGES


def is_live_draft_in_progress(session: dict[str, Any]) -> bool:
    """True when the live draft room is actively in progress (not merely complete)."""
    room = _resolve_live_room(session)
    if not isinstance(room, dict):
        return False
    status = str(room.get("status") or "").strip()
    return status in ("in_progress", "paused")


def _research_sync_enabled(session: dict[str, Any]) -> bool:
    try:
        from fantasy_context_ui import research_league_sync_enabled

        return research_league_sync_enabled(session)
    except ImportError:
        return bool(session.get("use_active_league_context_waiver_filter"))


def _has_filterable_fantasy_source(session: dict[str, Any]) -> bool:
    return resolve_fantasy_context_source(session).kind != SOURCE_GENERIC


def live_draft_feeds_draft_assistant(session: dict[str, Any]) -> bool:
    """Live Draft Room feeds Draft Assistant during in-progress drafts (no Research Mode required)."""
    source = resolve_fantasy_context_source(session)
    if source.kind != SOURCE_LIVE_DRAFT:
        return False
    return is_live_draft_in_progress(session)


def fantasy_drafted_pool_filter_applies(session: dict[str, Any], page_name: str) -> bool:
    """Whether drafted/rostered players should be removed from this page's player pool.

    Routing matrix:
    - Core management pages: never via this filter (they use league context directly).
    - Saved Active Draft / Simulator override: broader research + DAS only when Research Mode Sync ON.
    - Live Draft override (in progress): DAS always; broader research only when Research Mode Sync ON.
    - Completed / non-live drafts: same as saved/simulator (Research Mode Sync required for DAS).
    """
    page = str(page_name or "").strip()
    research_on = _research_sync_enabled(session)

    if page in CORE_FANTASY_PAGES:
        return False

    if page == DRAFT_ASSISTANT_PAGE:
        if research_on and _has_filterable_fantasy_source(session):
            return True
        return live_draft_feeds_draft_assistant(session)

    if page in BROADER_RESEARCH_FANTASY_PAGES:
        return research_on and _has_filterable_fantasy_source(session)

    return False


def draft_assistant_context_mode(session: dict[str, Any]) -> str:
    """How Draft Assistant should source roster/drafted state.

    Returns one of:
    - ``live_board`` — sync picks and needs from the in-progress live draft board.
    - ``research_context`` — filter via unified active-team / league context (Research Mode).
    - ``none`` — no fantasy-context filtering on Draft Assistant.
    """
    if live_draft_feeds_draft_assistant(session):
        return "live_board"
    if fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE):
        return "research_context"
    return "none"


def fantasy_context_applies_to_page(session: dict[str, Any], page_name: str) -> bool:
    """Whether fantasy context should drive this page's recommendations."""
    page = str(page_name or "").strip()
    if page in CORE_FANTASY_PAGES:
        return True
    if page in RESEARCH_FANTASY_PAGES:
        return fantasy_drafted_pool_filter_applies(session, page)
    return False


def _context_team_name(session: dict[str, Any]) -> str:
    source = resolve_fantasy_context_source(session)
    if source.kind == SOURCE_ACTIVE_DRAFT:
        saved = _get_saved_active_league_context(session)
        if isinstance(saved, dict):
            team = str(saved.get("my_team_name") or "").strip()
            if team:
                return team
    if source.kind == SOURCE_LIVE_DRAFT:
        room = _resolve_live_room(session)
        if isinstance(room, dict):
            cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
            for key in ("user_team", "your_team"):
                val = cfg.get(key)
                if val:
                    return str(val).strip()
    if source.kind == SOURCE_SIMULATOR_BOARD:
        table = _simulator_board_table(session)
        my_team = str(session.get("room_your_team") or "").strip()
        if my_team:
            return my_team
        if not table.empty and "Team" in table.columns and "Player" in table.columns:
            filled = table[table["Player"].astype(str).str.strip().ne("")]
            if not filled.empty:
                return str(filled.iloc[0]["Team"]).strip()
    return str(session.get("room_your_team") or "").strip()


def fantasy_context_source_badge_text(session: dict[str, Any]) -> str:
    """Full context-source badge including team when known."""
    source = resolve_fantasy_context_source(session)
    team = _context_team_name(session)
    text = source.badge_text
    if team and "Team:" not in text:
        text = f"{text} · Team: **{team}**"
    return text


def fantasy_context_using_caption(session: dict[str, Any]) -> str:
    """One short, plain line naming the single effective fantasy source.

    Active Draft and temporary boards are mutually exclusive labels — never combine them.
    """
    source = resolve_fantasy_context_source(session)
    team = _context_team_name(session)
    team_suffix = f" — Team {team}" if team else ""

    if source.kind == SOURCE_ACTIVE_DRAFT:
        name = source.draft_label or source.label or "Active Draft"
        return f"Using: Active Draft — {name}{team_suffix}"

    if source.kind == SOURCE_LIVE_DRAFT:
        return f"Using: Temporary Live Draft Board — unsaved{team_suffix}"

    if source.kind == SOURCE_SIMULATOR_BOARD:
        return f"Using: Temporary Simulator Board — unsaved{team_suffix}"

    return "Using: General MLB (no draft context)"


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
    return _simulator_board_table(session)


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
        label = str(cfg.get("league_name") or "Live Draft Room").strip() or "Live Draft Room"
        return create_league_context_from_live_room(
            session,
            room,
            my_team_name=my_team,
            display_name=f"{label} (temporary / unsaved)",
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
            display_name="Draft Room Simulator Board (temporary / unsaved)",
            league_context_id="__ephemeral_simulator__",
        )
    return None


def prepare_fantasy_context_source_defaults(session: dict[str, Any]) -> None:
    """Seed missing toggle keys once — never overwrite an explicit user choice."""
    session.setdefault(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, FANTASY_CONTEXT_TOGGLE_DEFAULT)
    session.setdefault(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, FANTASY_CONTEXT_TOGGLE_DEFAULT)
    try:
        from fantasy_context_ui import FANTASY_RESEARCH_SYNC_KEY

        session.setdefault(FANTASY_RESEARCH_SYNC_KEY, False)
    except ImportError:
        session.setdefault("use_active_league_context_waiver_filter", False)
