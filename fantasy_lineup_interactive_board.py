"""Interactive circular face-to-circle Fantasy Lineup board."""

from __future__ import annotations

import html as html_lib
import json
from typing import Any

import pandas as pd

from fantasy_lineup_ui import (
    build_slot_key_labels,
    initials_from_name,
    photo_html_for_player,
)
from fantasy_weekly_lineup import (
    _player_name_col,
    eligible_players_for_slot,
    not_starting_players,
    player_eligible_for_slot,
    position_tokens_from_row,
    roster_player_names,
)

BENCH_ZONE = "__bench__"
FACE_SIZE = 72


def apply_board_drop(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
    *,
    player: str,
    target: str,
    roster_df: pd.DataFrame,
) -> dict[str, str]:
    """Apply one face-to-circle drop onto canonical assignments."""
    player = str(player or "").strip()
    target = str(target or "").strip()
    valid_names = set(roster_player_names(roster_df))
    if not player or player not in valid_names:
        return dict(assignments)

    new = {key: str((assignments or {}).get(key) or "").strip() for key, _ in slot_keys}
    origin_key = next((key for key, _ in slot_keys if new.get(key) == player), "")

    if target == BENCH_ZONE:
        if origin_key:
            new[origin_key] = ""
        return new

    if target not in new:
        return dict(assignments)

    base_slot = target.split("_", 1)[0]
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(name_col) or "").strip()
    }
    row = lookup.get(player)
    if row is None or not player_eligible_for_slot(position_tokens_from_row(row), base_slot):
        return dict(assignments)

    displaced = new.get(target, "").strip()
    new[target] = player
    if origin_key and origin_key != target:
        new[origin_key] = ""
    # Displaced starter returns to bench (slot cleared).
    return new


def _normalize_slot_assignments(
    raw: dict[str, Any],
    slot_keys: list[tuple[str, str]],
) -> dict[str, str]:
    return {key: str((raw or {}).get(key) or "").strip() for key, _ in slot_keys}


def assignments_are_valid(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
    roster_df: pd.DataFrame,
) -> bool:
    """True when every filled slot has a rostered, eligible, non-duplicated player."""
    valid_names = set(roster_player_names(roster_df))
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(name_col) or "").strip()
    }
    used: set[str] = set()
    for key, _label in slot_keys:
        player = str((assignments or {}).get(key) or "").strip()
        if not player:
            continue
        if player in used or player not in valid_names:
            return False
        row = lookup.get(player)
        if row is None:
            return False
        base_slot = key.split("_", 1)[0]
        if not player_eligible_for_slot(position_tokens_from_row(row), base_slot):
            return False
        used.add(player)
    return True


def apply_drop_event(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
    drop_event: dict[str, Any],
    *,
    roster_df: pd.DataFrame,
) -> dict[str, str] | None:
    """Apply a component drop event; return None when invalid or unchanged."""
    if not isinstance(drop_event, dict):
        return None
    player = str(drop_event.get("player") or "").strip()
    target = str(drop_event.get("target") or "").strip()
    raw_assignments = drop_event.get("assignments")
    if isinstance(raw_assignments, dict):
        candidate = _normalize_slot_assignments(raw_assignments, slot_keys)
        if assignments_are_valid(candidate, slot_keys, roster_df):
            return candidate
    if not player or not target:
        return None
    result = apply_board_drop(
        assignments,
        slot_keys,
        player=player,
        target=target,
        roster_df=roster_df,
    )
    if assignments_are_valid(result, slot_keys, roster_df) or target == BENCH_ZONE:
        return result
    return None


def _face_inner_html(*, player_name: str, row: pd.Series | None, size: int) -> str:
    safe = html_lib.escape(player_name)
    photo_html, has_photo = photo_html_for_player(player_name=player_name, row=row, size=size)
    if has_photo:
        return photo_html.replace('class="fl-player-photo"', 'class="fl-face-img"')
    initials = html_lib.escape(initials_from_name(player_name))
    return (
        f'<div class="fl-face-fallback" aria-label="{safe}">'
        f'<span class="fl-face-fallback-icon" aria-hidden="true">⚾</span>'
        f'<span class="fl-face-initials">{initials}</span></div>'
    )


def build_interactive_board_payload(
    slot_labels: list,
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
    *,
    editable: bool = True,
) -> dict[str, Any]:
    """JSON-serializable payload for the interactive circular board."""
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(name_col) or "").strip()
    }
    slot_keys = [(label.key, label.label) for label in slot_labels]
    slot_map = {label.key: str(assignments.get(label.key) or "").strip() for label in slot_labels}

    slots: list[dict[str, Any]] = []
    for label in slot_labels:
        player = slot_map.get(label.key) or ""
        eligible = eligible_players_for_slot(roster_df, label.base_slot)
        slots.append(
            {
                "key": label.key,
                "label": label.label,
                "badge": label.badge,
                "base_slot": label.base_slot,
                "player": player or None,
                "eligible": eligible,
            }
        )

    bench_names = not_starting_players(roster_df, slot_map)
    bench: list[dict[str, Any]] = []
    for name in bench_names:
        row = lookup.get(name)
        bench.append(
            {
                "name": name,
                "positions": "/".join(position_tokens_from_row(row)[:4]) if row is not None else "",
            }
        )

    faces: dict[str, str] = {}
    for name in roster_player_names(roster_df):
        row = lookup.get(name)
        faces[name] = _face_inner_html(player_name=name, row=row, size=FACE_SIZE)

    return {
        "slots": slots,
        "bench": bench,
        "roster": roster_player_names(roster_df),
        "faces": faces,
        "assignments": slot_map,
        "slot_keys": [key for key, _ in slot_keys],
        "editable": bool(editable),
    }


def _board_height(payload: dict[str, Any]) -> int:
    """Tight iframe height from slot count and current bench size."""
    slots = payload.get("slots") or []
    roster = payload.get("roster") or []
    slot_count = len(slots)
    assigned = sum(1 for slot in slots if slot.get("player"))
    bench_count = max(0, len(roster) - assigned)

    slot_cols = 4
    slot_rows = max(1, (slot_count + slot_cols - 1) // slot_cols)
    bench_cols = 6
    bench_rows = max(1, (bench_count + bench_cols - 1) // bench_cols) if bench_count else 0

    header = 52
    slot_block = 20 + slot_rows * 112
    bench_block = 18 + (bench_rows * 92 if bench_count else 36)
    return header + slot_block + bench_block + 4


def render_interactive_lineup_board(
    st: Any,
    *,
    payload: dict[str, Any],
    component_key: str,
) -> Any:
    """Render the editable circular board; returns drop payload from prior interaction."""
    dev_mode = False
    try:
        from suite_workspace import developer_ui_visible_from_session

        dev_mode = bool(developer_ui_visible_from_session(st.session_state))
    except Exception:
        pass

    try:
        from lineup_board_component import (
            component_frontend_ready,
            get_component_frontend_dir,
            lineup_board_component,
        )
    except ImportError as exc:
        st.error("Lineup board couldn't load. Refresh the page.")
        if dev_mode:
            st.caption(f"Component import failed: {exc}")
        return None

    if not component_frontend_ready():
        st.error("Lineup board couldn't load. Refresh the page.")
        if dev_mode:
            st.caption(f"Component frontend path: `{get_component_frontend_dir()}`")
        return None

    if not (payload.get("slots") or []):
        st.warning("No lineup positions are configured for this league.")
        return None

    try:
        return lineup_board_component(payload=payload, key=str(component_key or "lineup_board"))
    except Exception as exc:
        st.error("Lineup board couldn't load. Refresh the page.")
        if dev_mode:
            st.caption(f"Component path: `{get_component_frontend_dir()}`")
            st.caption(f"Component error: {exc}")
        return None


def parse_board_drop_result(result: Any) -> dict[str, Any] | None:
    """Parse component return value from a face drop."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, str) and result.strip():
        try:
            parsed = json.loads(result)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None
