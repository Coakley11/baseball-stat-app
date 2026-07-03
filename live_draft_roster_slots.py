"""Canonical host-configured roster slots for Live Draft and post-draft analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Host slot order when expanding counts into separate slot instances.
_SLOT_EXPAND_ORDER: tuple[tuple[str, str], ...] = (
    ("C", "C"),
    ("1B", "1B"),
    ("2B", "2B"),
    ("3B", "3B"),
    ("SS", "SS"),
    ("OF", "OF"),
    ("DH", "UTIL"),
    ("P", "P"),
    ("BN", "BN"),
)

_POSITION_CODES = ("C", "1B", "2B", "3B", "SS", "OF", "DH", "P", "BN")


def _slots_dict(config: dict[str, Any] | None) -> dict[str, int]:
    cfg = dict(config or {})
    raw = dict(cfg.get("slots") or {})
    return {code: int(raw.get(code, 0) or 0) for code in _POSITION_CODES}


def get_required_position_counts(config: dict[str, Any] | None) -> dict[str, int]:
    """Per-position targets from host-created draft configuration."""
    return _slots_dict(config)


def get_active_position_codes(config: dict[str, Any] | None, *, include_bench: bool = False) -> set[str]:
    """Position codes with target > 0 (active in this draft)."""
    counts = get_required_position_counts(config)
    codes = {pos for pos, n in counts.items() if n > 0 and (include_bench or pos != "BN")}
    return codes


def get_active_draft_roster_slots(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Ordered slot instances — duplicate positions are separate entries (e.g. three OF slots)."""
    cfg = dict(config or {})
    stored = cfg.get("slot_instances")
    if isinstance(stored, list) and stored:
        out: list[dict[str, Any]] = []
        for i, slot in enumerate(stored):
            if not isinstance(slot, dict):
                continue
            pos = str(slot.get("position") or "").strip()
            if not pos:
                continue
            out.append(
                {
                    "position": pos,
                    "label": str(slot.get("label") or pos),
                    "slot_index": int(slot.get("slot_index", i)),
                }
            )
        if out:
            return out

    counts = _slots_dict(cfg)
    instances: list[dict[str, Any]] = []
    of_counter = 0
    for pos_key, display_base in _SLOT_EXPAND_ORDER:
        target = int(counts.get(pos_key, 0) or 0)
        for i in range(target):
            if pos_key == "OF" and target > 1:
                of_counter += 1
                label = f"OF {of_counter}"
            elif pos_key == "DH":
                label = "UTIL" if target == 1 else f"UTIL {i + 1}"
            elif target > 1:
                label = f"{display_base} {i + 1}"
            else:
                label = display_base
            instances.append(
                {
                    "position": pos_key,
                    "label": label,
                    "slot_index": len(instances),
                }
            )
    return instances


def freeze_slot_instances_on_config(config: dict[str, Any]) -> dict[str, Any]:
    """Persist ordered slot instances on room config at draft start."""
    cfg = dict(config or {})
    cfg["slot_instances"] = get_active_draft_roster_slots(cfg)
    return cfg


def get_filled_position_counts(roster_df: pd.DataFrame | None) -> dict[str, int]:
    """How many drafted players per Primary Position on one team."""
    if roster_df is None or roster_df.empty or "Primary Position" not in roster_df.columns:
        return {}
    return {
        str(k): int(v)
        for k, v in roster_df["Primary Position"].fillna("DH").astype(str).value_counts().items()
    }


def get_remaining_position_needs(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any] | None,
) -> list[str]:
    """Open slot position codes — duplicates preserved (e.g. three OF needs → ['OF','OF','OF'])."""
    slots = get_active_draft_roster_slots(config)
    if not slots:
        return []
    counts = get_filled_position_counts(roster_df)
    remaining = dict(counts)
    needs: list[str] = []
    for slot in slots:
        pos = str(slot.get("position") or "")
        if pos == "BN":
            left = max(0, int(remaining.get(pos, 0) or 0))
            if left > 0:
                remaining[pos] = left - 1
            else:
                needs.append(pos)
            continue
        left = int(remaining.get(pos, 0) or 0)
        if left > 0:
            remaining[pos] = left - 1
        else:
            needs.append(pos)
    return needs


def get_league_remaining_demand(room: dict[str, Any] | None, config: dict[str, Any] | None) -> dict[str, int]:
    """League-wide open roster slots per position code."""
    cfg = dict(config or {})
    if room and not cfg.get("slots"):
        cfg = dict(room.get("config") or {})
    counts = get_required_position_counts(cfg)
    demand = {pos: 0 for pos in counts}
    teams = list((room or {}).get("teams") or [])
    if not teams:
        teams = [""]
    for team in teams:
        roster_df = pd.DataFrame()
        if room and team:
            roster_df = pd.DataFrame((room.get("rosters") or {}).get(str(team), []) or [])
        needs = get_remaining_position_needs(roster_df, cfg)
        for pos in needs:
            if pos in demand:
                demand[pos] = int(demand.get(pos, 0) or 0) + 1
    return demand


def live_draft_target_counts(config: dict[str, Any] | None) -> dict[str, int]:
    """Backward-compatible alias used by scoring and tracker modules."""
    return get_required_position_counts(config)


def _config_with_slots_from_mapping(data: dict[str, Any] | None) -> dict[str, Any]:
    """Extract host slot config from a room dict or persisted blob."""
    if not isinstance(data, dict):
        return {}
    cfg = dict(data.get("config") or {})
    if cfg.get("slots"):
        if data.get("slot_instances") and not cfg.get("slot_instances"):
            cfg = {**cfg, "slot_instances": data["slot_instances"]}
        return cfg
    return {}


def resolve_draft_slot_config_from_session(session: dict[str, Any] | None) -> dict[str, Any]:
    """Host slot config from live draft room, canonical blob, or draft-lab handoff."""
    session = session or {}
    try:
        from live_draft_state import LIVE_DRAFT_PAGE_BLOCK, LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state

        prepare_live_draft_state(session)
    except ImportError:
        LIVE_DRAFT_PAGE_BLOCK = "Live Draft Room"
        LIVE_DRAFT_ROOM_KEY = "live_draft_room"

    room = session.get("live_draft_room")
    cfg = _config_with_slots_from_mapping(room if isinstance(room, dict) else None)
    if cfg.get("slots"):
        return cfg

    blob = session.get("live_draft_state")
    cfg = _config_with_slots_from_mapping(blob if isinstance(blob, dict) else None)
    if cfg.get("slots"):
        return cfg

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK) or pf.get("live_draft")
        if isinstance(block, dict):
            legacy = block.get(LIVE_DRAFT_ROOM_KEY) or block.get("live_draft_room")
            cfg = _config_with_slots_from_mapping(legacy if isinstance(legacy, dict) else None)
            if cfg.get("slots"):
                return cfg

    lab = session.get("draft_lab_results")
    if isinstance(lab, dict):
        handoff = lab.get("handoff")
        if isinstance(handoff, dict) and handoff.get("slots"):
            out = {"slots": dict(handoff["slots"])}
            if handoff.get("slot_instances"):
                out["slot_instances"] = handoff["slot_instances"]
            return out
    return {}


def position_codes_in_slot_order(config: dict[str, Any] | None) -> list[str]:
    """Active position codes in host slot display order (excludes bench)."""
    active = get_active_position_codes(config, include_bench=False)
    return [code for code, _ in _SLOT_EXPAND_ORDER if code in active]


def format_open_position_needs(gaps: list[str] | None) -> str:
    """Deduped open-need label for summary banners."""
    if not gaps:
        return "balanced roster"
    seen: list[str] = []
    for g in gaps:
        s = str(g or "").strip()
        if s and s not in seen:
            seen.append(s)
    return ", ".join(seen) if seen else "balanced roster"
