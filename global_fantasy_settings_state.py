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
LIVE_SCORING_ROTO = "Roto (5x5)"
LIVE_SCORING_POINTS = "Points League"

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


def _mirror_globals_to_aliases(session: dict[str, Any]) -> None:
    """Push canonical team/format values into all alias keys."""
    team = session.get(GLOBAL_TEAM_KEY)
    fmt = normalize_league_format(session.get(GLOBAL_FORMAT_KEY) or CANONICAL_ROTO)
    session[GLOBAL_FORMAT_KEY] = fmt
    for alias, canonical_key in _ALL_ALIASES.items():
        canonical_val = team if canonical_key == GLOBAL_TEAM_KEY else fmt
        if canonical_val is not None:
            session[alias] = canonical_val


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


def on_alias_team_changed(session: dict[str, Any], alias_key: str) -> None:
    """on_change for any alias team selectbox — promote to canonical and mirror everywhere."""
    new_team = session.get(alias_key) or session.get(GLOBAL_TEAM_KEY)
    if new_team is not None:
        write_canonical_global_fantasy_settings(session, team=str(new_team).strip())


def on_alias_format_changed(session: dict[str, Any], alias_key: str) -> None:
    """on_change for any alias format selectbox — promote to canonical and mirror everywhere."""
    new_fmt = session.get(alias_key) or session.get(GLOBAL_FORMAT_KEY)
    if new_fmt is not None:
        write_canonical_global_fantasy_settings(session, format_=str(new_fmt).strip())


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

