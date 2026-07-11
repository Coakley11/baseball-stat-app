"""Drag-and-drop weekly lineup helpers (Phase 2)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from fantasy_weekly_lineup import (
    _player_name_col,
    assignments_to_slot_player_map,
    not_starting_players,
    player_eligible_for_slot,
    position_tokens_from_row,
    roster_player_names,
    slot_display_name,
)

DND_SLOT_PREFIX = "__slot__:"
DND_BENCH_PREFIX = "__bench__"
EMPTY_SLOT_PLACEHOLDER = "— empty —"

WEEKLY_LINEUP_EDITOR_MODES: tuple[str, ...] = ("Drag & Drop", "Classic Dropdowns")
DEFAULT_WEEKLY_LINEUP_EDITOR_MODE = "Drag & Drop"


def slot_container_header(slot_key: str, label: str) -> str:
    """Machine-readable header shown in sortable container title."""
    return f"{label} [{DND_SLOT_PREFIX}{slot_key}]"


def bench_container_header() -> str:
    return f"Bench / Available [{DND_BENCH_PREFIX}]"


def parse_container_slot_key(header: str) -> str | None:
    text = str(header or "")
    match = re.search(rf"\[{re.escape(DND_SLOT_PREFIX)}([^\]]+)\]", text)
    return str(match.group(1)).strip() if match else None


def is_bench_container_header(header: str) -> bool:
    return DND_BENCH_PREFIX in str(header or "")


def player_id_from_row(row: pd.Series | dict[str, Any]) -> str:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": ""
    for key in ("player_id", "playerID", "playerId", "mlbam_id", "ID"):
        val = str(getter(key) or "").strip()
        if val:
            return val
    return ""


def player_card_caption(
    row: pd.Series | dict[str, Any],
    *,
    recommendation: str = "",
) -> str:
    """Compact card subtitle for bench/lineup display."""
    tokens = position_tokens_from_row(row)
    pos = "/".join(tokens[:4]) if tokens else "—"
    parts = [f"**{pos}**"]
    getter = row.get if hasattr(row, "get") else lambda _k, _d=None: _d
    stat_bits: list[str] = []
    for col, label in (("HR", "HR"), ("RBI", "RBI"), ("SB", "SB"), ("OPS", "OPS"), ("BA", "AVG")):
        val = getter(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        try:
            if col in ("OPS", "BA"):
                stat_bits.append(f"{label} {float(val):.3f}")
            else:
                stat_bits.append(f"{label} {int(float(val))}")
        except (TypeError, ValueError):
            continue
    if stat_bits:
        parts.append(" · ".join(stat_bits[:4]))
    rec = str(recommendation or "").strip()
    if rec:
        parts.append(f"**{rec}**")
    return " · ".join(parts)


def recommendation_lookup(scored_roster: pd.DataFrame | None) -> dict[str, str]:
    if scored_roster is None or scored_roster.empty or "Player" not in scored_roster.columns:
        return {}
    out: dict[str, str] = {}
    rec_col = "Start/Sit Recommendation" if "Start/Sit Recommendation" in scored_roster.columns else ""
    for _, row in scored_roster.iterrows():
        name = str(row.get("Player") or "").strip()
        if not name:
            continue
        out[name] = str(row.get(rec_col) or "").strip() if rec_col else ""
    return out


def build_sortable_containers(
    slot_keys: list[tuple[str, str]],
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
) -> list[dict[str, list[str]]]:
    """Build streamlit-sortables multi-container payload."""
    slot_map = {key: str(assignments.get(key) or "").strip() for key, _ in slot_keys}
    bench = not_starting_players(roster_df, slot_map)

    containers: list[dict[str, list[str]]] = []
    for key, label in slot_keys:
        player = slot_map.get(key) or ""
        items = [player] if player else []
        containers.append({"header": slot_container_header(key, label), "items": items})

    containers.append({"header": bench_container_header(), "items": list(bench)})
    return containers


def assignments_from_sortable_containers(
    containers: list[dict[str, Any]],
    slot_keys: list[tuple[str, str]],
    roster_df: pd.DataFrame,
) -> dict[str, str]:
    """
    Parse sortable output into slot assignments.

    Rules:
    - At most one starter per slot (first item wins).
    - Each player appears in at most one slot; duplicates return to bench.
    - Unknown names are ignored.
    """
    valid_names = set(roster_player_names(roster_df))
    assignments: dict[str, str] = {key: "" for key, _ in slot_keys}
    seen: set[str] = set()
    overflow_to_bench: list[str] = []

    for container in containers or []:
        if not isinstance(container, dict):
            continue
        header = str(container.get("header") or "")
        raw_items = container.get("items") or []
        items = [
            str(item).strip()
            for item in raw_items
            if str(item).strip() and str(item).strip() != EMPTY_SLOT_PLACEHOLDER
        ]

        if is_bench_container_header(header):
            overflow_to_bench.extend(items)
            continue

        slot_key = parse_container_slot_key(header)
        if not slot_key or slot_key not in assignments:
            overflow_to_bench.extend(items)
            continue

        for item in items:
            if item not in valid_names:
                continue
            if item in seen:
                overflow_to_bench.append(item)
                continue
            if not assignments[slot_key]:
                assignments[slot_key] = item
                seen.add(item)
            else:
                overflow_to_bench.append(item)

    return assignments


def slot_validation_styles(
    slot_keys: list[tuple[str, str]],
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
) -> dict[str, str]:
    """Map slot_key -> css class suffix: valid | invalid | empty."""
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row for _, row in roster_df.iterrows() if str(row.get(name_col) or "").strip()
    }
    styles: dict[str, str] = {}
    for key, _label in slot_keys:
        player = str(assignments.get(key) or "").strip()
        base = key.split("_", 1)[0]
        if not player:
            styles[key] = "empty"
            continue
        row = lookup.get(player)
        if row is None or not player_eligible_for_slot(position_tokens_from_row(row), base):
            styles[key] = "invalid"
        else:
            styles[key] = "valid"
    return styles


def dnd_custom_style() -> str:
    return """
.sortable-component { font-size: 14px; }
.sortable-container {
    background-color: #f8fafc;
    border: 2px dashed #94a3b8;
    border-radius: 12px;
    margin-bottom: 10px;
    min-height: 84px;
}
.sortable-container-header {
    background: linear-gradient(180deg, #e2e8f0, #f1f5f9);
    font-weight: 800;
    font-size: 0.82rem;
    letter-spacing: 0.03em;
    color: #0b3d6e;
    padding: 8px 10px;
    border-radius: 10px 10px 0 0;
}
.sortable-container-body { padding: 8px; min-height: 52px; }
.sortable-item {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 10px 12px;
    margin: 5px 0;
    font-weight: 700;
    color: #0f172a;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}
.sortable-item:hover { border-color: #0b3d6e; }
@media (max-width: 768px) {
    .sortable-item { padding: 12px 14px; font-size: 15px; }
}
"""
