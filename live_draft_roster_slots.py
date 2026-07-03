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
