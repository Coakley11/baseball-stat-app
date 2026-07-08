"""Global fantasy settings — Draft Team and Fantasy Format shared across all pages.

The canonical keys are `room_your_team` (team) and `room_format` (format). Every
baseball page that has a team or format selector uses a local alias. This module
provides a single write path and a `prepare_global_fantasy_settings` function that
mirrors the canonicals into all alias keys before widgets render, so that changing
team/format on one page propagates to every other page.
"""

from __future__ import annotations

from typing import Any

# ── canonical keys (persisted top-level in the cloud blob) ──────────────────
GLOBAL_TEAM_KEY = "room_your_team"
GLOBAL_FORMAT_KEY = "room_format"

CANONICAL_ROTO = "5x5 Roto"
CANONICAL_POINTS = "Points League"
LINEUP_H2H_FORMAT = "Head-to-Head Categories"
LIVE_SCORING_ROTO = "Roto (5x5)"
LIVE_SCORING_POINTS = "Points League"

# Optional words between "my" and "team/roster" (e.g. "my fantasy team").
_MY_TEAM_MIDDLE = r"(?:\s+\w+){0,3}"

# ── page-local aliases that should mirror the canonical values ───────────────
# Maps alias key → canonical key.
# Pages whose alias intentionally differs (e.g. lineup_format can be H2H) are
# left out so they manage their own defaults.
TEAM_ALIASES: dict[str, str] = {
    "draft_assistant_synced_team": GLOBAL_TEAM_KEY,
    "sleeper_sync_team": GLOBAL_TEAM_KEY,
    "comparison_user_team": GLOBAL_TEAM_KEY,
    "trend_sync_team_for_draft": GLOBAL_TEAM_KEY,
    "value_sync_team_for_draft": GLOBAL_TEAM_KEY,
    "lineup_team": GLOBAL_TEAM_KEY,
}

FORMAT_ALIASES: dict[str, str] = {
    "draft_format": GLOBAL_FORMAT_KEY,
    "fantasy_market_format": GLOBAL_FORMAT_KEY,
    "draft_lab_scoring_type": GLOBAL_FORMAT_KEY,
    "standings_scoring_format": GLOBAL_FORMAT_KEY,
}

# Keys that use alternate labels but should still follow canonical format.
LIVE_FORMAT_ALIASES: dict[str, str] = {
    "live_draft_scoring": GLOBAL_FORMAT_KEY,
}

_ALL_ALIASES: dict[str, str] = {**TEAM_ALIASES, **FORMAT_ALIASES}

# Keys owned globally — never save/restore from per-page snapshots (prevents stale
# Daniel vs Team 2 drift when navigating between draft pages).
_GLOBAL_SNAPSHOT_EXCLUDED: frozenset[str] = frozenset(
    {
        GLOBAL_TEAM_KEY,
        GLOBAL_FORMAT_KEY,
        *TEAM_ALIASES.keys(),
        *FORMAT_ALIASES.keys(),
        *LIVE_FORMAT_ALIASES.keys(),
        "live_draft_my_team",
        # Roto/points always mirror room_format; only H2H is lineup-local (see resolve_lineup_scoring_format).
        "lineup_format",
    }
)


def global_settings_snapshot_excluded_keys() -> frozenset[str]:
    """Session keys that must not be read/written via page_filter_state snapshots."""
    return _GLOBAL_SNAPSHOT_EXCLUDED


def active_fantasy_team_source(session: dict[str, Any]) -> str:
    """Which subsystem owns the active fantasy team."""
    try:
        from fantasy_context_source import (
            SOURCE_ACTIVE_DRAFT,
            SOURCE_LIVE_DRAFT,
            SOURCE_SIMULATOR_BOARD,
            resolve_fantasy_context_source,
        )

        kind = resolve_fantasy_context_source(session).kind
        if kind == SOURCE_LIVE_DRAFT:
            return "live_draft"
        if kind == SOURCE_SIMULATOR_BOARD:
            return "draft_room"
        if kind == SOURCE_ACTIVE_DRAFT:
            return "active_draft"
    except ImportError:
        pass
    if _saved_active_league_team_info(session):
        return "active_draft"
    try:
        from live_draft_state import has_active_live_draft

        if has_active_live_draft(session):
            return "live_draft"
    except ImportError:
        pass
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        status = str(room.get("status") or "").strip()
        if status in ("in_progress", "paused"):
            return "live_draft"
    return "draft_room"


def _saved_active_league_team_info(session: dict[str, Any]) -> tuple[str, str] | None:
    """Return (team_name, draft_label) for the Saved Draft Library Active Draft only."""
    try:
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session, respect_source_priority=False)
    except ImportError:
        return None
    if not isinstance(ctx, dict):
        return None
    team = str(ctx.get("my_team_name") or "").strip()
    if not team:
        return None
    label = str(ctx.get("display_name") or ctx.get("draft_name") or "").strip()
    if not label:
        try:
            from draft_archive_state import get_active_draft_archive

            archive = get_active_draft_archive(session)
            if isinstance(archive, dict):
                label = str(archive.get("draft_name") or "").strip()
        except ImportError:
            pass
    return team, label or "Active Draft"


def _active_league_team_info(session: dict[str, Any]) -> tuple[str, str] | None:
    """Return (team_name, draft_label) when the effective fantasy context has a team."""
    src = active_fantasy_team_source(session)
    if src == "active_draft":
        return _saved_active_league_team_info(session)
    if src == "live_draft":
        team = _live_draft_team_name(session)
        if team:
            return team, "Live Draft"
    if src == "draft_room":
        team = str(session.get(GLOBAL_TEAM_KEY) or "").strip()
        if team:
            return team, "Draft Room Simulator"
    return None


def _live_draft_team_name(session: dict[str, Any]) -> str:
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
        for key in ("user_team", "your_team"):
            val = cfg.get(key)
            if val:
                return str(val).strip()
        teams = room.get("teams")
        if isinstance(teams, list) and teams:
            return str(teams[0]).strip()
    return ""


def get_active_fantasy_team(session: dict[str, Any]) -> str:
    """Single active fantasy team for the whole app."""
    try:
        from draft_room_context import is_multiplayer_draft_active, recommendation_team

        if is_multiplayer_draft_active(session):
            mp_team = str(recommendation_team(session) or "").strip()
            if not mp_team:
                try:
                    from draft_room_participant_state import ACTIVE_PARTICIPANT_TEAM_KEY

                    mp_team = str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "").strip()
                except ImportError:
                    pass
            if mp_team:
                return mp_team
    except ImportError:
        pass
    src = active_fantasy_team_source(session)
    if src == "live_draft":
        team = _live_draft_team_name(session)
        if team:
            return team
    if src == "active_draft":
        league_info = _saved_active_league_team_info(session)
        if league_info:
            return league_info[0]
    return str(session.get(GLOBAL_TEAM_KEY) or "").strip()


def sync_active_fantasy_team_to_canonical(session: dict[str, Any]) -> str:
    """Push the active source-of-truth team into ``room_your_team`` and aliases."""
    src = active_fantasy_team_source(session)
    if src == "active_draft":
        league_info = _saved_active_league_team_info(session)
        if league_info:
            team = league_info[0]
            session[GLOBAL_TEAM_KEY] = team
            _mirror_globals_to_aliases(session)
            session["_active_fantasy_team_source"] = "active_draft"
            propagated = {alias: session.get(alias) for alias in _ALL_ALIASES}
            session["_global_settings_last_propagated"] = propagated
            return team
    team = get_active_fantasy_team(session)
    if team:
        session[GLOBAL_TEAM_KEY] = team
        _mirror_globals_to_aliases(session)
        if src == "live_draft":
            _sync_live_draft_room_team(session)
        propagated = {alias: session.get(alias) for alias in _ALL_ALIASES}
        session["_global_settings_last_propagated"] = propagated
    session["_active_fantasy_team_source"] = src
    return team


def active_fantasy_team_label(session: dict[str, Any]) -> str:
    """Human-readable label for dev UI / captions."""
    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            team = get_active_fantasy_team(session) or "—"
            return f"{team} (Shared Draft Room)"
    except ImportError:
        pass
    league_info = _active_league_team_info(session)
    if league_info:
        team, label = league_info
        return f"{team} ({label})"
    team = get_active_fantasy_team(session) or "—"
    src = active_fantasy_team_source(session)
    if src == "live_draft":
        return f"{team} (Live Draft)"
    return f"{team} (Draft Room)"


ACTIVE_TEAM_CHANGE_GUIDANCE = (
    "You can change this in **Draft Room Simulator**, **Live Draft Room**, "
    "or **Saved Draft Library** (by changing the Active Draft)."
)


def active_fantasy_team_caption(session: dict[str, Any], *, label: str = "Your team") -> str:
    """Caption explaining the active team label and where to change it."""
    return f"**{label}:** {active_fantasy_team_label(session)}. {ACTIVE_TEAM_CHANGE_GUIDANCE}"


# Dev trace ring buffer key — records each lifecycle step for canonical format/team.
_FORMAT_TRACE_KEY = "_global_format_trace"
_FORMAT_TRACE_MAX = 40


def normalize_league_format(val: Any) -> str:
    """Map Roto / 5x5 Roto / Points / Points League / Roto (5x5) → canonical label."""
    s = str(val or "").strip()
    if not s:
        return CANONICAL_ROTO
    low = s.lower()
    if "point" in low:
        return CANONICAL_POINTS
    if "roto" in low or "5x5" in low:
        return CANONICAL_ROTO
    if low in (CANONICAL_ROTO.lower(), CANONICAL_POINTS.lower()):
        return CANONICAL_ROTO if low == CANONICAL_ROTO.lower() else CANONICAL_POINTS
    return CANONICAL_ROTO


def to_live_draft_scoring(fmt: Any) -> str:
    return LIVE_SCORING_POINTS if normalize_league_format(fmt) == CANONICAL_POINTS else LIVE_SCORING_ROTO


def from_live_draft_scoring(scoring: Any) -> str:
    return normalize_league_format(scoring)


def record_global_settings_trace(session: dict[str, Any], step: str) -> None:
    """Append a snapshot of canonical + alias format/team values for debugging.

    Inspect ``st.session_state['_global_format_trace']`` in Dev Mode to see the
    full lifecycle: before render, after on_change, snapshot, restore, final.
    """
    try:
        from suite_workspace import developer_ui_visible_from_session

        if not developer_ui_visible_from_session(session):
            return
    except ImportError:
        return
    try:
        entry = {
            "step": step,
            "canonical_format": session.get(GLOBAL_FORMAT_KEY),
            "canonical_team": session.get(GLOBAL_TEAM_KEY),
            "canonical_team_count": session.get("room_team_count"),
            "format_aliases": {a: session.get(a) for a in FORMAT_ALIASES},
            "live_draft_scoring": session.get("live_draft_scoring"),
            "team_aliases": {a: session.get(a) for a in TEAM_ALIASES},
        }
        trace = session.get(_FORMAT_TRACE_KEY)
        if not isinstance(trace, list):
            trace = []
        trace.append(entry)
        session[_FORMAT_TRACE_KEY] = trace[-_FORMAT_TRACE_MAX:]
    except Exception:
        pass


def _canonical_value(session: dict[str, Any], canonical_key: str) -> Any:
    return session.get(canonical_key)


def _mirror_live_format_aliases(session: dict[str, Any], fmt: str) -> None:
    """Push canonical format into live-draft scoring labels."""
    canonical = normalize_league_format(fmt)
    for alias in LIVE_FORMAT_ALIASES:
        session[alias] = to_live_draft_scoring(canonical)


def write_canonical_global_fantasy_settings(
    session: dict[str, Any],
    *,
    team: str | None = None,
    format_: str | None = None,
    reason: str = "",
) -> None:
    """Write team and/or format to the canonical keys and mirror into all aliases."""
    if team is not None:
        session[GLOBAL_TEAM_KEY] = str(team).strip()
    if format_ is not None:
        session[GLOBAL_FORMAT_KEY] = normalize_league_format(format_)
    _mirror_globals_to_aliases(session)
    if format_ is not None or session.get(GLOBAL_FORMAT_KEY) is not None:
        _mirror_live_format_aliases(session, session.get(GLOBAL_FORMAT_KEY) or CANONICAL_ROTO)
    record_global_settings_trace(session, f"write_canonical:{reason or 'unspecified'}")
    try:
        from draft_room_state import mark_draft_room_local_edit

        mark_draft_room_local_edit(session)
    except Exception:
        pass


def _lineup_format_is_h2h(session: dict[str, Any]) -> bool:
    return str(session.get("lineup_format") or "").strip() == LINEUP_H2H_FORMAT


def sync_lineup_format_from_canonical(session: dict[str, Any], *, force: bool = False) -> None:
    """Mirror canonical roto/points into lineup_format unless user chose H2H."""
    session["lineup_format"] = resolve_lineup_scoring_format(session, force=force)


def resolve_lineup_scoring_format(session: dict[str, Any], *, force: bool = False) -> str:
    """Return the scoring format Lineup Assistant should use (canonical unless H2H)."""
    if _lineup_format_is_h2h(session) and not force:
        return LINEUP_H2H_FORMAT
    return normalize_league_format(session.get(GLOBAL_FORMAT_KEY) or CANONICAL_ROTO)


def _mirror_globals_to_aliases(session: dict[str, Any]) -> None:
    """Push canonical team/format values into all alias keys."""
    team = session.get(GLOBAL_TEAM_KEY)
    fmt = normalize_league_format(session.get(GLOBAL_FORMAT_KEY) or CANONICAL_ROTO)
    session[GLOBAL_FORMAT_KEY] = fmt
    for alias, canonical_key in _ALL_ALIASES.items():
        canonical_val = team if canonical_key == GLOBAL_TEAM_KEY else fmt
        if canonical_val is not None:
            session[alias] = canonical_val
    sync_lineup_format_from_canonical(session)


def prepare_global_fantasy_settings(
    session: dict[str, Any],
    *,
    force_mirror: bool = False,
) -> None:
    """Call before widgets on any baseball page that uses team or format.

    Propagates the canonical team/format into all alias keys so that a change
    made on one page is visible on every other page without explicit contextual
    transfers.

    When ``force_mirror=True`` (called after page navigation / restore), the
    canonical value always wins over any stale per-page snapshot value.  This is
    the correct behavior on navigation because the snapshot was saved before the
    canonical was updated.

    When ``force_mirror=False`` (called during a same-page rerun), the alias is
    only overwritten if it still matches the previously-propagated value — i.e.
    the user has not edited that alias locally on its own page.
    """
    team = session.get(GLOBAL_TEAM_KEY)
    fmt = session.get(GLOBAL_FORMAT_KEY)
    try:
        from fantasy_context_source import prepare_fantasy_context_source_defaults

        prepare_fantasy_context_source_defaults(session)
    except ImportError:
        pass
    if team is None and fmt is None:
        return
    normalized_fmt = normalize_league_format(fmt or CANONICAL_ROTO) if fmt is not None else None
    if normalized_fmt is not None:
        session[GLOBAL_FORMAT_KEY] = normalized_fmt
    for alias, canonical_key in _ALL_ALIASES.items():
        canonical_val = team if canonical_key == GLOBAL_TEAM_KEY else normalized_fmt
        if canonical_val is None:
            continue
        if alias not in session:
            session[alias] = canonical_val
        elif session[alias] != canonical_val:
            if force_mirror:
                # After page navigation: canonical wins; stale snapshot overwritten.
                session[alias] = canonical_val
            else:
                # Same-page rerun: only override if the alias was last written by us.
                last = session.get("_global_settings_last_propagated") or {}
                if isinstance(last, dict) and last.get(alias) == session[alias]:
                    session[alias] = canonical_val
    if normalized_fmt is not None:
        _mirror_live_format_aliases(session, normalized_fmt)
        sync_lineup_format_from_canonical(session, force=force_mirror)
    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            pteam = active_participant_team(session)
            if pteam and pteam != session.get(GLOBAL_TEAM_KEY):
                session[GLOBAL_TEAM_KEY] = pteam
                for alias, canonical_key in _ALL_ALIASES.items():
                    if canonical_key == GLOBAL_TEAM_KEY:
                        session[alias] = pteam
    except ImportError:
        pass
    # Record what we propagated so we can detect vs user-local edits next time.
    propagated = {alias: session.get(alias) for alias in _ALL_ALIASES}
    session["_global_settings_last_propagated"] = propagated
    record_global_settings_trace(
        session, f"prepare_global{'(force)' if force_mirror else ''}"
    )


def mirror_canonical_to_all_aliases(session: dict[str, Any]) -> None:
    """Unconditionally push canonical team/format into every alias.

    Use this after page navigation / restore so that all alias keys reflect the
    current canonical values, regardless of what the old page snapshot had.
    Equivalent to ``prepare_global_fantasy_settings(session, force_mirror=True)``.
    """
    prepare_global_fantasy_settings(session, force_mirror=True)
    _sync_live_draft_room_team(session)


def _sync_live_draft_room_team(session: dict[str, Any]) -> None:
    """Keep live draft room config in sync with canonical ``room_your_team``."""
    team = str(session.get(GLOBAL_TEAM_KEY) or "").strip()
    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            pteam = active_participant_team(session)
            if pteam:
                team = pteam
    except ImportError:
        pass
    if not team:
        return
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return
    teams = room.get("teams")
    if isinstance(teams, list) and team not in [str(t) for t in teams]:
        return
    cfg = room.get("config")
    if not isinstance(cfg, dict):
        cfg = {}
        room["config"] = cfg
    if cfg.get("user_team") == team and cfg.get("your_team") == team:
        return
    cfg["user_team"] = team
    cfg["your_team"] = team


def on_alias_team_changed(session: dict[str, Any], alias_key: str) -> None:
    """Deprecated — team is owned by Draft Room or Live Draft only."""
    if active_fantasy_team_source(session) == "live_draft":
        return
    new_team = session.get(alias_key) or session.get(GLOBAL_TEAM_KEY)
    if new_team is not None:
        write_canonical_global_fantasy_settings(session, team=str(new_team).strip(), reason=f"alias:{alias_key}")


def on_alias_format_changed(session: dict[str, Any], alias_key: str) -> None:
    """on_change for any alias format selectbox — promote to canonical and mirror everywhere."""
    new_fmt = session.get(alias_key) or session.get(GLOBAL_FORMAT_KEY)
    if new_fmt is not None:
        write_canonical_global_fantasy_settings(session, format_=str(new_fmt).strip())


def on_lineup_format_changed(session: dict[str, Any]) -> None:
    """on_change for lineup scoring — roto/points update canonical; H2H stays lineup-local."""
    lf = str(session.get("lineup_format") or "").strip()
    if lf == LINEUP_H2H_FORMAT:
        return
    if lf:
        write_canonical_global_fantasy_settings(session, format_=lf, reason="lineup_format")


def on_global_team_changed(session: dict[str, Any]) -> None:
    """on_change callback for canonical team selectbox — write canonical + mirror."""
    write_canonical_global_fantasy_settings(session, team=session.get(GLOBAL_TEAM_KEY))


def on_global_format_changed(session: dict[str, Any]) -> None:
    """on_change callback for canonical format selectbox — write canonical + mirror."""
    write_canonical_global_fantasy_settings(session, format_=session.get(GLOBAL_FORMAT_KEY))


def on_live_draft_scoring_changed(session: dict[str, Any]) -> None:
    """on_change for live_draft_scoring — map Roto (5x5) labels to canonical room_format."""
    scoring = session.get("live_draft_scoring")
    if scoring is not None:
        write_canonical_global_fantasy_settings(
            session,
            format_=from_live_draft_scoring(scoring),
            reason="live_draft_scoring_changed",
        )

