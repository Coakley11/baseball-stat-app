"""Weekly lineup management for the active fantasy team."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fantasy_league_context import (
    get_active_league_context,
    resolve_context_lineup_slots,
    upsert_league_context,
)

WORKFLOW_KEY_WEEKLY_LINEUPS = "weekly_lineups"
WORKFLOW_KEY_WEEKLY_DRAFTS = "weekly_lineup_drafts"
LINEUP_STATUS_DRAFT = "draft"
LINEUP_STATUS_LOCKED = "locked"
DEFAULT_WEEKLY_SLOTS: tuple[str, ...] = ("C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL")
ROTO_STARTER_CATEGORIES: tuple[str, ...] = ("R", "HR", "RBI", "SB", "AVG")
MAX_FANTASY_WEEKS = 26
SLOT_DISPLAY_NAMES: dict[str, str] = {
    "C": "Catcher",
    "1B": "First Base",
    "2B": "Second Base",
    "3B": "Third Base",
    "SS": "Shortstop",
    "OF": "Outfield",
    "UTIL": "Utility",
    "DH": "Designated Hitter",
}
SLOT_LABEL_TO_WAIVER_FILTER: dict[str, str] = {
    "Catcher": "C",
    "First Base": "1B",
    "Second Base": "2B",
    "Third Base": "3B",
    "Shortstop": "SS",
    "Outfield": "OF",
    "Utility": "DH/UTIL",
    "Designated Hitter": "DH/UTIL",
}


def waiver_filter_for_slot_label(slot_label: str) -> str:
    """Map lineup slot display label to Waiver Wire position filter token."""
    return SLOT_LABEL_TO_WAIVER_FILTER.get(str(slot_label or "").strip(), "")
_STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "R": ("R",),
    "HR": ("HR",),
    "RBI": ("RBI",),
    "SB": ("SB",),
    "AVG": ("BA", "AVG"),
    "H": ("H",),
    "AB": ("AB",),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _player_name_col(df: pd.DataFrame) -> str:
    for col in ("Player", "fullName", "player_name"):
        if col in df.columns:
            return col
    return "Player"


def _split_positions(raw: Any) -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    text = str(raw).strip().upper()
    if not text:
        return []
    parts = re.split(r"[,/|]+", text)
    tokens: list[str] = []
    for part in parts:
        token = part.strip()
        if not token:
            continue
        if token in ("LF", "CF", "RF"):
            token = "OF"
        if token == "DH":
            token = "DH"
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def position_tokens_from_row(row: pd.Series | dict[str, Any]) -> list[str]:
    """Normalized eligibility tokens for a roster row."""
    if isinstance(row, pd.Series):
        getter = row.get
    else:
        getter = row.get  # type: ignore[assignment]
    tokens: list[str] = []
    if isinstance(row, pd.Series) and "_pos_tokens" in row.index:
        raw_tokens = row.get("_pos_tokens")
        if isinstance(raw_tokens, list):
            tokens.extend(str(t).strip().upper() for t in raw_tokens if str(t).strip())
    for col in ("Primary Position", "Position", "Eligibility", "Positions"):
        tokens.extend(_split_positions(getter(col)))
    tokens = list(dict.fromkeys(t for t in tokens if t))
    return tokens or ["DH"]


def player_eligible_for_slot(pos_tokens: list[str], slot: str) -> bool:
    """True when hitter eligibility covers the lineup slot."""
    slot = str(slot or "").strip().upper()
    if slot in ("UTIL", "DH/UTIL", "DH"):
        return not any(p in ("P", "SP", "RP") for p in pos_tokens)
    if slot == "OF":
        return any(p == "OF" for p in pos_tokens)
    if slot in ("C", "1B", "2B", "3B", "SS"):
        if pos_tokens == ["DH"] or (len(pos_tokens) == 1 and pos_tokens[0] == "DH"):
            return False
        if slot in pos_tokens:
            return True
        if slot == "1B" and "3B" in pos_tokens:
            return True
        if slot == "3B" and "1B" in pos_tokens:
            return True
        if slot == "2B" and "SS" in pos_tokens:
            return True
        if slot == "SS" and "2B" in pos_tokens:
            return True
        return False
    return False


def slot_display_name(slot: str) -> str:
    base = str(slot or "").strip().upper().split("_", 1)[0]
    return SLOT_DISPLAY_NAMES.get(base, base)


def resolve_weekly_lineup_slots(context: dict[str, Any] | None) -> list[str]:
    """Starter slots from league configuration only — no implicit default lineup."""
    context_slots = resolve_context_lineup_slots(context)
    if context_slots:
        normalized: list[str] = []
        for slot in context_slots:
            token = str(slot or "").strip().upper()
            if token in ("LF", "CF", "RF"):
                token = "OF"
            if token == "DH":
                token = "UTIL"
            if token in ("BN", "P", "SP", "RP"):
                continue
            normalized.append(token)
        if normalized:
            return normalized
    return []


def week_label(week: int) -> str:
    return f"Week {int(week)}"


def list_week_options(*, max_week: int = MAX_FANTASY_WEEKS) -> list[int]:
    return list(range(1, max(1, int(max_week)) + 1))


def _weekly_lineups_store(context: dict[str, Any]) -> dict[str, Any]:
    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    raw = workflow.get(WORKFLOW_KEY_WEEKLY_LINEUPS)
    if not isinstance(raw, dict):
        raw = {}
        workflow[WORKFLOW_KEY_WEEKLY_LINEUPS] = raw
    return raw


def weekly_lineup_key(week: int) -> str:
    return f"week_{int(week)}"


def team_week_lineup_key(team: str, week: int) -> str:
    return f"{str(team or '').strip()}|week_{int(week)}"


def _weekly_lineup_drafts_store(context: dict[str, Any]) -> dict[str, Any]:
    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    raw = workflow.get(WORKFLOW_KEY_WEEKLY_DRAFTS)
    if not isinstance(raw, dict):
        raw = {}
        workflow[WORKFLOW_KEY_WEEKLY_DRAFTS] = raw
    return raw


def _lookup_team_week_record(store: dict[str, Any], team: str, week: int) -> dict[str, Any] | None:
    key = team_week_lineup_key(team, week)
    payload = store.get(key)
    if isinstance(payload, dict):
        return copy.deepcopy(payload)
    legacy = store.get(weekly_lineup_key(week))
    if isinstance(legacy, dict):
        saved_team = str(legacy.get("my_team_name") or "").strip()
        if not saved_team or saved_team == str(team or "").strip():
            return copy.deepcopy(legacy)
    return None


def _lineup_storage_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Durable league context for weekly lineup drafts and locks."""
    ctx = get_active_league_context(session, respect_source_priority=False)
    if ctx:
        return ctx
    return get_active_league_context(session)


def get_weekly_lineup_state(
    context: dict[str, Any] | None,
    week: int,
    *,
    team: str = "",
    session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return locked lineup, else in-progress draft, for a team/week."""
    if session is not None:
        stored = _lineup_storage_context(session)
        if stored:
            context = stored
    if not context:
        return None
    team_name = str(team or context.get("my_team_name") or "").strip()
    locked = _lookup_team_week_record(_weekly_lineups_store(context), team_name, week)
    if isinstance(locked, dict) and str(locked.get("status") or "") == LINEUP_STATUS_LOCKED:
        return locked
    draft = _lookup_team_week_record(_weekly_lineup_drafts_store(context), team_name, week)
    if isinstance(draft, dict):
        return draft
    if isinstance(locked, dict):
        return locked
    return None


def get_saved_weekly_lineup(
    context: dict[str, Any] | None,
    week: int,
    *,
    team: str = "",
    session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return persisted lineup record (locked preferred, else draft)."""
    return get_weekly_lineup_state(context, week, team=team, session=session)


def is_lineup_locked(
    context: dict[str, Any] | None,
    week: int,
    *,
    team: str = "",
    session: dict[str, Any] | None = None,
) -> bool:
    record = get_weekly_lineup_state(context, week, team=team, session=session)
    return isinstance(record, dict) and str(record.get("status") or "") == LINEUP_STATUS_LOCKED


def persist_weekly_lineup_draft(
    session: dict[str, Any],
    *,
    week: int,
    slots: list[str],
    assignments: dict[str, str],
    my_team: str,
    roster_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Auto-save in-progress lineup draft after every valid board change."""
    del roster_df
    result: dict[str, Any] = {"ok": False, "errors": []}
    context = _lineup_storage_context(session)
    if not context:
        result["errors"].append("No active league context.")
        return result
    team = str(my_team or context.get("my_team_name") or "").strip()
    if is_lineup_locked(context, week, team=team, session=session):
        result["errors"].append("Lineup is locked for this week.")
        return result

    slot_map = assignments_to_slot_player_map(slots, assignments)
    drafts = _weekly_lineup_drafts_store(context)
    key = team_week_lineup_key(team, week)
    existing = drafts.get(key) if isinstance(drafts, dict) else None
    if isinstance(existing, dict) and str(existing.get("status") or "") == LINEUP_STATUS_DRAFT:
        prior = existing.get("assignments") if isinstance(existing.get("assignments"), dict) else {}
        if dict(prior) == dict(slot_map):
            result["ok"] = True
            result["lineup"] = existing
            result["skipped"] = True
            return result

    payload = {
        "week": int(week),
        "week_label": week_label(week),
        "my_team_name": team,
        "slots": slots,
        "assignments": slot_map,
        "status": LINEUP_STATUS_DRAFT,
        "updated_at": _utc_now_iso(),
    }
    drafts = _weekly_lineup_drafts_store(context)
    drafts[team_week_lineup_key(team, week)] = payload
    upsert_league_context(session, context)
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="weekly_lineup_draft")
    except Exception:
        pass
    result["ok"] = True
    result["lineup"] = payload
    return result


def roster_player_names(roster_df: pd.DataFrame) -> list[str]:
    if roster_df is None or roster_df.empty:
        return []
    col = _player_name_col(roster_df)
    return sorted(roster_df[col].dropna().astype(str).str.strip().unique().tolist())


def eligible_players_for_slot(roster_df: pd.DataFrame, slot: str) -> list[str]:
    if roster_df is None or roster_df.empty:
        return []
    col = _player_name_col(roster_df)
    names: list[str] = []
    for _, row in roster_df.iterrows():
        name = str(row.get(col) or "").strip()
        if not name:
            continue
        if player_eligible_for_slot(position_tokens_from_row(row), slot):
            names.append(name)
    return sorted(set(names))


def slot_assignments_from_names(
    slots: list[str],
    slot_to_player: dict[str, str],
) -> dict[str, str]:
    """Map slot index keys (C, OF_1, etc.) to player names."""
    out: dict[str, str] = {}
    slot_counts: dict[str, int] = {}
    for slot in slots:
        base = str(slot or "").strip().upper()
        count = slot_counts.get(base, 0) + 1
        slot_counts[base] = count
        key = base if count == 1 else f"{base}_{count}"
        player = str(slot_to_player.get(key) or slot_to_player.get(base) or "").strip()
        if player:
            out[key] = player
    return out


def assignments_to_slot_player_map(
    slots: list[str],
    assignments: dict[str, str],
) -> dict[str, str]:
    """Expand saved assignments back to widget keys."""
    out: dict[str, str] = {}
    slot_counts: dict[str, int] = {}
    for slot in slots:
        base = str(slot or "").strip().upper()
        count = slot_counts.get(base, 0) + 1
        slot_counts[base] = count
        key = base if count == 1 else f"{base}_{count}"
        if key in assignments:
            out[key] = str(assignments.get(key) or "").strip()
        elif count == 1 and base in assignments:
            out[key] = str(assignments.get(base) or "").strip()
        else:
            out[key] = ""
    return out


def validate_weekly_lineup(
    slots: list[str],
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
) -> dict[str, Any]:
    """Validate required slots, duplicate players, and eligibility."""
    result: dict[str, Any] = {
        "ok": True,
        "missing_slots": [],
        "ineligible_slots": [],
        "duplicate_players": [],
        "messages": [],
    }
    if roster_df is None or roster_df.empty:
        result["ok"] = False
        result["messages"].append("Load roster stats before saving a weekly lineup.")
        return result

    name_col = _player_name_col(roster_df)
    roster_lookup = {
        str(row[name_col]).strip(): row for _, row in roster_df.iterrows() if str(row.get(name_col) or "").strip()
    }
    slot_map = assignments_to_slot_player_map(slots, assignments)
    used_players: dict[str, str] = {}

    for slot_key, player_name in slot_map.items():
        base_slot = slot_key.split("_", 1)[0]
        slot_label = slot_display_name(base_slot)
        if not player_name:
            result["missing_slots"].append(base_slot)
            result["messages"].append(f"{slot_label} is empty.")
            result["ok"] = False
            continue
        if player_name in used_players:
            result["duplicate_players"].append(player_name)
            result["messages"].append(f"{player_name} is assigned twice.")
            result["ok"] = False
        used_players[player_name] = slot_key
        row = roster_lookup.get(player_name)
        if row is None:
            result["messages"].append(f"{player_name} is not on your active roster.")
            result["ok"] = False
            continue
        if not player_eligible_for_slot(position_tokens_from_row(row), base_slot):
            result["ineligible_slots"].append({"slot": base_slot, "player": player_name})
            result["messages"].append(f"{player_name} is not eligible for {slot_label}.")
            result["ok"] = False

    for slot in slots:
        base = str(slot or "").strip().upper()
        if base not in {s.split("_", 1)[0] for s in slot_map}:
            continue
        if not eligible_players_for_slot(roster_df, base):
            result["messages"].append(
                f"Need eligible {slot_display_name(base)}. Open Waiver Wire to add one."
            )
    return result


def build_lineup_summary(
    slots: list[str],
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
) -> dict[str, Any]:
    """Starting lineup, bench, and open slot labels for the active team."""
    slot_map = assignments_to_slot_player_map(slots, assignments)
    slot_keys = []
    counts: dict[str, int] = {}
    for slot in slots:
        base = str(slot or "").strip().upper()
        count = counts.get(base, 0) + 1
        counts[base] = count
        key = base if count == 1 else f"{base}_{count}"
        slot_keys.append((key, base, slot_display_name(base) if count == 1 else f"{slot_display_name(base)} ({count})"))

    starters: list[str] = []
    open_slots: list[str] = []
    for key, base, label in slot_keys:
        player = str(slot_map.get(key) or "").strip()
        if player:
            starters.append(f"{label}: {player}")
        else:
            open_slots.append(label)

    bench = not_starting_players(roster_df, slot_map)
    return {
        "starters": starters,
        "bench": bench,
        "open_slots": open_slots,
    }


def not_starting_players(
    roster_df: pd.DataFrame,
    assignments: dict[str, str],
) -> list[str]:
    all_names = roster_player_names(roster_df)
    starter_names = {str(v).strip() for v in assignments.values() if str(v).strip()}
    return [name for name in all_names if name not in starter_names]


def _read_numeric(row: pd.Series, category: str) -> float:
    for col in _STAT_ALIASES.get(category, (category,)):
        if col not in row.index:
            continue
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def compute_weekly_starter_totals(
    roster_df: pd.DataFrame,
    assignments: dict[str, str],
    *,
    categories: tuple[str, ...] = ROTO_STARTER_CATEGORIES,
) -> dict[str, Any]:
    """Aggregate current-season counting stats for assigned starters."""
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row for _, row in roster_df.iterrows() if str(row.get(name_col) or "").strip()
    }
    starter_names = [str(v).strip() for v in assignments.values() if str(v).strip()]
    rows: list[dict[str, Any]] = []
    totals: dict[str, float] = {cat: 0.0 for cat in categories if cat != "AVG"}
    hits = 0.0
    ab = 0.0
    for name in starter_names:
        row = lookup.get(name)
        if row is None:
            continue
        entry: dict[str, Any] = {"Player": name}
        for cat in categories:
            if cat == "AVG":
                hits += _read_numeric(row, "H")
                ab += _read_numeric(row, "AB")
                continue
            val = _read_numeric(row, cat)
            entry[cat] = val
            totals[cat] = totals.get(cat, 0.0) + val
        rows.append(entry)
    if "AVG" in categories:
        totals["AVG"] = (hits / ab) if ab > 0 else 0.0
    return {"starters": rows, "totals": totals, "categories": list(categories)}


def _player_id_from_row(row: pd.Series | dict[str, Any]) -> str:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": ""
    for key in ("player_id", "playerID", "playerId", "mlbam_id", "ID"):
        val = str(getter(key) or "").strip()
        if val:
            return val
    return ""


def save_weekly_lineup(
    session: dict[str, Any],
    *,
    week: int,
    slots: list[str],
    assignments: dict[str, str],
    my_team: str,
    roster_df: pd.DataFrame,
) -> dict[str, Any]:
    """Persist weekly lineup to active league context and linked draft archive."""
    result: dict[str, Any] = {"ok": False, "errors": []}
    context = _lineup_storage_context(session)
    if not context:
        result["errors"].append("No active league context.")
        return result

    validation = validate_weekly_lineup(slots, assignments, roster_df)
    if not validation.get("ok"):
        result["errors"].extend(list(validation.get("messages") or []))
        return result

    slot_map = assignments_to_slot_player_map(slots, assignments)
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row for _, row in roster_df.iterrows() if str(row.get(name_col) or "").strip()
    }
    assignments_by_id: dict[str, str] = {}
    for slot_key, player_name in slot_map.items():
        row = lookup.get(player_name)
        if row is not None:
            pid = _player_id_from_row(row)
            if pid:
                assignments_by_id[slot_key] = pid

    team_name = str(my_team or "").strip()
    payload = {
        "week": int(week),
        "week_label": week_label(week),
        "my_team_name": team_name,
        "slots": slots,
        "assignments": slot_map,
        "assignments_by_id": assignments_by_id,
        "not_starting": not_starting_players(roster_df, slot_map),
        "saved_at": _utc_now_iso(),
        "locked_at": _utc_now_iso(),
        "status": LINEUP_STATUS_LOCKED,
    }

    try:
        from fantasy_weekly_hitter_scoring import (
            create_weekly_baseline_on_lock,
            resolve_hitter_scoring_profile,
        )

        profile = resolve_hitter_scoring_profile(context, session=session)
        if profile.blocked:
            result["errors"].append(profile.block_message or "Weekly scoring is not configured for this league.")
            return result
        baseline_result = create_weekly_baseline_on_lock(
            context,
            week=int(week),
            team=team_name,
            assignments=slot_map,
            roster_df=roster_df,
            profile=profile,
            session=session,
        )
        if not baseline_result.get("ok"):
            result["errors"].extend(list(baseline_result.get("errors") or []))
            return result
        payload["weekly_scoring_record_key"] = (
            (baseline_result.get("record") or {}).get("record_key") or ""
        )
        payload["stats_snapshot"] = compute_weekly_starter_totals(
            roster_df,
            slot_map,
            categories=tuple(profile.display_categories),
        )
        from fantasy_weekly_hitter_scoring import refresh_weekly_scoring

        refresh_weekly_scoring(
            context,
            week=int(week),
            team=team_name,
            roster_df=roster_df,
            profile=profile,
            session=session,
        )
    except ImportError:
        payload["stats_snapshot"] = compute_weekly_starter_totals(roster_df, slot_map)
    store = _weekly_lineups_store(context)
    store[team_week_lineup_key(team_name, week)] = payload
    drafts = _weekly_lineup_drafts_store(context)
    drafts.pop(team_week_lineup_key(team_name, week), None)
    context = upsert_league_context(session, context)

    try:
        from fantasy_lineup_perf import invalidate_lineup_page_caches

        invalidate_lineup_page_caches(session)
    except ImportError:
        pass

    draft_id = str(context.get("source_draft_id") or "").strip()
    if not draft_id:
        try:
            from draft_archive_state import get_active_draft_archive

            active = get_active_draft_archive(session)
            if isinstance(active, dict):
                draft_id = str(active.get("draft_id") or "").strip()
        except ImportError:
            pass
    if draft_id:
        try:
            from draft_archive_state import get_draft_archive, _archive_list, _set_archive_list

            entry = get_draft_archive(session, draft_id)
            if entry:
                entry = copy.deepcopy(entry)
                entry["weekly_lineups"] = copy.deepcopy(_weekly_lineups_store(context))
                entries = _archive_list(session)
                for i, existing in enumerate(entries):
                    if str(existing.get("draft_id") or "") == draft_id:
                        entries[i] = entry
                        break
                _set_archive_list(session, entries)
        except ImportError:
            pass

    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="weekly_lineup_save")
    except Exception:
        pass

    result["ok"] = True
    result["lineup"] = payload
    return result
