"""Fantasy context source-of-truth — user-controlled priority across live, simulator, and saved drafts."""

from __future__ import annotations

import html
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

DRAFT_ASSISTANT_PAGE = "Draft Assistant Simulator"

CORE_FANTASY_PAGES: frozenset[str] = frozenset({
    "Fantasy Standings Tracker",
    "Fantasy Lineup Assistant",
    "Waiver Wire",
    "Waiver Wire / Add-Drop Center",
    "Trades",
    DRAFT_ASSISTANT_PAGE,
})

# Draft-related research pages — Research Mode Sync only (never historical pages).
BROADER_RESEARCH_FANTASY_PAGES: frozenset[str] = frozenset({
    "Comparison Tool",
    "Trend Value",
    "Valuation",
    "Fantasy Sleepers & Busts",
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
            heading = self.label.split(":", 1)[0].strip() if ":" in self.label else "Active Draft"
            return f"{_BADGE_PREFIX} **Saved Draft Library {heading}** · **{name}**"
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
    # Active Live Draft preempts simulator as effective fantasy source.
    if is_live_draft_in_progress(session):
        return False
    try:
        from draft_room_state import is_live_draft_runtime_active

        if is_live_draft_runtime_active(session) and live_draft_sync_enabled(session):
            return False
    except ImportError:
        pass
    return True


def saved_active_draft_available(session: dict[str, Any]) -> bool:
    """True when Saved Draft Library has an Active Draft / Active League selection."""
    ctx = _get_saved_active_league_context(session)
    if not isinstance(ctx, dict):
        return False
    if str(ctx.get("my_team_name") or "").strip():
        return True
    # Shared-league team overlay may blank my_team when ownership is unresolved;
    # a durable context id still counts as an Active League selection.
    if str(ctx.get("league_context_id") or "").strip():
        return True
    try:
        from draft_archive_state import get_active_draft_archive

        archive = get_active_draft_archive(session)
        if isinstance(archive, dict) and str(archive.get("draft_id") or "").strip():
            return True
    except ImportError:
        pass
    return False


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


def _looks_ephemeral_draft_label(label: str) -> bool:
    """True when a label describes a temporary workspace board, not a saved Active Draft."""
    low = str(label or "").strip().lower()
    if not low:
        return True
    ephemeral_bits = (
        "temporary / unsaved",
        "temporary/unsaved",
        "(temporary",
        "draft room simulator board",
        "draft room simulator (",
        "live draft room (",
        "__ephemeral_",
    )
    return any(bit in low for bit in ephemeral_bits)


def _active_context_heading(session: dict[str, Any], ctx: dict[str, Any]) -> str:
    archive = None
    try:
        from draft_archive_state import get_active_draft_archive

        archive = get_active_draft_archive(session)
    except ImportError:
        pass
    try:
        from fantasy_context_terminology import active_context_label

        return active_context_label(ctx, archive)
    except ImportError:
        return "Active Draft"


def _active_draft_label(session: dict[str, Any], ctx: dict[str, Any]) -> str:
    """User-facing saved Active Draft name — never ephemeral simulator/live board copy."""
    archive = None
    try:
        from draft_archive_state import get_active_draft_archive

        archive = get_active_draft_archive(session)
    except ImportError:
        pass

    if isinstance(archive, dict):
        try:
            from fantasy_context_source import _archive_matches_context

            archive_ok = _archive_matches_context(archive, ctx)
        except ImportError:
            archive_ok = True
        if archive_ok:
            arch_name = str(archive.get("draft_name") or "").strip()
            if arch_name and not _looks_ephemeral_draft_label(arch_name):
                return arch_name

    for candidate in (
        str(ctx.get("draft_name") or "").strip(),
        str(ctx.get("display_name") or "").strip(),
        str(ctx.get("league_name") or "").strip(),
    ):
        if candidate and not _looks_ephemeral_draft_label(candidate):
            return candidate

    if isinstance(archive, dict):
        arch_name = str(archive.get("draft_name") or "").strip()
        if arch_name:
            return arch_name

    return str(ctx.get("my_team_name") or "Active Draft").strip()


def _resolve_override_source(session: dict[str, Any]) -> FantasyContextSource | None:
    """Temporary override only — user explicitly checked a workspace override box.

    Completed Live Drafts stay effective only while the Live override is ON.
    Simulator boards never become effective without this override.
    """
    if live_draft_sync_enabled(session) and live_draft_context_available(session):
        return FantasyContextSource(
            SOURCE_LIVE_DRAFT, "Live Draft Room (temporary override)", origin="override"
        )
    if simulator_board_sync_enabled(session) and simulator_board_context_available(session):
        return FantasyContextSource(
            SOURCE_SIMULATOR_BOARD, "Draft Room Simulator (temporary override)", origin="override"
        )
    return None


def _resolve_active_live_draft_source(session: dict[str, Any]) -> FantasyContextSource | None:
    """In-progress / paused Live Draft automatically becomes the effective source."""
    if not is_live_draft_in_progress(session):
        return None
    if not live_draft_context_available(session):
        # Allow activation even before the first pick when room is in_progress/paused.
        room = session.get("live_draft_room")
        if not (isinstance(room, dict) and str(room.get("status") or "").strip() in ("in_progress", "paused")):
            return None
    return FantasyContextSource(
        SOURCE_LIVE_DRAFT,
        "Live Draft Room (active)",
        origin="active_live",
    )


def _resolve_natural_board_source(session: dict[str, Any]) -> FantasyContextSource | None:
    """Natural fallback boards when there is no Saved Active Draft and no override.

    Simulator never auto-attaches. Completed Live Draft without override does not either.
    Active in-progress Live Draft is handled earlier by ``_resolve_active_live_draft_source``.
    """
    del session  # Natural simulator/live attach removed by product rule.
    return None


def resolve_fantasy_context_source(session: dict[str, Any]) -> FantasyContextSource:
    """Canonical priority for core fantasy + research (when Research Mode Sync is on).

    1. Active Live Draft (in_progress / paused) — automatic, no Override required.
    2. Temporary workspace override (completed Live or Simulator checkbox).
    3. Saved Active Draft / Active League.
    4. Generic/default (no active draft).
    """
    active_live = _resolve_active_live_draft_source(session)
    if active_live is not None:
        return active_live

    override = _resolve_override_source(session)
    if override is not None:
        return override

    saved = _get_saved_active_league_context(session)
    if isinstance(saved, dict) and saved_active_draft_available(session):
        name = _active_draft_label(session, saved)
        heading = _active_context_heading(session, saved)
        return FantasyContextSource(
            SOURCE_ACTIVE_DRAFT,
            f"{heading}: {name}",
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


def simulator_feeds_draft_assistant(session: dict[str, Any]) -> bool:
    """Draft Room Simulator feeds DAS with drafted-player exclusions only (no Research Mode)."""
    if live_draft_feeds_draft_assistant(session):
        return False
    if not simulator_board_context_available(session, ignore_live_override=True):
        return False
    return resolve_fantasy_context_source(session).kind == SOURCE_SIMULATOR_BOARD


def active_saved_draft_feeds_draft_assistant(session: dict[str, Any]) -> bool:
    """Saved Active Draft feeds DAS with drafted exclusions (default needs — not Live strategy)."""
    if live_draft_feeds_draft_assistant(session) or simulator_feeds_draft_assistant(session):
        return False
    source = resolve_fantasy_context_source(session)
    return source.kind == SOURCE_ACTIVE_DRAFT and saved_active_draft_available(session)


def fantasy_drafted_pool_filter_applies(session: dict[str, Any], page_name: str) -> bool:
    """Whether drafted/rostered players should be removed from this page's player pool.

    Routing matrix:
    - Draft Assistant (fantasy tool): Active Live, Simulator override, or Saved Active Draft
      always remove drafted players (needs policy decided by ``draft_assistant_context_mode``).
    - Broader research pages: only when Research Mode Sync is ON and a filterable source exists.
    - Historical pages: never.
    """
    page = str(page_name or "").strip()
    research_on = _research_sync_enabled(session)

    if page == DRAFT_ASSISTANT_PAGE:
        if live_draft_feeds_draft_assistant(session):
            return True
        if simulator_feeds_draft_assistant(session):
            return True
        if active_saved_draft_feeds_draft_assistant(session):
            return True
        return False

    # Core management pages use league context directly — not this pool filter gate.
    if page in CORE_FANTASY_PAGES:
        return False

    if page in BROADER_RESEARCH_FANTASY_PAGES:
        return research_on and _has_filterable_fantasy_source(session)

    return False


def draft_assistant_context_mode(session: dict[str, Any]) -> str:
    """How Draft Assistant should source roster/drafted state.

    Returns one of:
    - ``live_board`` — sync picks and needs from the in-progress live draft board.
    - ``simulator_board`` — exclude simulator-board picks only (no team-needs scoring).
    - ``active_draft`` — exclude Saved Active Draft picks; keep default needs.
    - ``research_context`` — legacy alias for ``active_draft`` (Saved Active exclusions).
    - ``none`` — no fantasy-context filtering on Draft Assistant.
    """
    if live_draft_feeds_draft_assistant(session):
        return "live_board"
    if simulator_feeds_draft_assistant(session):
        return "simulator_board"
    if active_saved_draft_feeds_draft_assistant(session):
        return "active_draft"
    return "none"


def fantasy_context_applies_to_page(session: dict[str, Any], page_name: str) -> bool:
    """Whether fantasy context should drive this page's recommendations."""
    page = str(page_name or "").strip()
    if page == DRAFT_ASSISTANT_PAGE:
        return draft_assistant_context_mode(session) != "none"
    if page in CORE_FANTASY_PAGES:
        return True
    if page in BROADER_RESEARCH_FANTASY_PAGES:
        return fantasy_drafted_pool_filter_applies(session, page)
    return False


def _context_team_name(session: dict[str, Any]) -> str:
    source = resolve_fantasy_context_source(session)
    if source.kind == SOURCE_ACTIVE_DRAFT:
        saved = _get_saved_active_league_context(session)
        if isinstance(saved, dict):
            try:
                from fantasy_league_team_ownership import resolve_account_fantasy_team

                owned = str(resolve_account_fantasy_team(session, saved) or "").strip()
                if owned:
                    return owned
            except ImportError:
                pass
            team = str(saved.get("my_team_name") or "").strip()
            if team:
                return team
            try:
                from fantasy_league_team_ownership import ownership_blocks_archive_team_fallback

                if ownership_blocks_archive_team_fallback(saved):
                    return ""
            except ImportError:
                pass
        try:
            from draft_archive_state import get_active_draft_archive

            archive = get_active_draft_archive(session)
            if isinstance(archive, dict):
                team = str(archive.get("team_name") or "").strip()
                if team:
                    return team
        except ImportError:
            pass
        candidate = str(session.get("room_your_team") or "").strip()
        if candidate:
            return candidate
    if source.kind in (SOURCE_LIVE_DRAFT, SOURCE_SIMULATOR_BOARD):
        return _resolve_my_team_for_ephemeral(session, source=source)
    return str(session.get("room_your_team") or "").strip()


def _restore_saved_context_team(session: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fill blank my_team after shared-league overlay wipe using ownership, never archive Team 1/2."""
    if not isinstance(context, dict):
        return context
    if str(context.get("my_team_name") or "").strip():
        return context
    try:
        from fantasy_league_team_ownership import (
            ownership_blocks_archive_team_fallback,
            resolve_account_fantasy_team,
        )

        owned = str(resolve_account_fantasy_team(session, context) or "").strip()
        if owned:
            out = dict(context)
            out["my_team_name"] = owned
            return out
        if ownership_blocks_archive_team_fallback(context):
            return context
    except ImportError:
        pass

    team = ""
    try:
        from draft_archive_state import get_active_draft_archive

        archive = get_active_draft_archive(session)
        if isinstance(archive, dict):
            team = str(archive.get("team_name") or "").strip()
    except ImportError:
        pass
    if not team:
        team = str(session.get("room_your_team") or "").strip()
    if not team:
        names = _workflow_team_names(context)
        if len(names) == 1:
            team = names[0]
    if not team:
        return context
    out = dict(context)
    out["my_team_name"] = team
    return out


def fantasy_context_source_badge_text(session: dict[str, Any]) -> str:
    """Full context-source badge including team when known."""
    source = resolve_fantasy_context_source(session)
    team = _context_team_name(session)
    text = source.badge_text
    if team and "Team:" not in text:
        text = f"{text} · Team: **{team}**"
    return text


def fantasy_context_using_caption(session: dict[str, Any]) -> str:
    """Plain-text summary — prefer ``fantasy_context_using_markdown`` for UI."""
    display = fantasy_context_using_display(session)
    if display["kind"] == "active_draft":
        name = display.get("draft_name") or "Active Draft"
        heading = str(display.get("active_heading") or "Active Draft").strip()
        team = str(display.get("team") or "").strip()
        if team:
            return f"{heading}: {name} — Team {team}"
        return f"{heading}: {name}"
    if display["kind"] == "temporary_live":
        team = str(display.get("team") or "").strip()
        return (
            f"Temporary Draft Board (Unsaved) — Live Draft — Team {team}"
            if team
            else "Temporary Draft Board (Unsaved) — Live Draft"
        )
    if display["kind"] == "temporary_simulator":
        team = str(display.get("team") or "").strip()
        return (
            f"Temporary Draft Board (Unsaved) — Simulator — Team {team}"
            if team
            else "Temporary Draft Board (Unsaved)"
        )
    return "General MLB (no draft context)"


def fantasy_context_using_display(session: dict[str, Any]) -> dict[str, str]:
    """Structured effective source for prominent management-page banners."""
    source = resolve_fantasy_context_source(session)
    team = _context_team_name(session)

    if source.kind == SOURCE_ACTIVE_DRAFT:
        saved = _get_saved_active_league_context(session)
        name = _active_draft_label(session, saved or {})
        heading = _active_context_heading(session, saved or {})
        return {
            "kind": "active_draft",
            "draft_name": name,
            "active_heading": heading,
            "board_label": "",
            "team": team,
        }

    if source.kind == SOURCE_LIVE_DRAFT:
        return {
            "kind": "temporary_live",
            "draft_name": "",
            "board_label": "Temporary Draft Board (Unsaved) — Live Draft",
            "team": team,
        }

    if source.kind == SOURCE_SIMULATOR_BOARD:
        return {
            "kind": "temporary_simulator",
            "draft_name": "",
            "board_label": "Temporary Draft Board (Unsaved)",
            "team": team,
        }

    return {"kind": "generic", "draft_name": "", "board_label": "", "team": team}


def _html_esc(text: str) -> str:
    return html.escape(str(text or "").strip(), quote=True)


def fantasy_context_using_html(session: dict[str, Any]) -> str:
    """Polished league-card banner for fantasy management pages."""
    display = fantasy_context_using_display(session)
    kind = display.get("kind") or "generic"
    team = _html_esc(display.get("team") or "")
    team_row = (
        f'<div class="fantasy-source-team">My team: <strong>{team}</strong></div>'
        if team
        else ""
    )

    if kind == "active_draft":
        name = _html_esc(display.get("draft_name") or "Active Draft")
        heading = _html_esc(display.get("active_heading") or "Active Draft")
        return f"""
<div class="fantasy-source-card fantasy-source-card-active">
  <div class="fantasy-source-kicker">{heading}</div>
  <div class="fantasy-source-name">{name}</div>
  {team_row}
</div>"""

    if kind in ("temporary_live", "temporary_simulator"):
        board = _html_esc(display.get("board_label") or "Temporary Draft Board (Unsaved)")
        return f"""
<div class="fantasy-source-card fantasy-source-card-temporary">
  <div class="fantasy-source-kicker">Temporary Draft Board (Unsaved)</div>
  <div class="fantasy-source-sub">{board}</div>
  {team_row}
</div>"""

    return f"""
<div class="fantasy-source-card fantasy-source-card-generic">
  <div class="fantasy-source-kicker">No draft context</div>
  <div class="fantasy-source-sub">General MLB — choose an Active League or Active Draft in Saved Draft Library</div>
  {team_row}
</div>"""


def fantasy_context_using_markdown(session: dict[str, Any]) -> str:
    """Markdown for a visible source banner on fantasy management pages."""
    display = fantasy_context_using_display(session)
    team = str(display.get("team") or "").strip()
    team_line = f"**My team:** {team}" if team else ""

    if display["kind"] == "active_draft":
        name = display.get("draft_name") or "Active Draft"
        heading = str(display.get("active_heading") or "Active Draft").strip()
        lines = [f"**{heading}:** {name}"]
        if team_line:
            lines.append(team_line)
        return "\n\n".join(lines)

    if display["kind"] == "temporary_live":
        lines = ["**Temporary Draft Board (Unsaved)** — Live Draft"]
        if team_line:
            lines.append(team_line)
        return "\n\n".join(lines)

    if display["kind"] == "temporary_simulator":
        lines = ["**Temporary Draft Board (Unsaved)**"]
        if team_line:
            lines.append(team_line)
        return "\n\n".join(lines)

    return "**General MLB** — no draft context selected"


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


def _board_team_names(table: pd.DataFrame) -> list[str]:
    if table is None or getattr(table, "empty", True):
        return []
    col = "Fantasy Team" if "Fantasy Team" in table.columns else ("Team" if "Team" in table.columns else "")
    if not col:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for raw in table[col].tolist():
        name = str(raw or "").strip()
        if not name or name.lower() in {"nan", "none"} or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _live_room_team_names(room: dict[str, Any] | None) -> list[str]:
    """Teams that belong to the current Live Draft board only."""
    if not isinstance(room, dict):
        return []
    teams = room.get("teams")
    names: list[str] = []
    seen: set[str] = set()
    if isinstance(teams, list):
        for t in teams:
            name = str(t or "").strip()
            if name and name.lower() not in {"nan", "none"} and name not in seen:
                seen.add(name)
                names.append(name)
    if names:
        return names
    board = room.get("draft_board") or room.get("pick_order") or []
    if isinstance(board, list):
        for row in board:
            if not isinstance(row, dict):
                continue
            name = str(row.get("Team") or row.get("team") or "").strip()
            if name and name.lower() not in {"nan", "none"} and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _resolve_my_team_for_ephemeral(session: dict[str, Any], *, source: FantasyContextSource) -> str:
    """Team identity for temporary Live/Simulator boards — never Active League's saved team."""
    if source.kind == SOURCE_SIMULATOR_BOARD:
        frozen = session.get("_draft_simulator_resume_identity")
        if isinstance(frozen, dict):
            frozen_team = str(frozen.get("user_team") or "").strip()
            if frozen_team:
                board_teams = _board_team_names(_resolve_simulator_board(session))
                if not board_teams or frozen_team in board_teams:
                    return frozen_team
        table = _resolve_simulator_board(session)
        board_teams = _board_team_names(table)
        candidate = str(session.get("room_your_team") or "").strip()
        if candidate and (not board_teams or candidate in board_teams):
            return candidate
        if board_teams:
            return board_teams[0]
        return candidate
    if source.kind == SOURCE_LIVE_DRAFT:
        room = _resolve_live_room(session)
        room_teams = _live_room_team_names(room if isinstance(room, dict) else None)
        # Prefer the Live Draft Room selectbox / room config — only if on this board.
        candidates: list[str] = []
        for key in ("live_draft_my_team",):
            val = str(session.get(key) or "").strip()
            if val:
                candidates.append(val)
        if isinstance(room, dict):
            cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
            for key in ("user_team", "your_team"):
                val = str(cfg.get(key) or "").strip()
                if val:
                    candidates.append(val)
            # Do not call resolve_current_account_team here — it loads league context via
            # get_effective_fantasy_context and would recurse forever.
            participant = str(session.get("draft_room_participant_team") or "").strip()
            if participant:
                candidates.append(participant)
        room_your = str(session.get("room_your_team") or "").strip()
        if room_your:
            candidates.append(room_your)
        for candidate in candidates:
            if candidate and (not room_teams or candidate in room_teams):
                return candidate
        if room_teams:
            return room_teams[0]
        return ""
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
        return _restore_saved_context_team(session, _get_saved_active_league_context(session))
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
            persist=False,
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
            persist=False,
        )
    return None


WORKFLOW_SOURCE_ACTIVE = "active_draft"
WORKFLOW_SOURCE_TEMPORARY_LIVE = "temporary_live"
WORKFLOW_SOURCE_TEMPORARY_SIMULATOR = "temporary_simulator"
WORKFLOW_SOURCE_GENERIC = "generic"


def _context_source_draft_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    meta = dict(context.get("metadata") or {})
    return str(meta.get("source_draft_id") or context.get("source_draft_id") or "").strip()


def _archive_matches_context(archive: dict[str, Any] | None, context: dict[str, Any] | None) -> bool:
    if not isinstance(archive, dict) or not isinstance(context, dict):
        return False
    aid = str(archive.get("draft_id") or "").strip()
    sid = _context_source_draft_id(context)
    if aid and sid and aid != sid:
        return False
    linked = str(archive.get("league_context_id") or "").strip()
    cid = str(context.get("league_context_id") or "").strip()
    if linked and cid and linked != cid:
        return False
    return bool(aid or sid)


def _workflow_team_names(context: dict[str, Any] | None) -> list[str]:
    if not isinstance(context, dict):
        return []
    rosters = context.get("league_rosters") or {}
    if not isinstance(rosters, dict):
        return []
    return sorted(str(name).strip() for name in rosters if str(name).strip())


def _workflow_short_league_name(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    for candidate in (
        str(context.get("league_name") or "").strip(),
        str(context.get("draft_name") or "").strip(),
        str(context.get("display_name") or "").strip(),
    ):
        if not candidate or _looks_ephemeral_draft_label(candidate):
            continue
        if " — " in candidate:
            return candidate.split(" — ", 1)[0].strip()
        if " - " in candidate:
            return candidate.split(" - ", 1)[0].strip()
        return candidate
    return ""


def _workflow_matchup_line(my_team: str, team_names: list[str]) -> str:
    my_team = str(my_team or "").strip()
    others = [t for t in team_names if t and t != my_team]
    if my_team and others:
        return f"{my_team} vs {' vs '.join(others[:3])}"
    if team_names:
        return " vs ".join(team_names[:4])
    return ""


def _workflow_descriptor_cache_fingerprint(session: dict[str, Any]) -> str:
    """Fingerprint that invalidates when override, board, or saved active pair changes."""
    source = resolve_fantasy_context_source(session)
    live_ov = int(bool(live_draft_sync_enabled(session)))
    sim_ov = int(bool(simulator_board_sync_enabled(session)))
    sim_picks = _simulator_board_pick_count(session)
    sim_teams = ",".join(_board_team_names(_simulator_board_table(session)))
    sim_my = ""
    frozen = session.get("_draft_simulator_resume_identity")
    if isinstance(frozen, dict):
        sim_my = str(frozen.get("user_team") or "").strip()
    if not sim_my:
        sim_my = str(session.get("room_your_team") or "").strip()

    live_id = ""
    live_rev = ""
    live_my = ""
    live_teams = ""
    room = _resolve_live_room(session)
    if isinstance(room, dict):
        live_id = str(room.get("draft_room_id") or room.get("room_id") or "").strip()
        board = room.get("draft_board") or []
        live_rev = str(
            room.get("revision")
            or room.get("updated_at")
            or (len(board) if isinstance(board, list) else 0)
        )
        live_team_names = _live_room_team_names(room)
        live_teams = ",".join(live_team_names)
        cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
        live_my = str(session.get("live_draft_my_team") or "").strip()
        if not live_my:
            live_my = str(cfg.get("user_team") or cfg.get("your_team") or "").strip()
        if live_my and live_team_names and live_my not in live_team_names:
            live_my = live_team_names[0] if live_team_names else ""

    active_draft = str(session.get("active_draft_archive_id") or "").strip()
    active_ctx = str(session.get("active_league_context_id") or "").strip()
    try:
        from fantasy_league_context import ensure_fantasy_league_context_state

        store = ensure_fantasy_league_context_state(session)
        active_ctx = str(store.get("active_league_context_id") or active_ctx).strip()
    except ImportError:
        pass

    auth = str(session.get("_suite_auth_user_id") or "").strip()
    workspace = str(session.get("_suite_active_workspace_id") or "").strip()
    return "|".join(
        [
            f"kind={source.kind}",
            f"origin={source.origin}",
            f"live_ov={live_ov}",
            f"sim_ov={sim_ov}",
            f"sim_picks={sim_picks}",
            f"sim_teams={sim_teams}",
            f"sim_my={sim_my}",
            f"live_id={live_id}",
            f"live_rev={live_rev}",
            f"live_my={live_my}",
            f"live_teams={live_teams}",
            f"active_draft={active_draft}",
            f"active_ctx={active_ctx}",
            f"auth={auth}",
            f"ws={workspace}",
        ]
    )


def _resolve_saved_active_workflow_pair(
    session: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Coherent saved Active League/Draft pair — never used while temporary override wins."""
    context: dict[str, Any] | None = None
    archive: dict[str, Any] | None = None
    try:
        from saved_draft_library_selection import resolve_coherent_active_library_selection

        sel = resolve_coherent_active_library_selection(session)
        linked = sel.get("linked_active_context") or sel.get("active_context")
        if isinstance(linked, dict):
            context = linked
        active_archive = sel.get("active_archive")
        if _archive_matches_context(
            active_archive if isinstance(active_archive, dict) else None,
            context,
        ):
            archive = active_archive if isinstance(active_archive, dict) else None
    except ImportError:
        context = None
    if not isinstance(context, dict):
        context = _get_saved_active_league_context(session)
    if isinstance(context, dict) and archive is None:
        try:
            from draft_archive_state import get_active_draft_archive, get_draft_archive

            draft_id = _context_source_draft_id(context)
            active_archive = get_active_draft_archive(session)
            if _archive_matches_context(active_archive, context):
                archive = active_archive
            elif draft_id:
                loaded = get_draft_archive(session, draft_id)
                if isinstance(loaded, dict):
                    archive = loaded
        except ImportError:
            pass
    return context, archive


def resolve_fantasy_workflow_source_descriptor(session: dict[str, Any]) -> dict[str, Any]:
    """Coherent workflow source — same context identity that feeds Lineup/Standings/Waiver data.

    Priority matches ``resolve_fantasy_context_source``:
    temporary Live/Simulator override → saved Active Draft/League → generic.
    """
    cache_fp = _workflow_descriptor_cache_fingerprint(session)
    if session.get("_workflow_descriptor_fp") == cache_fp:
        cached = session.get("_workflow_descriptor_cached")
        if isinstance(cached, dict):
            return dict(cached)

    empty: dict[str, Any] = {
        "draft_id": "",
        "league_context_id": "",
        "canonical_league_id": "",
        "display_name": "",
        "draft_type": "",
        "draft_type_label": "",
        "my_team_name": "",
        "team_names": [],
        "source_kind": WORKFLOW_SOURCE_GENERIC,
        "is_temporary_source": False,
        "active_heading": "",
        "subtitle": "",
        "matchup": "",
        "board_pick_count": 0,
        "descriptor_cache_fingerprint": cache_fp,
    }

    source = resolve_fantasy_context_source(session)
    context: dict[str, Any] | None = None
    archive: dict[str, Any] | None = None

    if source.kind in (SOURCE_SIMULATOR_BOARD, SOURCE_LIVE_DRAFT):
        # Temporary / natural board wins — never select the saved Active League for page data.
        context = get_effective_fantasy_context(session, respect_source_priority=True)
        archive = None
    elif source.kind == SOURCE_ACTIVE_DRAFT:
        context, archive = _resolve_saved_active_workflow_pair(session)
    else:
        session["_workflow_descriptor_fp"] = cache_fp
        session["_workflow_descriptor_cached"] = dict(empty)
        return empty

    if not isinstance(context, dict):
        session["_workflow_descriptor_fp"] = cache_fp
        session["_workflow_descriptor_cached"] = dict(empty)
        return empty

    league_context_id = str(context.get("league_context_id") or "").strip()
    draft_id = _context_source_draft_id(context)
    is_temporary = bool(
        source.kind in (SOURCE_SIMULATOR_BOARD, SOURCE_LIVE_DRAFT)
        or league_context_id.startswith("__ephemeral_")
        or is_ephemeral_league_context_id(league_context_id)
    )
    if is_temporary:
        # Temporary boards must not inherit saved Upload/Robins draft or league IDs.
        draft_id = ""
        archive = None
        if source.kind == SOURCE_LIVE_DRAFT and not league_context_id.startswith("__ephemeral_"):
            league_context_id = "__ephemeral_live__"
        if source.kind == SOURCE_SIMULATOR_BOARD and not league_context_id.startswith("__ephemeral_"):
            league_context_id = "__ephemeral_simulator__"

    try:
        from fantasy_league_identity import resolve_canonical_league_id

        canonical_league_id = str(resolve_canonical_league_id(context) or "").strip()
    except ImportError:
        canonical_league_id = str(dict(context.get("metadata") or {}).get("league_id") or "").strip()
    if is_temporary:
        canonical_league_id = ""

    my_team_name = str(context.get("my_team_name") or "").strip()
    if not my_team_name:
        try:
            from fantasy_league_team_ownership import (
                ownership_blocks_archive_team_fallback,
                resolve_account_fantasy_team,
            )

            my_team_name = str(resolve_account_fantasy_team(session, context) or "").strip()
            if not my_team_name and not ownership_blocks_archive_team_fallback(context) and isinstance(archive, dict):
                my_team_name = str(archive.get("team_name") or "").strip()
        except ImportError:
            if isinstance(archive, dict):
                my_team_name = str(archive.get("team_name") or "").strip()
    if not my_team_name and source.kind in (SOURCE_SIMULATOR_BOARD, SOURCE_LIVE_DRAFT):
        my_team_name = _resolve_my_team_for_ephemeral(session, source=source)
    if not my_team_name:
        try:
            from fantasy_workspace_team_identity import resolve_current_account_team_for_live_draft_and_league

            my_team_name = str(
                resolve_current_account_team_for_live_draft_and_league(session, context=context)
                or ""
            ).strip()
        except ImportError:
            pass

    team_names = _workflow_team_names(context)
    if not my_team_name and team_names:
        candidate = str(session.get("room_your_team") or "").strip()
        if candidate and candidate in team_names:
            my_team_name = candidate
        elif len(team_names) == 1:
            my_team_name = team_names[0]
    if is_temporary and source.kind == SOURCE_SIMULATOR_BOARD and not team_names:
        team_names = _board_team_names(_resolve_simulator_board(session))
    display_name = _workflow_short_league_name(context) or str(context.get("display_name") or "").strip()
    if is_temporary and source.kind == SOURCE_SIMULATOR_BOARD:
        display_name = "Draft Room Simulator Board"
    elif is_temporary and source.kind == SOURCE_LIVE_DRAFT:
        display_name = display_name or "Live Draft Room"

    draft_type = ""
    draft_type_label = ""
    if not is_temporary:
        try:
            from fantasy_league_context import resolve_archive_draft_type_with_reason

            draft_type, _, _ = resolve_archive_draft_type_with_reason(
                context=context,
                archive_entry=archive if isinstance(archive, dict) else None,
                session=session,
            )
            draft_type_label = draft_type_display({"draft_type": draft_type}) if draft_type else ""
        except ImportError:
            pass

    if is_temporary:
        active_heading = "Temporary Practice Board"
    else:
        try:
            from fantasy_context_terminology import active_context_label

            active_heading = active_context_label(context, archive if isinstance(archive, dict) else None)
        except ImportError:
            active_heading = "Active League"

    matchup = _workflow_matchup_line(my_team_name, team_names)
    board_pick_count = _simulator_board_pick_count(session) if source.kind == SOURCE_SIMULATOR_BOARD else 0
    if source.kind == SOURCE_LIVE_DRAFT:
        room = _resolve_live_room(session)
        if isinstance(room, dict):
            board = room.get("draft_board") or []
            board_pick_count = len(board) if isinstance(board, list) else 0

    subtitle_parts = [part for part in (draft_type_label, matchup) if part]
    if is_temporary and board_pick_count:
        my_count = 0
        rosters = context.get("league_rosters") if isinstance(context.get("league_rosters"), dict) else {}
        if my_team_name and isinstance(rosters.get(my_team_name), dict):
            players = rosters[my_team_name].get("players") or []
            my_count = len(players) if isinstance(players, list) else 0
        if my_count:
            subtitle_parts.append(f"{board_pick_count} picks / {my_count} players on {my_team_name}")
        else:
            subtitle_parts.append(f"{board_pick_count} picks")
    subtitle = " · ".join(subtitle_parts)

    if is_temporary:
        source_kind = (
            WORKFLOW_SOURCE_TEMPORARY_LIVE
            if source.kind == SOURCE_LIVE_DRAFT or league_context_id == "__ephemeral_live__"
            else WORKFLOW_SOURCE_TEMPORARY_SIMULATOR
        )
    elif draft_id or league_context_id:
        source_kind = WORKFLOW_SOURCE_ACTIVE
    else:
        source_kind = WORKFLOW_SOURCE_GENERIC

    # Keep context id/draft fields consistent with temporary semantics even if ephemeral
    # builder stamped blank metadata.
    if is_temporary:
        context = dict(context)
        context["league_context_id"] = league_context_id
        context["my_team_name"] = my_team_name or str(context.get("my_team_name") or "").strip()
        meta = dict(context.get("metadata") or {})
        meta.pop("source_draft_id", None)
        meta.pop("draft_id", None)
        meta.pop("league_id", None)
        context["metadata"] = meta
    elif my_team_name and not str(context.get("my_team_name") or "").strip():
        context = dict(context)
        context["my_team_name"] = my_team_name

    result = {
        "draft_id": draft_id,
        "league_context_id": league_context_id,
        "canonical_league_id": canonical_league_id,
        "display_name": display_name,
        "draft_type": draft_type,
        "draft_type_label": draft_type_label,
        "my_team_name": my_team_name,
        "team_names": team_names,
        "source_kind": source_kind,
        "is_temporary_source": is_temporary,
        "active_heading": active_heading,
        "subtitle": subtitle,
        "matchup": matchup,
        "board_pick_count": board_pick_count,
        "descriptor_cache_fingerprint": cache_fp,
        "context": context,
        "archive": archive if isinstance(archive, dict) else None,
    }
    session["_workflow_descriptor_fp"] = cache_fp
    session["_workflow_descriptor_cached"] = dict(result)
    return result


def collect_saved_vs_effective_source_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Two-layer diagnostics: saved Active League selection vs effective workflow source."""
    out: dict[str, Any] = {
        "saved_active_draft_id": "",
        "saved_active_context_id": "",
        "saved_active_name": "",
        "saved_active_team": "",
        "effective_source_kind": "",
        "effective_context_id": "",
        "effective_team": "",
        "effective_roster_team_names": [],
        "effective_board_pick_count": 0,
        "effective_context_fingerprint": "",
        "descriptor_cache_fingerprint": "",
        "context_coherent": True,
    }
    try:
        from draft_archive_state import get_active_draft_archive

        archive = get_active_draft_archive(session)
        if isinstance(archive, dict):
            out["saved_active_draft_id"] = str(archive.get("draft_id") or "").strip()
            out["saved_active_name"] = str(archive.get("draft_name") or "").strip()
            out["saved_active_team"] = str(archive.get("team_name") or "").strip()
            out["saved_active_context_id"] = str(archive.get("league_context_id") or "").strip()
    except ImportError:
        pass
    try:
        saved = _get_saved_active_league_context(session)
        if isinstance(saved, dict):
            out["saved_active_context_id"] = str(
                saved.get("league_context_id") or out["saved_active_context_id"] or ""
            ).strip()
            if not out["saved_active_name"]:
                out["saved_active_name"] = str(
                    saved.get("league_name") or saved.get("display_name") or ""
                ).strip()
            if not out["saved_active_team"]:
                out["saved_active_team"] = str(saved.get("my_team_name") or "").strip()
            if not out["saved_active_draft_id"]:
                out["saved_active_draft_id"] = _context_source_draft_id(saved)
    except Exception:
        pass

    desc = resolve_fantasy_workflow_source_descriptor(session)
    out["effective_source_kind"] = str(desc.get("source_kind") or "")
    out["effective_context_id"] = str(desc.get("league_context_id") or "")
    out["effective_team"] = str(desc.get("my_team_name") or "")
    out["effective_roster_team_names"] = list(desc.get("team_names") or [])
    out["effective_board_pick_count"] = int(desc.get("board_pick_count") or 0)
    out["descriptor_cache_fingerprint"] = str(desc.get("descriptor_cache_fingerprint") or "")
    try:
        from resolved_fantasy_context import RESOLVED_DIAG_KEY

        raw = session.get(RESOLVED_DIAG_KEY)
        if isinstance(raw, dict):
            out["effective_context_fingerprint"] = str(raw.get("context_fingerprint") or "")
            out["context_coherent"] = bool(raw.get("context_coherent", True))
    except ImportError:
        pass
    return out


def invalidate_fantasy_workflow_descriptor_cache(session: dict[str, Any]) -> None:
    session.pop("_workflow_descriptor_fp", None)
    session.pop("_workflow_descriptor_cached", None)


def is_ephemeral_league_context_id(league_context_id: str) -> bool:
    try:
        from fantasy_league_context import is_ephemeral_league_context_id as _is_ephemeral

        return _is_ephemeral(str(league_context_id or ""))
    except ImportError:
        return str(league_context_id or "").strip().startswith("__ephemeral_")


def draft_type_display(entry: dict[str, Any] | None) -> str:
    try:
        from draft_archive_state import draft_type_display as _display

        return _display(entry)
    except ImportError:
        return str((entry or {}).get("draft_type") or "").replace("_", " ").title()


def fantasy_workflow_using_html(session: dict[str, Any]) -> str:
    """Workflow-page header card — uses the same descriptor as page data."""
    desc = resolve_fantasy_workflow_source_descriptor(session)
    team = _html_esc(desc.get("my_team_name") or "")
    team_row = (
        f'<div class="fantasy-source-team">My team: <strong>{team}</strong></div>'
        if team
        else ""
    )
    kind = str(desc.get("source_kind") or WORKFLOW_SOURCE_GENERIC)

    if kind == WORKFLOW_SOURCE_ACTIVE:
        heading = _html_esc(desc.get("active_heading") or "Active League")
        name = _html_esc(desc.get("display_name") or "League")
        subtitle = _html_esc(desc.get("subtitle") or "")
        sub_row = f'<div class="fantasy-source-sub">{subtitle}</div>' if subtitle else ""
        return f"""
<div class="fantasy-source-card fantasy-source-card-active">
  <div class="fantasy-source-kicker">{heading}</div>
  <div class="fantasy-source-name">{name}</div>
  {team_row}
  {sub_row}
</div>"""

    if kind in (WORKFLOW_SOURCE_TEMPORARY_LIVE, WORKFLOW_SOURCE_TEMPORARY_SIMULATOR):
        board = "Live Draft Room — unsaved" if kind == WORKFLOW_SOURCE_TEMPORARY_LIVE else "Draft Room Simulator — unsaved"
        board = _html_esc(board)
        matchup = _html_esc(desc.get("matchup") or "")
        subtitle = _html_esc(desc.get("subtitle") or "")
        matchup_row = f'<div class="fantasy-source-sub">{matchup}</div>' if matchup else ""
        # Prefer matchup alone under team; append pick counts from subtitle when distinct.
        detail = ""
        raw_sub = str(desc.get("subtitle") or "")
        if raw_sub and matchup and matchup in raw_sub:
            remainder = raw_sub.replace(str(desc.get("matchup") or ""), "", 1).strip(" ·")
            if remainder:
                detail = f'<div class="fantasy-source-sub">{_html_esc(remainder)}</div>'
        elif subtitle and not matchup:
            detail = f'<div class="fantasy-source-sub">{subtitle}</div>'
        return f"""
<div class="fantasy-source-card fantasy-source-card-temporary">
  <div class="fantasy-source-kicker">Temporary Practice Board</div>
  <div class="fantasy-source-sub">{board}</div>
  {team_row}
  {matchup_row}
  {detail}
</div>"""

    return f"""
<div class="fantasy-source-card fantasy-source-card-generic">
  <div class="fantasy-source-kicker">No draft context</div>
  <div class="fantasy-source-sub">General MLB — choose an Active League or Active Draft in Saved Draft Library</div>
  {team_row}
</div>"""


def prepare_fantasy_context_source_defaults(session: dict[str, Any]) -> None:
    """Seed missing toggle keys once — never overwrite an explicit user choice."""
    session.setdefault(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, FANTASY_CONTEXT_TOGGLE_DEFAULT)
    session.setdefault(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, FANTASY_CONTEXT_TOGGLE_DEFAULT)
