"""Canonical roster-position validation for Live Draft, simulator, and uploaded leagues.

Live Draft configures required positions before start.
Simulator / uploaded drafts configure positions after the draft via commissioner setup.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

LIVE_DRAFT_SETUP_ERROR = (
    "Draft picks per team must be greater than or equal to the number of required roster positions."
)

# Session keys for position-specific Waiver Wire correction mode.
WAIVER_CORRECTION_MODE_KEY = "waiver_position_correction_mode"
WAIVER_CORRECTION_POSITION_KEY = "waiver_correction_position_code"
WAIVER_CORRECTION_LABEL_KEY = "waiver_correction_position_label"

_STARTER_POSITION_CODES: tuple[str, ...] = ("C", "1B", "2B", "3B", "SS", "OF", "DH", "P")

_POSITION_DISPLAY: dict[str, dict[str, str]] = {
    "C": {"singular": "catcher", "plural": "Catchers", "title": "Catcher"},
    "1B": {"singular": "first baseman", "plural": "First Basemen", "title": "First Base"},
    "2B": {"singular": "second baseman", "plural": "Second Basemen", "title": "Second Base"},
    "3B": {"singular": "third baseman", "plural": "Third Basemen", "title": "Third Base"},
    "SS": {"singular": "shortstop", "plural": "Shortstops", "title": "Shortstop"},
    "OF": {"singular": "outfielder", "plural": "Outfielders", "title": "Outfield"},
    "DH": {"singular": "utility player", "plural": "Utility Players", "title": "Utility"},
    "UTIL": {"singular": "utility player", "plural": "Utility Players", "title": "Utility"},
    "P": {"singular": "pitcher", "plural": "Pitchers", "title": "Pitcher"},
}


def normalize_position_code(code: str) -> str:
    pos = str(code or "").strip().upper()
    if pos == "UTIL":
        return "DH"
    if pos in ("LF", "CF", "RF"):
        return "OF"
    if pos in ("SP", "RP"):
        return "P"
    if pos in ("BN", "BENCH"):
        return "BN"
    return pos


def position_display_names(code: str) -> dict[str, str]:
    pos = normalize_position_code(code)
    return dict(_POSITION_DISPLAY.get(pos) or {"singular": pos.lower(), "plural": pos, "title": pos})


def missing_position_message(code: str) -> str:
    names = position_display_names(code)
    return f"Missing {names['singular']}"


def open_waiver_button_label(code: str) -> str:
    names = position_display_names(code)
    return f"Open Waiver Wire for {names['plural']}"


def count_required_starting_positions(slots: dict[str, Any] | None) -> int:
    """Count required starter slots (excludes bench)."""
    raw = dict(slots or {})
    total = 0
    for code in _STARTER_POSITION_CODES:
        try:
            total += max(0, int(raw.get(code, 0) or 0))
        except (TypeError, ValueError):
            continue
    # UTIL may appear as a lineup token mapped into DH already; also accept UTIL key.
    if "UTIL" in raw and "DH" not in raw:
        try:
            total += max(0, int(raw.get("UTIL", 0) or 0))
        except (TypeError, ValueError):
            pass
    return total


def count_bench_slots(slots: dict[str, Any] | None) -> int:
    raw = dict(slots or {})
    try:
        return max(0, int(raw.get("BN", 0) or 0))
    except (TypeError, ValueError):
        return 0


def total_configured_roster_slots(slots: dict[str, Any] | None) -> int:
    return count_required_starting_positions(slots) + count_bench_slots(slots)


def validate_live_draft_setup(
    *,
    picks_per_team: int,
    slots: dict[str, Any] | None,
) -> dict[str, Any]:
    """Live Draft Room only — picks per team must cover required starter positions."""
    picks = max(0, int(picks_per_team or 0))
    required = count_required_starting_positions(slots)
    if required <= 0:
        return {
            "ok": False,
            "error": "Configure at least one required roster position before starting the Live Draft.",
            "picks_per_team": picks,
            "required_positions": required,
            "bench_slots": count_bench_slots(slots),
            "extra_picks": 0,
        }
    if picks < required:
        return {
            "ok": False,
            "error": LIVE_DRAFT_SETUP_ERROR,
            "picks_per_team": picks,
            "required_positions": required,
            "bench_slots": count_bench_slots(slots),
            "extra_picks": 0,
        }
    return {
        "ok": True,
        "error": "",
        "picks_per_team": picks,
        "required_positions": required,
        "bench_slots": count_bench_slots(slots),
        "extra_picks": max(0, picks - required),
    }


def ensure_bench_slots_for_extra_picks(
    slots: dict[str, Any] | None,
    picks_per_team: int,
) -> dict[str, int]:
    """Place surplus picks on the bench. Never discard players or shrink starters."""
    from live_draft_roster_slots import get_required_position_counts

    out = dict(get_required_position_counts({"slots": dict(slots or {})}))
    required = count_required_starting_positions(out)
    picks = max(0, int(picks_per_team or 0))
    extras = max(0, picks - required)
    current_bn = count_bench_slots(out)
    if extras > current_bn:
        out["BN"] = extras
    return out


def no_expansion_draft_allowed(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Explicit product rule — never create a second/expansion draft after position config."""
    del context
    return {
        "allowed": False,
        "reason": (
            "Roster corrections use Waiver Wire, add/drop, and trades — "
            "not a second or expansion draft."
        ),
    }


def _roster_df_from_players(players: list[dict[str, Any]] | None) -> pd.DataFrame:
    rows = [dict(p) for p in (players or []) if isinstance(p, dict)]
    if not rows:
        return pd.DataFrame()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        name = str(
            out.get("fullName")
            or out.get("Player")
            or out.get("player_name")
            or out.get("name")
            or ""
        ).strip()
        if name:
            out.setdefault("fullName", name)
            out.setdefault("Player", name)
        primary = str(out.get("Primary Position") or out.get("Position") or "").strip()
        if not primary:
            positions = out.get("positions") or out.get("Eligibility") or []
            if isinstance(positions, str):
                primary = positions
            elif isinstance(positions, (list, tuple)):
                primary = "/".join(str(p).strip() for p in positions if str(p).strip())
        if primary:
            out["Primary Position"] = primary
        normalized.append(out)
    return pd.DataFrame(normalized)


def evaluate_team_roster(
    *,
    roster_df: pd.DataFrame | None = None,
    players: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    max_roster_count: int | None = None,
) -> dict[str, Any]:
    """Canonical coverage snapshot used by Team Management, Lineup, and Waiver Wire."""
    from live_draft_roster_slots import (
        assign_roster_to_slot_instances,
        get_remaining_position_needs,
        get_required_position_counts,
    )

    df = roster_df if isinstance(roster_df, pd.DataFrame) else _roster_df_from_players(players)
    slot_config = dict(config or {})
    if not slot_config.get("slots") and isinstance(context, dict):
        try:
            from fantasy_league_context import resolve_context_draft_slot_config

            resolved = resolve_context_draft_slot_config(context)
            if isinstance(resolved, dict):
                slot_config = resolved
        except ImportError:
            pass
        if not slot_config.get("slots"):
            try:
                from fantasy_league_context import resolve_context_lineup_slots

                lineup_slots = resolve_context_lineup_slots(context) or []
                counts: dict[str, int] = {}
                for token in lineup_slots:
                    code = normalize_position_code(str(token))
                    if code == "BN":
                        continue
                    counts[code] = counts.get(code, 0) + 1
                if counts:
                    slot_config = {"slots": counts}
            except ImportError:
                pass

    required_counts = get_required_position_counts(slot_config)
    required_total = count_required_starting_positions(required_counts)
    assignment = assign_roster_to_slot_instances(df, slot_config)
    missing_codes = [
        normalize_position_code(g)
        for g in (get_remaining_position_needs(df, slot_config) or [])
        if normalize_position_code(g) != "BN"
    ]
    # Preserve order, unique for UI buttons.
    missing_unique: list[str] = list(dict.fromkeys(missing_codes))

    current_count = int(len(df)) if df is not None and not df.empty else 0
    capacity = max_roster_count
    if capacity is None and isinstance(context, dict):
        try:
            from fantasy_league_lineup_format import roster_capacity_from_format

            capacity = roster_capacity_from_format(context)
        except ImportError:
            capacity = None
    if capacity is None:
        configured_total = total_configured_roster_slots(required_counts)
        capacity = configured_total if configured_total > 0 else max(current_count, required_total)

    capacity = max(0, int(capacity))
    if current_count < capacity:
        tx_mode = "add_only"
    elif current_count == capacity:
        tx_mode = "add_drop"
    else:
        tx_mode = "cleanup_required"

    valid = required_total > 0 and not missing_unique and current_count <= capacity
    prompts = [
        {
            "position_code": code,
            "text": missing_position_message(code),
            "button_label": open_waiver_button_label(code),
            "waiver_label": position_display_names(code)["title"],
        }
        for code in missing_unique
    ]
    return {
        "required_positions": required_counts,
        "required_count": required_total,
        "filled_count": int(assignment.get("filled") or 0),
        "missing_positions": missing_unique,
        "player_eligibility_ok": True,
        "current_roster_count": current_count,
        "max_roster_count": capacity,
        "add_only_allowed": tx_mode == "add_only",
        "add_drop_required": tx_mode == "add_drop",
        "cleanup_required": tx_mode == "cleanup_required",
        "transaction_mode": tx_mode,
        "roster_valid": bool(valid),
        "assignment": assignment,
        "missing_prompts": prompts,
    }


def activate_waiver_position_correction(session: dict[str, Any], position_code: str) -> str:
    """Enter special Waiver Wire correction mode for one missing position."""
    code = normalize_position_code(position_code)
    names = position_display_names(code)
    session[WAIVER_CORRECTION_MODE_KEY] = True
    session[WAIVER_CORRECTION_POSITION_KEY] = code
    session[WAIVER_CORRECTION_LABEL_KEY] = names["title"]
    # Map to Waiver Wire filter tokens.
    if code == "DH":
        return "DH/UTIL"
    return code


def clear_waiver_position_correction(session: dict[str, Any]) -> None:
    session.pop(WAIVER_CORRECTION_MODE_KEY, None)
    session.pop(WAIVER_CORRECTION_POSITION_KEY, None)
    session.pop(WAIVER_CORRECTION_LABEL_KEY, None)


def is_waiver_position_correction_active(session: dict[str, Any] | None) -> bool:
    return bool((session or {}).get(WAIVER_CORRECTION_MODE_KEY))


def waiver_correction_banner(session: dict[str, Any] | None) -> str:
    if not is_waiver_position_correction_active(session):
        return ""
    code = str((session or {}).get(WAIVER_CORRECTION_POSITION_KEY) or "").strip()
    names = position_display_names(code)
    return (
        f"Position correction mode: filling missing {names['singular']}. "
        f"Only eligible {names['plural'].lower()} are prioritized."
    )


def validate_commissioner_lineup_slot_count(
    *,
    starter_count: int,
    drafted_roster_size: int,
) -> dict[str, Any]:
    """Simulator / uploaded — do not create more required starters than drafted roster size."""
    starters = max(0, int(starter_count or 0))
    drafted = max(0, int(drafted_roster_size or 0))
    if drafted <= 0:
        return {"ok": False, "error": "Could not detect drafted roster size.", "max_starters": 0}
    if starters <= 0:
        return {"ok": False, "error": "Choose at least one starting position.", "max_starters": drafted}
    if starters > drafted:
        return {
            "ok": False,
            "error": (
                f"Required positions ({starters}) cannot exceed drafted players per team ({drafted})."
            ),
            "max_starters": drafted,
        }
    return {"ok": True, "error": "", "max_starters": drafted, "bench_spots": drafted - starters}
