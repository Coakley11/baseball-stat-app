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

_ALL_ALIASES: dict[str, str] = {**TEAM_ALIASES, **FORMAT_ALIASES}


def _canonical_value(session: dict[str, Any], canonical_key: str) -> Any:
    return session.get(canonical_key)


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
        session[GLOBAL_FORMAT_KEY] = str(format_).strip()
    _mirror_globals_to_aliases(session)
    try:
        from draft_room_state import mark_draft_room_local_edit
        mark_draft_room_local_edit(session)
    except Exception:
        pass


def _mirror_globals_to_aliases(session: dict[str, Any]) -> None:
    """Push canonical team/format values into all alias keys."""
    team = session.get(GLOBAL_TEAM_KEY)
    fmt = session.get(GLOBAL_FORMAT_KEY)
    for alias, canonical_key in _ALL_ALIASES.items():
        canonical_val = team if canonical_key == GLOBAL_TEAM_KEY else fmt
        if canonical_val is not None:
            session[alias] = canonical_val


def prepare_global_fantasy_settings(session: dict[str, Any]) -> None:
    """Call before widgets on any baseball page that uses team or format.

    Propagates the canonical team/format into all alias keys so that a change
    made on one page is visible on every other page without explicit contextual
    transfers.

    Does NOT overwrite an alias that is already locally set to a different value
    via its own widget — only seeds it if it's absent or matches the previous
    canonical propagation.
    """
    team = session.get(GLOBAL_TEAM_KEY)
    fmt = session.get(GLOBAL_FORMAT_KEY)
    if team is None and fmt is None:
        return
    for alias, canonical_key in _ALL_ALIASES.items():
        canonical_val = team if canonical_key == GLOBAL_TEAM_KEY else fmt
        if canonical_val is None:
            continue
        if alias not in session:
            session[alias] = canonical_val
        elif session[alias] != canonical_val:
            # Only override if the alias was last written by canonical propagation
            # (tracked via _global_settings_last_propagated). If the user explicitly
            # changed the alias on its own page, respect that choice.
            last = session.get("_global_settings_last_propagated") or {}
            if isinstance(last, dict) and last.get(alias) == session[alias]:
                session[alias] = canonical_val
    # Record what we propagated so we can detect vs user-local edits next time.
    propagated = {alias: session.get(alias) for alias in _ALL_ALIASES}
    session["_global_settings_last_propagated"] = propagated


def on_global_team_changed(session: dict[str, Any]) -> None:
    """on_change callback for any team selectbox — write canonical + mirror."""
    write_canonical_global_fantasy_settings(session, team=session.get(GLOBAL_TEAM_KEY))


def on_global_format_changed(session: dict[str, Any]) -> None:
    """on_change callback for any format selectbox — write canonical + mirror."""
    write_canonical_global_fantasy_settings(session, format_=session.get(GLOBAL_FORMAT_KEY))
