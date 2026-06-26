"""Canonical Draft Room Simulator state — JSON-safe persistence for draft_room_table."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from dataframe_utils import sanitize_for_json

DRAFT_ROOM_PAGE_BLOCK = "Draft Room Simulator"
DRAFT_ROOM_TABLE_KEY = "draft_room_table"
DRAFT_ROOM_EDITOR_KEY_PREFIX = "draft_room_board_editor"
DRAFT_ROOM_EDITOR_SEED_KEY = "draft_room_board_editor_seed"
DRAFT_ROOM_EDITOR_VERSION_KEY = "draft_room_board_editor_version"
DRAFT_ROOM_EDITOR_CACHE_KEY = "draft_room_board_editor_cache"
# Legacy name — do not assign to this key; widget key is versioned (Streamlit-owned).
DRAFT_ROOM_EDITOR_KEY = DRAFT_ROOM_EDITOR_KEY_PREFIX
DRAFT_ROOM_STATE_KEY = "draft_room_state"
DRAFT_ROOM_DIRTY_KEY = "draft_room_state_dirty"
DRAFT_ROOM_LOCAL_EDIT_TS_KEY = "draft_room_state_last_local_edit_ts"
SUITE_LOCAL_DIRTY_BASEBALL_KEY = "_suite_local_dirty::baseball"
DRAFT_ROOM_PERSIST_SCHEMA = 1

DRAFT_ROOM_SETTINGS_KEYS = (
    "room_your_team",
    "room_team_count",
    "room_rounds",
    "room_format",
    "room_window",
    "room_team_names",
    "fantasy_draft_projection_style",
)

# One canonical draft board: runtime draft_room_table + blob draft_room_state.
CANONICAL_DRAFT_META_KEY = "canonical_draft_meta"
ACTIVE_DRAFT_MODE_LIVE = "live_draft_room"
ACTIVE_DRAFT_MODE_MANUAL = "draft_room_simulator"
ACTIVE_DRAFT_SOURCE_LIVE = "live"
ACTIVE_DRAFT_SOURCE_SIMULATOR = "simulator"


def is_live_draft_runtime_active(session: dict[str, Any]) -> bool:
    """True only when a live draft is in progress or paused — not not_started/complete."""
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state

        prepare_live_draft_state(session)
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        return isinstance(room, dict) and str(room.get("status") or "") in ("in_progress", "paused")
    except Exception:
        return False


def should_resolve_live_draft_source(session: dict[str, Any]) -> bool:
    """True when draft buttons and validation should use live_draft_room progress."""
    if is_live_draft_runtime_active(session):
        return True
    try:
        from draft_room_context import is_multiplayer_draft_active
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, is_runtime_room

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if not is_runtime_room(room) or not list(room.get("pick_order") or []):
            return False
        if is_multiplayer_draft_active(session):
            return True
        if str(room.get("status") or "") == "not_started" and not open_pick_row_options(
            get_canonical_draft_board(session)
        ):
            return True
    except Exception:
        return False
    return False


def resolve_active_draft_source(session: dict[str, Any]) -> str:
    """Single ownership: live when runtime live draft is active, else simulator."""
    return ACTIVE_DRAFT_SOURCE_LIVE if should_resolve_live_draft_source(session) else ACTIVE_DRAFT_SOURCE_SIMULATOR


def simulator_teams_from_board(board: Any) -> list[str]:
    """Fantasy team names in snake slot-1 order from a canonical board."""
    df = coerce_board_table(board)
    if df.empty or "Team" not in df.columns:
        return []
    work = df.sort_values("Pick", kind="stable") if "Pick" in df.columns else df
    teams: list[str] = []
    seen: set[str] = set()
    for team in work["Team"].dropna().astype(str):
        name = str(team).strip()
        if name and name not in seen:
            teams.append(name)
            seen.add(name)
    return teams


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value: Any) -> Any:
    return sanitize_for_json(value)


def editor_widget_key(session: dict[str, Any]) -> str:
    """Versioned widget key — Streamlit-owned; never assign to this key in app code."""
    version = int(session.get(DRAFT_ROOM_EDITOR_VERSION_KEY) or 0)
    return f"{DRAFT_ROOM_EDITOR_KEY_PREFIX}_{version}"


def bump_editor_version(session: dict[str, Any]) -> int:
    version = int(session.get(DRAFT_ROOM_EDITOR_VERSION_KEY) or 0) + 1
    session[DRAFT_ROOM_EDITOR_VERSION_KEY] = version
    return version


def sync_editor_seed(session: dict[str, Any], table: Any, *, force_reset: bool = False) -> None:
    """Update seed dataframe used as data_editor initial value (safe to assign)."""
    if not is_runtime_table(table):
        return
    seed = session.get(DRAFT_ROOM_EDITOR_SEED_KEY)
    if force_reset or not is_runtime_table(seed):
        session[DRAFT_ROOM_EDITOR_SEED_KEY] = table.copy()
        return
    if table_pick_count(table) > table_pick_count(seed):
        session[DRAFT_ROOM_EDITOR_SEED_KEY] = table.copy()


def apply_restored_board_to_session(
    session: dict[str, Any],
    table: pd.DataFrame,
    *,
    blob: dict[str, Any] | None = None,
    bump_widget: bool = True,
) -> pd.DataFrame:
    """After cloud/disk restore: canonical table + seed + new widget version."""
    session[DRAFT_ROOM_TABLE_KEY] = table
    if isinstance(blob, dict):
        session[DRAFT_ROOM_STATE_KEY] = blob
    session[DRAFT_ROOM_EDITOR_CACHE_KEY] = table.copy()
    sync_editor_seed(session, table, force_reset=True)
    if bump_widget:
        bump_editor_version(session)
    return table


def is_board_editor_widget_key(key: str) -> bool:
    """True only for versioned Streamlit widget keys (draft_room_board_editor_0), not cache/seed."""
    prefix = f"{DRAFT_ROOM_EDITOR_KEY_PREFIX}_"
    text = str(key)
    if not text.startswith(prefix):
        return False
    if text in (DRAFT_ROOM_EDITOR_CACHE_KEY, DRAFT_ROOM_EDITOR_SEED_KEY):
        return False
    suffix = text[len(prefix) :]
    return suffix.isdigit()


def apply_pending_widget_edits_to_board(
    session: dict[str, Any],
    base: pd.DataFrame,
    st: Any,
    widget_key: str,
) -> pd.DataFrame:
    """Merge keyed data_editor edited_rows into base before render."""
    _, raw = find_widget_state_in_session(st, widget_key)
    widget_dict = _coerce_data_editor_widget_state(raw)
    if not widget_dict or not widget_state_has_edits(raw):
        return base
    reconstructed = reconstruct_board_from_widget_state(widget_dict, base)
    norm = normalize_board_table(reconstructed)
    if norm is not None and table_pick_count(norm) >= table_pick_count(base):
        return norm
    return base


def capture_board_from_data_editor(
    session: dict[str, Any],
    widget_key: str,
    editor_return: Any,
    *,
    st: Any | None = None,
) -> tuple[pd.DataFrame, int, str]:
    """
    Authoritative board capture after st.data_editor.
    Prefers editor_return, then widget edited_rows reconstruction, then session table.
    """
    sources: list[tuple[pd.DataFrame, str]] = []
    debug: dict[str, Any] = {
        "widget_key": widget_key,
        "editor_return_type": type(editor_return).__name__ if editor_return is not None else "missing",
        "editor_return_pick_count": table_pick_count(editor_return) if is_runtime_table(editor_return) else 0,
    }

    if is_runtime_table(editor_return):
        norm = normalize_board_table(editor_return)
        if norm is not None:
            sources.append((norm, "editor_return"))

    read_key = widget_key
    raw_widget: Any = None
    if st is not None:
        read_key, raw_widget = find_widget_state_in_session(st, widget_key)
        debug["read_key"] = read_key
        debug["widget_state_type"] = type(raw_widget).__name__ if raw_widget is not None else "missing"
        widget_dict = _coerce_data_editor_widget_state(raw_widget)
        if widget_dict is not None:
            debug["widget_state_keys"] = sorted(str(k) for k in widget_dict.keys())
            debug["edited_rows"] = widget_dict.get("edited_rows")
            debug["added_rows"] = widget_dict.get("added_rows")
            debug["deleted_rows"] = widget_dict.get("deleted_rows")
            base = sources[0][0].copy() if sources else _base_board_for_reconstruction(session)
            reconstructed = reconstruct_board_from_widget_state(widget_dict, base)
            norm = normalize_board_table(reconstructed)
            if norm is not None:
                sources.append((norm, f"widget_reconstructed:{read_key}"))
                debug["widget_reconstructed_pick_count"] = table_pick_count(norm)
        elif is_runtime_table(raw_widget):
            norm = normalize_board_table(raw_widget)
            if norm is not None:
                sources.append((norm, f"widget_dataframe:{read_key}"))
        debug["widget_state_repr"] = repr(raw_widget)[:2000]

    for key in (DRAFT_ROOM_TABLE_KEY, DRAFT_ROOM_EDITOR_CACHE_KEY, DRAFT_ROOM_EDITOR_SEED_KEY):
        val = session.get(key)
        if is_runtime_table(val):
            norm = normalize_board_table(val)
            if norm is not None:
                sources.append((norm, key))

    best = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    best_count = -1
    best_source = "empty_fallback"
    for df, src in sources:
        count = table_pick_count(df)
        if count > best_count:
            best_count = count
            best = df
            best_source = src

    if best_count < 0:
        best_count = 0

    debug["capture_source"] = best_source
    debug["capture_pick_count"] = best_count
    session["_draft_room_widget_capture_debug"] = debug
    session["_draft_room_active_board_source"] = best_source
    session["_draft_room_active_board_pick_count"] = best_count
    return best.copy(), best_count, best_source


def prepare_board_editor_for_render(
    session: dict[str, Any],
    canonical_table: Any,
    *,
    st: Any | None = None,
    widget_key: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Return (initial_df, widget_key) for st.data_editor — never touches widget session key."""
    if not is_runtime_table(canonical_table):
        canonical_table = pd.DataFrame()
    if DRAFT_ROOM_EDITOR_VERSION_KEY not in session:
        session[DRAFT_ROOM_EDITOR_VERSION_KEY] = 0
    wkey = widget_key or editor_widget_key(session)
    table = canonical_table.copy() if is_runtime_table(canonical_table) else pd.DataFrame()
    if st is not None:
        table = apply_pending_widget_edits_to_board(session, table, st, wkey)
    sync_editor_seed(session, table, force_reset=table_pick_count(table) > 0)
    seed = session.get(DRAFT_ROOM_EDITOR_SEED_KEY)
    initial = seed.copy() if is_runtime_table(seed) else table.copy()
    session["_draft_room_editor_column_order"] = _column_names_list(initial)
    return initial, wkey


def is_runtime_table(table: Any) -> bool:
    return table is not None and hasattr(table, "to_dict")


def is_persisted_table_blob(data: Any) -> bool:
    return isinstance(data, dict) and (
        "table_records" in data or data.get("_persist_schema") == DRAFT_ROOM_PERSIST_SCHEMA
    )


def table_row_count(table: Any) -> int:
    if is_runtime_table(table):
        return len(table)
    if is_persisted_table_blob(table):
        return len(table.get("table_records") or [])
    return 0


def _player_cell_filled(val: Any) -> bool:
    if val is None:
        return False
    try:
        if pd.isna(val):
            return False
    except (TypeError, ValueError):
        pass
    text = str(val).strip()
    return bool(text) and text.lower() not in {"none", "nan", "<na>"}


_NON_PLAYER_COLUMNS = frozenset({"Round", "Pick", "Team", "round", "pick", "team"})


def detect_player_column(table: Any) -> str | None:
    """Find the column holding drafted player names (never Round/Pick/Team)."""
    if not is_runtime_table(table) or table.empty:
        return None
    preferred = ("Player", "player", "fullName", "Player Name", "Selected Player", "Name")
    for col in preferred:
        if col in table.columns:
            return col
    for col in table.columns:
        col_s = str(col)
        if col_s in _NON_PLAYER_COLUMNS:
            continue
        lower = col_s.lower()
        if "player" in lower or lower == "name":
            return col_s
    return None


def normalize_board_table(table: Any) -> pd.DataFrame | None:
    """Ensure standard Round/Pick/Team/Player columns for persistence."""
    if not is_runtime_table(table):
        return None
    out = table.copy()
    player_col = detect_player_column(out)
    if player_col and player_col != "Player":
        out["Player"] = out[player_col]
    for col in ("Round", "Pick", "Team", "Player"):
        if col not in out.columns:
            out[col] = "" if col == "Player" else None
    return out


_EMPTY_BOARD_COLUMNS = ["Round", "Pick", "Team", "Player"]


def coerce_board_table(table: Any) -> pd.DataFrame:
    """Normalize runtime DataFrame, persisted blob, records list, or invalid input to a board DataFrame."""
    if is_runtime_table(table):
        normalized = normalize_board_table(table)
        return normalized if normalized is not None else table.copy()
    if is_persisted_table_blob(table):
        restored = table_from_persist_dict(table)
        if restored is not None:
            normalized = normalize_board_table(restored)
            return normalized if normalized is not None else restored
    if isinstance(table, list) and table and all(isinstance(row, dict) for row in table):
        restored = pd.DataFrame(table)
        normalized = normalize_board_table(restored)
        return normalized if normalized is not None else restored
    if isinstance(table, dict) and table.get("table_records") is not None:
        restored = table_from_persist_dict(table)
        if restored is not None:
            normalized = normalize_board_table(restored)
            return normalized if normalized is not None else restored
    return pd.DataFrame(columns=_EMPTY_BOARD_COLUMNS)


def ensure_runtime_draft_board(session: dict[str, Any]) -> pd.DataFrame:
    """Guarantee session draft_room_table is a runtime DataFrame."""
    df = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    session[DRAFT_ROOM_TABLE_KEY] = df
    return df


def column_non_empty_counts(table: Any) -> dict[str, int]:
    if not is_runtime_table(table):
        return {}
    return {str(col): int(table[col].apply(_player_cell_filled).sum()) for col in table.columns}


def table_pick_count(table: Any, *, player_col: str | None = None) -> int:
    if is_runtime_table(table):
        df = table
        if df.empty:
            return 0
        col = player_col or detect_player_column(df)
        if not col or col not in df.columns:
            return 0
        return int(df[col].apply(_player_cell_filled).sum())
    if is_persisted_table_blob(table):
        records = table.get("table_records") or []
        if not isinstance(records, list):
            return 0
        col = player_col or "Player"
        return sum(
            1
            for row in records
            if isinstance(row, dict) and _player_cell_filled(row.get(col) or row.get("Player"))
        )
    return 0


def _table_head_preview(table: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not is_runtime_table(table) or table.empty:
        return []
    return _json_safe(table.head(limit).to_dict(orient="records"))  # type: ignore[return-value]


def _table_filled_rows_preview(table: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not is_runtime_table(table) or table.empty:
        return []
    player_col = detect_player_column(table) or "Player"
    if player_col not in table.columns:
        return []
    picked = table[table[player_col].apply(_player_cell_filled)].head(limit)
    return _json_safe(picked.to_dict(orient="records"))  # type: ignore[return-value]


def _draft_related_session_keys(session: dict[str, Any]) -> list[str]:
    terms = ("draft", "room", "board", "pick", "editor")
    return sorted(str(k) for k in session.keys() if any(t in str(k).lower() for t in terms))


def _source_pick_count(label: str, value: Any) -> dict[str, Any]:
    if is_runtime_table(value):
        return {
            "source": label,
            "type": "dataframe",
            "rows": len(value),
            "pick_count": table_pick_count(value),
            "player_column": detect_player_column(value),
            "columns": [str(c) for c in value.columns],
            "non_empty_by_column": column_non_empty_counts(value),
        }
    if isinstance(value, dict):
        return {"source": label, "type": "dict", "keys": sorted(str(k) for k in value.keys())[:20]}
    return {"source": label, "type": type(value).__name__, "pick_count": 0}


_COLUMN_LABEL_ALIASES: dict[str, str] = {
    "player": "Player",
    "team": "Team",
    "round": "Round",
    "pick": "Pick",
}


def _column_names_list(table: Any) -> list[str]:
    if not is_runtime_table(table):
        return []
    return [str(c) for c in table.columns]


def _resolve_edit_column_key(col_key: Any, columns: list[str]) -> str | None:
    """
    Map data_editor edited_rows column identifiers to dataframe column names.
    Streamlit may send column names, numeric positions (int or digit str), or labels.
    """
    if not columns:
        return None
    if col_key is None:
        return None
    if isinstance(col_key, str) and col_key.startswith("_"):
        return None

    if isinstance(col_key, int) and not isinstance(col_key, bool):
        if 0 <= col_key < len(columns):
            return columns[col_key]
        return None

    col_s = str(col_key).strip()
    if not col_s:
        return None
    if col_s in columns:
        return col_s
    if col_s.isdigit():
        idx = int(col_s)
        if 0 <= idx < len(columns):
            return columns[idx]
    lower = col_s.lower()
    for name in columns:
        if name.lower() == lower:
            return name
    alias = _COLUMN_LABEL_ALIASES.get(lower)
    if alias and alias in columns:
        return alias
    for name in columns:
        nl = name.lower()
        if lower in nl or nl in lower:
            return name
    return None


def _apply_cell_change(out: pd.DataFrame, row_idx: int, col_key: Any, val: Any) -> pd.DataFrame:
    columns = _column_names_list(out)
    col_name = _resolve_edit_column_key(col_key, columns)
    if not col_name:
        return out
    if col_name not in out.columns:
        out[col_name] = None
    out.at[row_idx, col_name] = val
    return out


def _normalize_row_change_dict(changes: Any, columns: list[str]) -> dict[str, Any]:
    if not isinstance(changes, dict):
        return {}
    normalized: dict[str, Any] = {}
    for col_key, val in changes.items():
        col_name = _resolve_edit_column_key(col_key, columns)
        if col_name:
            normalized[col_name] = val
    return normalized


def _coerce_data_editor_widget_state(raw: Any) -> dict[str, Any] | None:
    """Streamlit keyed data_editor stores {edited_rows, added_rows, deleted_rows}."""
    if not isinstance(raw, dict):
        return None
    if any(k in raw for k in ("edited_rows", "added_rows", "deleted_rows")):
        return raw
    return None


def widget_state_has_edits(raw: Any) -> bool:
    """True when keyed data_editor session value contains user edits."""
    widget_dict = _coerce_data_editor_widget_state(raw)
    if widget_dict is None:
        return False
    edited = widget_dict.get("edited_rows") or {}
    added = widget_dict.get("added_rows") or []
    deleted = widget_dict.get("deleted_rows") or []
    return bool(edited) or bool(added) or bool(deleted)


def apply_programmatic_board_update(
    session: dict[str, Any],
    table: Any,
    *,
    bump_widget: bool = True,
    reason: str = "programmatic_pick",
) -> pd.DataFrame:
    """After button/API pick entry — sync table, seed, cache, canonical blob; refresh widget."""
    normalized = sync_board_to_session_keys(session, table, local_edit=True, reason=reason)
    if bump_widget:
        bump_editor_version(session)
    session["_draft_room_last_programmatic_pick_reason"] = reason
    return normalized


def get_canonical_draft_meta(session: dict[str, Any]) -> dict[str, Any]:
    meta = session.get(CANONICAL_DRAFT_META_KEY)
    return dict(meta) if isinstance(meta, dict) else {}


def get_active_draft_mode(session: dict[str, Any]) -> str:
    """Runtime ownership wins over stale canonical meta."""
    source = resolve_active_draft_source(session)
    mode = ACTIVE_DRAFT_MODE_LIVE if source == ACTIVE_DRAFT_SOURCE_LIVE else ACTIVE_DRAFT_MODE_MANUAL
    meta = get_canonical_draft_meta(session)
    if meta.get("active_mode") != mode:
        set_canonical_draft_meta(
            session,
            mode=mode,
            source="runtime_ownership_sync",
            pick_count=table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)),
        )
    return mode


def set_canonical_draft_meta(session: dict[str, Any], *, mode: str, source: str, pick_count: int | None = None) -> None:
    meta = get_canonical_draft_meta(session)
    meta["active_mode"] = mode
    meta["source"] = source
    meta["last_updated_at"] = _utc_now_iso()
    if pick_count is not None:
        meta["pick_count"] = pick_count
    session[CANONICAL_DRAFT_META_KEY] = meta


def build_snake_board(team_names: list[str], *, rounds: int) -> pd.DataFrame:
    """Snake-order grid with empty Player cells."""
    teams = [str(t).strip() for t in team_names if str(t).strip()]
    if not teams:
        teams = ["Team 1", "Team 2"]
    team_count = len(teams)
    rows: list[dict[str, Any]] = []
    for pick in range(1, int(rounds) * team_count + 1):
        rnd = ((pick - 1) // team_count) + 1
        within_round = (pick - 1) % team_count
        team = teams[within_round] if rnd % 2 == 1 else teams[::-1][within_round]
        rows.append({"Round": rnd, "Pick": pick, "Team": team, "Player": ""})
    return pd.DataFrame(rows)


def get_canonical_draft_board(session: dict[str, Any]) -> pd.DataFrame:
    """Single board every draft tool should read."""
    prepare_draft_room_state(session)
    return ensure_runtime_draft_board(session).copy()


def get_all_drafted_player_names(session: dict[str, Any]) -> list[str]:
    """Names on the richest in-memory board — avoids prepare_draft_room_state clobber during assign."""
    table, _, _ = _resolve_richest_draft_board(session)
    return _drafted_players_from_table(table)


def _next_open_row_index(table: pd.DataFrame) -> int | None:
    if not is_runtime_table(table) or table.empty or "Player" not in table.columns:
        return None
    work = table.copy()
    if "Pick" in work.columns:
        work = work.sort_values("Pick", kind="stable").reset_index(drop=True)
    else:
        work = work.reset_index(drop=True)
    for idx, row in work.iterrows():
        if not _player_cell_filled(row.get("Player")):
            return int(idx)
    return None


def open_pick_row_options(table: Any) -> list[tuple[int, str]]:
    """Return (dataframe row index, label) for each open Player cell."""
    df = coerce_board_table(table)
    if df.empty or "Player" not in df.columns:
        return []
    work = df.copy()
    if "Pick" in work.columns:
        work = work.sort_values("Pick", kind="stable")
    options: list[tuple[int, str]] = []
    for idx, row in work.iterrows():
        if not _player_cell_filled(row.get("Player")):
            pick_n = row.get("Pick", "")
            team = str(row.get("Team", "") or "").strip()
            label = f"Pick {pick_n} — {team}" if team else f"Pick {pick_n}"
            options.append((int(idx), label.strip()))
    return options


def pick_label_row_map(table: Any) -> dict[str, int]:
    """Map pick labels from open_pick_row_options to dataframe row indices."""
    return {label: idx for idx, label in open_pick_row_options(table)}


_BOARD_ASSIGN_SUBMIT_TRACE_KEY = "_draft_room_assign_submit_trace"

_BOARD_ASSIGN_SUBMIT_FIELDS = (
    "assignment_button_clicked",
    "selected_pick",
    "selected_player_search_text",
    "selected_player_match",
    "selected_player_official_name",
    "assign_player_to_board_row_called",
    "target_row_index",
    "before_pick_count",
    "after_pick_count",
    "error",
    "message",
)


def record_board_assign_submit_trace(
    session: dict[str, Any],
    trace: dict[str, Any],
) -> None:
    """Persist last assign-form submit attempt for Board tab diagnostics."""
    stored = {k: trace.get(k) for k in _BOARD_ASSIGN_SUBMIT_FIELDS}
    session[_BOARD_ASSIGN_SUBMIT_TRACE_KEY] = stored
    pick_count = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    if stored.get("assign_player_to_board_row_called"):
        pick_count = int(stored.get("after_pick_count") or pick_count or 0)
    session["_draft_room_widget_capture_debug"] = {
        "capture_source": "board_assign_submit",
        "capture_pick_count": pick_count,
        "editor_return_pick_count": pick_count,
        "widget_reconstructed_pick_count": pick_count,
        "editor_return_type": "assignment_form",
        "edited_rows": "n/a (form assignment, not data_editor)",
        **stored,
    }
    session["_draft_room_active_board_source"] = "draft_room_table:board_assign_submit"
    session["_draft_room_active_board_pick_count"] = pick_count


def record_board_assignment_diagnostics(
    session: dict[str, Any],
    *,
    pick_count: int,
    source: str = "pick_assignment",
) -> None:
    submit = session.get(_BOARD_ASSIGN_SUBMIT_TRACE_KEY)
    submit_after = (
        int(submit.get("after_pick_count") or 0) if isinstance(submit, dict) else 0
    )
    effective = max(int(pick_count or 0), effective_board_pick_count(session), submit_after)
    if isinstance(submit, dict) and submit.get("assignment_button_clicked"):
        merged = dict(submit)
        merged["capture_pick_count"] = effective
        merged["editor_return_pick_count"] = effective
        merged["widget_reconstructed_pick_count"] = effective
        session["_draft_room_widget_capture_debug"] = {
            "capture_source": "board_assign_submit",
            "capture_pick_count": effective,
            "editor_return_pick_count": effective,
            "widget_reconstructed_pick_count": effective,
            "editor_return_type": "assignment_form",
            "edited_rows": "n/a (form assignment, not data_editor)",
            **merged,
        }
    else:
        session["_draft_room_widget_capture_debug"] = {
            "capture_source": source,
            "capture_pick_count": effective,
            "editor_return_pick_count": effective,
            "widget_reconstructed_pick_count": effective,
            "editor_return_type": "assignment_form",
            "edited_rows": "n/a (form assignment, not data_editor)",
        }
    session["_draft_room_active_board_source"] = f"draft_room_table:{source}"
    session["_draft_room_active_board_pick_count"] = effective


def submit_board_pick_assignment(
    session: dict[str, Any],
    *,
    pick_label: str,
    player_match: str,
    pick_row_by_label: dict[str, int],
    name_index: dict[str, str] | None = None,
    all_names: list[str] | None = None,
    search_text: str = "",
) -> dict[str, Any]:
    """Handle Set player on pick — records submit trace and writes draft_room_table."""
    trace: dict[str, Any] = {
        "assignment_button_clicked": True,
        "selected_pick": str(pick_label or ""),
        "selected_player_search_text": str(search_text or ""),
        "selected_player_match": str(player_match or "").strip(),
        "selected_player_official_name": "",
        "assign_player_to_board_row_called": False,
        "target_row_index": None,
        "before_pick_count": table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)),
        "after_pick_count": 0,
        "error": "",
        "message": "",
    }
    record_board_assign_submit_trace(session, trace)

    match = trace["selected_player_match"]
    if not match or match.startswith("—"):
        trace["error"] = "no_player_match"
        trace["message"] = "Search and select a player first."
        record_board_assign_submit_trace(session, trace)
        return {"ok": False, "trace": trace, **trace}

    official = match
    if name_index:
        try:
            from draft_player_names import resolve_draft_player_name

            resolved, _ = resolve_draft_player_name(match, name_index, all_names=all_names)
            if resolved:
                official = resolved
        except Exception:
            pass
    trace["selected_player_official_name"] = official

    row_idx = pick_row_by_label.get(str(pick_label or "").strip())
    if row_idx is None:
        trace["error"] = "bad_pick"
        trace["message"] = "Pick row not found."
        record_board_assign_submit_trace(session, trace)
        return {"ok": False, "trace": trace, **trace}

    trace["target_row_index"] = int(row_idx)
    trace["assign_player_to_board_row_called"] = True
    record_board_assign_submit_trace(session, trace)

    res = assign_player_to_board_row(session, int(row_idx), official)
    trace["before_pick_count"] = int(res.get("before_pick_count") or trace["before_pick_count"])
    trace["after_pick_count"] = int(res.get("after_pick_count") or 0)
    trace["error"] = str(res.get("error") or "")
    trace["message"] = str(res.get("message") or "")
    if res.get("ok"):
        pick_count = int(res.get("after_pick_count") or 0)
        trace["draft_room_state_pick_count"] = table_pick_count(session.get(DRAFT_ROOM_STATE_KEY))
        trace["canonical_meta_pick_count"] = get_canonical_draft_meta(session).get("pick_count")
        trace["local_has_draft_room_board"] = bool(session.get("local_has_draft_room_board"))
    record_board_assign_submit_trace(session, trace)
    out = {"ok": bool(res.get("ok")), "trace": trace}
    out.update(res)
    return out


def assign_player_to_board_row(
    session: dict[str, Any],
    row_index: int,
    player_name: str,
) -> dict[str, Any]:
    """Set official player name on a board row — reliable path bypassing data_editor."""
    name = str(player_name or "").strip()
    result: dict[str, Any] = {
        "ok": False,
        "player": name,
        "row_index": row_index,
        "before_pick_count": table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)),
        "after_pick_count": 0,
        "message": "",
        "error": "",
    }
    if not name:
        result["error"] = "no_player"
        result["message"] = "Select a player first."
        return result

    table = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    if table.empty:
        result["error"] = "empty_board"
        result["message"] = "Board is empty."
        return result
    if row_index < 0 or row_index not in table.index:
        result["error"] = "bad_row"
        result["message"] = "Invalid pick row."
        return result

    existing = set(get_all_drafted_player_names(session))
    current_at_row = str(table.at[row_index, "Player"] or "").strip()
    if name in existing and current_at_row != name:
        result["error"] = "duplicate"
        result["message"] = f"{name} is already on the board."
        return result

    table = table.copy()
    table.at[row_index, "Player"] = name
    updated = apply_programmatic_board_update(
        session, table, bump_widget=False, reason="board_pick_assign"
    )
    pick_count = table_pick_count(updated)
    result["after_pick_count"] = pick_count
    result["ok"] = True
    pick_label = table.at[row_index, "Pick"] if "Pick" in table.columns else row_index + 1
    result["message"] = f"Set {name} on pick {pick_label}."
    record_board_assignment_diagnostics(session, pick_count=pick_count)
    return result


def _parse_pasted_player_lines(text: str) -> list[str]:
    names: list[str] = []
    import re

    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\d+[\.\)\:]?\s*", "", line).strip()
        if line:
            names.append(line)
    return list(dict.fromkeys(names))


def add_player_to_next_open_pick(session: dict[str, Any], player_name: Any) -> dict[str, Any]:
    """Simulator-fast path: next open pick row, no team selection."""
    player_name = str(player_name or "").strip()
    result: dict[str, Any] = {
        "ok": False,
        "player": player_name,
        "target_pick": None,
        "target_row_index": None,
        "before_pick_count": table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)),
        "after_pick_count": 0,
        "message": "",
        "error": "",
    }
    if not player_name:
        result["error"] = "no_player_selected"
        result["message"] = "Enter a player name first."
        return result

    table = get_canonical_draft_board(session)
    if table.empty:
        teams = [str(session.get("room_your_team") or "Team 1")]
        rounds = int(session.get("room_rounds") or 20)
        table = build_snake_board(teams, rounds=rounds)

    existing = get_all_drafted_player_names(session)
    if player_name in existing:
        result["error"] = "player_already_drafted"
        result["message"] = f"{player_name} is already on the board."
        return result

    row_idx = _next_open_row_index(table)
    if row_idx is None:
        result["error"] = "board_full"
        result["message"] = "Board is full — no open pick rows."
        return result

    if "Pick" in table.columns:
        table = table.sort_values("Pick", kind="stable").reset_index(drop=True)
    else:
        table = table.reset_index(drop=True)

    table.at[row_idx, "Player"] = player_name
    result["target_row_index"] = row_idx
    if "Pick" in table.columns:
        result["target_pick"] = table.at[row_idx, "Pick"]

    updated = apply_programmatic_board_update(session, table, reason="simulator_add_player")
    result["after_pick_count"] = table_pick_count(updated)
    result["ok"] = True
    pick_n = result.get("target_pick") or (row_idx + 1)
    result["message"] = f"Logged {player_name} to pick {pick_n}."
    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_MANUAL,
        source="draft_room_simulator",
        pick_count=result["after_pick_count"],
    )
    session["_draft_room_simulator_last_add"] = result
    return result


def paste_players_to_board(session: dict[str, Any], text: str) -> dict[str, Any]:
    """Fill next open rows from pasted list (numbered or plain lines)."""
    names = _parse_pasted_player_lines(text)
    result: dict[str, Any] = {
        "ok": False,
        "parsed_count": len(names),
        "added_count": 0,
        "before_pick_count": table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)),
        "after_pick_count": 0,
        "message": "",
        "error": "",
    }
    if not names:
        result["error"] = "no_players_parsed"
        result["message"] = "Paste one player per line."
        return result

    table = get_canonical_draft_board(session)
    if table.empty:
        team_lines = str(session.get("room_team_names") or session.get("room_your_team") or "Team 1")
        teams = [x.strip() for x in team_lines.splitlines() if x.strip()] or ["Team 1"]
        table = build_snake_board(teams, rounds=int(session.get("room_rounds") or 20))

    if "Pick" in table.columns:
        table = table.sort_values("Pick", kind="stable").reset_index(drop=True)
    else:
        table = table.reset_index(drop=True)

    existing = set(get_all_drafted_player_names(session))
    added = 0
    for name in names:
        if name in existing:
            continue
        row_idx = _next_open_row_index(table)
        if row_idx is None:
            break
        table.at[row_idx, "Player"] = name
        existing.add(name)
        added += 1

    if added == 0:
        result["error"] = "nothing_added"
        result["message"] = "No new players added (board full or all duplicates)."
        return result

    updated = apply_programmatic_board_update(session, table, reason="simulator_paste")
    result["added_count"] = added
    result["after_pick_count"] = table_pick_count(updated)
    result["ok"] = True
    result["message"] = f"Pasted {added} player(s) onto the board."
    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_MANUAL,
        source="draft_room_simulator_paste",
        pick_count=result["after_pick_count"],
    )
    session["_draft_room_simulator_last_paste"] = result
    return result


def board_team_names_match(table: Any, expected_teams: list[str]) -> bool:
    """True when board Team column matches the configured team name list."""
    if table is None or getattr(table, "empty", True):
        return not expected_teams
    if "Team" not in getattr(table, "columns", []):
        return False
    board_teams = list(
        dict.fromkeys(str(t).strip() for t in table["Team"].astype(str).tolist() if str(t).strip())
    )
    exp = [str(t).strip() for t in expected_teams if str(t).strip()]
    return board_teams == exp[: len(board_teams)] and len(board_teams) == len(exp)


def rebuild_simulator_board_for_teams(session: dict[str, Any]) -> pd.DataFrame:
    """Rebuild snake board from room_team_names / room_rounds (preserves no picks)."""
    team_lines = str(session.get("room_team_names") or "")
    teams = [x.strip() for x in team_lines.splitlines() if x.strip()]
    if not teams:
        teams = [str(session.get("room_your_team") or "Team 1"), "Team 2"]
    rounds = int(session.get("room_rounds") or 20)
    session.pop(DRAFT_ROOM_EDITOR_CACHE_KEY, None)
    table = build_snake_board(teams, rounds=rounds)
    return apply_programmatic_board_update(session, table, reason="rebuild_board_teams")


def reset_canonical_draft_board(session: dict[str, Any]) -> pd.DataFrame:
    """Fresh snake board — Start New Draft."""
    team_lines = str(session.get("room_team_names") or "")
    teams = [x.strip() for x in team_lines.splitlines() if x.strip()]
    if not teams:
        teams = [str(session.get("room_your_team") or "Team 1"), "Team 2"]
    rounds = int(session.get("room_rounds") or 20)
    table = build_snake_board(teams, rounds=rounds)
    out = apply_programmatic_board_update(session, table, reason="reset_canonical_board")
    set_canonical_draft_meta(session, mode=ACTIVE_DRAFT_MODE_MANUAL, source="reset", pick_count=0)
    session.pop("_draft_room_skip_editor_resolve_clobber", None)
    return out


def reset_simulator_board_only(session: dict[str, Any]) -> pd.DataFrame:
    """Option B: clear practice board only; Live Draft Room record stays if present."""
    session.pop(DRAFT_ROOM_EDITOR_CACHE_KEY, None)
    session.pop("draft_room_board_editor_cache", None)
    session.pop("draft_room_board_editor_seed", None)
    out = reset_canonical_draft_board(session)
    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_MANUAL,
        source="simulator_reset_only",
        pick_count=0,
    )
    return out


def delete_live_draft_only(session: dict[str, Any]) -> dict[str, Any]:
    """Clear Live Draft Room state only — canonical simulator board and queue stay."""
    trace: dict[str, Any] = {"ok": True, "cleared_live": False}
    try:
        from live_draft_state import clear_live_draft_state

        clear_live_draft_state(session, reason="delete_live_draft_only")
        trace["cleared_live"] = True
    except Exception:
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)
        trace["cleared_live"] = True
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Live Draft Room")
        if isinstance(block, dict):
            block.pop("live_draft_room", None)
    try:
        from draft_actions import _clear_ami_draft_cache

        _clear_ami_draft_cache(session)
    except Exception:
        pass
    meta = get_canonical_draft_meta(session)
    if meta.get("active_mode") == ACTIVE_DRAFT_MODE_LIVE:
        set_canonical_draft_meta(
            session,
            mode=ACTIVE_DRAFT_MODE_MANUAL,
            source="live_draft_deleted",
            pick_count=table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)),
        )
    return trace


def delete_active_draft(session: dict[str, Any], *, clear_queue: bool = True) -> dict[str, Any]:
    """Option A: wipe live draft + canonical board + draft queue (fresh start)."""
    trace: dict[str, Any] = {
        "ok": True,
        "cleared_live": False,
        "cleared_board": False,
        "cleared_queue": False,
    }
    try:
        from live_draft_state import clear_live_draft_state

        clear_live_draft_state(session, reason="delete_active_draft")
        trace["cleared_live"] = True
    except Exception:
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)
        trace["cleared_live"] = True
    reset_canonical_draft_board(session)
    trace["cleared_board"] = True
    session[CANONICAL_DRAFT_META_KEY] = {}
    session.pop("_canonical_draft_last_live_sync", None)
    if clear_queue:
        try:
            from draft_state import clear_draft_queue

            clear_draft_queue(session, reason="delete_active_draft")
            trace["cleared_queue"] = True
        except Exception:
            pass
    return trace


def get_active_draft_status(session: dict[str, Any]) -> dict[str, Any]:
    """Cross-page summary: mode, pick progress, queue size, live clock."""
    mode = get_active_draft_mode(session)
    picks = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    queue = session.get("draft_queue") or []
    queue_len = len(queue) if isinstance(queue, list) else 0
    status: dict[str, Any] = {
        "active": picks > 0 or mode == ACTIVE_DRAFT_MODE_LIVE,
        "mode": mode,
        "pick_count": picks,
        "queue_len": queue_len,
        "current_round": None,
        "current_pick": None,
        "my_next_pick": None,
        "your_team": str(session.get("room_your_team") or "").strip() or None,
        "live_status": None,
        "return_page": "Live Draft Room" if mode == ACTIVE_DRAFT_MODE_LIVE else "Draft Room Simulator",
    }
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state

        prepare_live_draft_state(session)
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict) and room:
            status["live_status"] = str(room.get("status") or "")
            if status["live_status"] in ("in_progress", "paused"):
                status["active"] = True
            pick_order = list(room.get("pick_order") or [])
            idx = int(room.get("current_pick_index") or 0)
            if idx < len(pick_order):
                slot = pick_order[idx]
                if isinstance(slot, dict):
                    status["current_round"] = slot.get("Round")
                    status["current_pick"] = slot.get("Pick")
            your_team = str(
                (room.get("config") or {}).get("your_team")
                or (room.get("config") or {}).get("user_team")
                or session.get("room_your_team")
                or ""
            ).strip()
            if your_team:
                status["your_team"] = your_team
                for i in range(idx, len(pick_order)):
                    slot_i = pick_order[i]
                    if isinstance(slot_i, dict) and str(slot_i.get("Team") or "").strip() == your_team:
                        status["my_next_pick"] = slot_i.get("Pick")
                        break
    except Exception:
        pass
    if not status["current_pick"] and picks > 0:
        status["current_pick"] = picks + 1
    if not status["current_round"] and picks > 0:
        team_count = int(session.get("room_team_count") or 12)
        status["current_round"] = ((picks) // team_count) + 1 if team_count else None
    return status


def round_one_draft_slot(team_names: list[str], your_team: str) -> int | None:
    """Round-1 draft position (1-based) for ``your_team`` in the team list."""
    team_s = str(your_team or "").strip()
    if not team_s:
        return None
    for i, name in enumerate(team_names):
        if str(name).strip() == team_s:
            return i + 1
    return None


def next_board_pick_for_team(
    table: Any,
    team_name: str,
    *,
    min_pick: int = 1,
) -> int | None:
    """Next open overall pick number for ``team_name`` on a Draft Room board."""
    if not isinstance(table, pd.DataFrame) or table.empty:
        return None
    if "Team" not in table.columns or "Pick" not in table.columns:
        return None
    team_s = str(team_name or "").strip()
    if not team_s:
        return None
    candidates: list[int] = []
    for _, row in table.iterrows():
        if str(row.get("Team") or "").strip() != team_s:
            continue
        player = str(row.get("Player") or "").strip()
        try:
            pk = int(row.get("Pick"))
        except (TypeError, ValueError):
            continue
        if pk >= int(min_pick) and not player:
            candidates.append(pk)
    return min(candidates) if candidates else None


def draft_board_summary_for_team(
    table: Any,
    *,
    your_team: str,
    team_names: list[str] | None = None,
    pick_adjustment: int = 0,
    num_teams: int | None = None,
) -> dict[str, Any]:
    """Plain-language draft progress for Draft Assistant / status panels."""
    names = [str(x).strip() for x in (team_names or []) if str(x).strip()]
    teams = max(int(num_teams or 0), len(names), 1)
    team_s = str(your_team or "").strip()

    players_you: list[str] = []
    players_league: list[str] = []
    if isinstance(table, pd.DataFrame) and not table.empty and "Player" in table.columns:
        for _, row in table.iterrows():
            player = str(row.get("Player") or "").strip()
            if not player:
                continue
            row_team = str(row.get("Team") or "").strip()
            if team_s and row_team == team_s:
                players_you.append(player)
            else:
                players_league.append(player)

    players_you = list(dict.fromkeys(players_you))
    players_league = list(dict.fromkeys(players_league))
    total_picked = len(players_you) + len(players_league)
    current_pick = max(1, total_picked + 1 + int(pick_adjustment or 0))
    current_round = ((current_pick - 1) // teams) + 1 if teams else 1
    draft_slot = round_one_draft_slot(names, team_s) if names else None
    your_next_pick = next_board_pick_for_team(table, team_s, min_pick=current_pick)

    return {
        "your_team": team_s or None,
        "players_you_drafted": len(players_you),
        "players_league_drafted": len(players_league),
        "current_pick": current_pick,
        "current_round": current_round,
        "draft_slot": draft_slot,
        "your_next_pick": your_next_pick,
        "num_teams": teams,
    }


def render_active_draft_banner(st: Any, session: dict[str, Any]) -> None:
    """Global banner when a draft is active — visible on every page."""
    try:
        from live_draft_navigation import get_draft_return_context

        if get_draft_return_context(session):
            return
    except ImportError:
        pass
    try:
        from live_draft_state import has_active_live_draft

        if has_active_live_draft(session):
            return
    except Exception:
        pass
    status = get_active_draft_status(session)
    if not status.get("active"):
        return
    mode = status.get("mode")
    label = "Live Draft" if mode == ACTIVE_DRAFT_MODE_LIVE else "Practice Draft"
    parts = [f"**{label}** · **{status.get('pick_count', 0)}** pick(s) logged"]
    if status.get("current_round") and status.get("current_pick"):
        parts.append(f"Round **{status['current_round']}** · Pick **{status['current_pick']}**")
    if status.get("my_next_pick"):
        parts.append(f"My next pick: **{status['my_next_pick']}**")
    if status.get("queue_len"):
        parts.append(f"Queue: **{status['queue_len']}**")
    col_msg, col_btn = st.sidebar.columns([3, 1])
    with col_msg:
        st.info(" · ".join(parts))
    with col_btn:
        if st.button("Return to Draft", key="active_draft_return_btn", use_container_width=True):
            session["_navigate_to_page"] = status.get("return_page") or "Draft Room Simulator"
            st.rerun()


def sync_live_draft_room_to_canonical_board(session: dict[str, Any], room: Any) -> pd.DataFrame:
    """Live Draft Room → canonical draft_room_table (auto after each pick)."""
    if not isinstance(room, dict):
        return pd.DataFrame()
    cfg = dict(room.get("config") or {})
    teams = list(room.get("teams") or [])
    picks_per_team = int(cfg.get("picks_per_team") or cfg.get("rounds") or session.get("room_rounds") or 15)
    pick_order = list(room.get("pick_order") or [])
    if not pick_order and teams:
        pick_order = []
        pick_no = 1
        for rnd in range(1, picks_per_team + 1):
            round_teams = teams if rnd % 2 == 1 else list(reversed(teams))
            for team in round_teams:
                pick_order.append({"Round": rnd, "Pick": pick_no, "Team": team})
                pick_no += 1

    rows: list[dict[str, Any]] = []
    for slot in pick_order:
        if isinstance(slot, dict):
            rows.append(
                {
                    "Round": slot.get("Round"),
                    "Pick": slot.get("Pick"),
                    "Team": slot.get("Team"),
                    "Player": "",
                }
            )
    table = pd.DataFrame(rows) if rows else build_snake_board(teams or ["Team 1"], rounds=picks_per_team)

    picks_by_number: dict[int, tuple[str, str]] = {}
    for rec in room.get("draft_board") or []:
        if not isinstance(rec, dict):
            continue
        try:
            pick_n = int(rec.get("Pick"))
        except (TypeError, ValueError):
            continue
        player = str(rec.get("fullName") or rec.get("Player") or "").strip()
        team = str(rec.get("Fantasy Team") or rec.get("Team") or "").strip()
        if player:
            picks_by_number[pick_n] = (player, team)

    if not table.empty and "Pick" in table.columns:
        table = table.sort_values("Pick", kind="stable").reset_index(drop=True)
        for idx, row in table.iterrows():
            try:
                pk = int(row["Pick"])
            except (TypeError, ValueError):
                continue
            if pk in picks_by_number:
                player, team = picks_by_number[pk]
                table.at[idx, "Player"] = player
                if team:
                    table.at[idx, "Team"] = team

    if teams:
        session["room_team_names"] = "\n".join(teams)
        session["room_team_count"] = len(teams)
    session["room_rounds"] = picks_per_team
    your_team = ""
    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            your_team = active_participant_team(session)
    except ImportError:
        pass
    if not your_team:
        your_team = str(cfg.get("your_team") or cfg.get("user_team") or "").strip()
    if your_team:
        try:
            from draft_room_context import is_multiplayer_draft_active

            if not is_multiplayer_draft_active(session):
                session["room_your_team"] = your_team
        except ImportError:
            session["room_your_team"] = your_team
    if cfg.get("scoring_type"):
        session["room_format"] = str(cfg.get("scoring_type"))

    out = apply_programmatic_board_update(session, table, reason="live_draft_sync")
    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_LIVE,
        source="live_draft_room",
        pick_count=table_pick_count(out),
    )
    session["_canonical_draft_last_live_sync"] = _utc_now_iso()
    return out


def render_canonical_draft_banner(st: Any, session: dict[str, Any]) -> None:
    mode = get_active_draft_mode(session)
    picks = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    label = "Live draft" if mode == ACTIVE_DRAFT_MODE_LIVE else "Practice draft"
    st.info(f"**{label}** · **{picks}** pick(s) logged on your draft board.")


def preserve_richer_session_board(
    session: dict[str, Any],
    resolved: Any,
    resolved_count: int,
) -> tuple[pd.DataFrame | None, int, str]:
    """Never let empty editor resolve clobber a richer programmatic draft_room_table."""
    runtime = session.get(DRAFT_ROOM_TABLE_KEY)
    runtime_count = table_pick_count(runtime)
    blob = _draft_room_from_blob(session)
    blob_count = table_pick_count(blob) if isinstance(blob, dict) else 0
    if blob_count > resolved_count and blob_count > runtime_count and isinstance(blob, dict) and blob.get("table_records") is not None:
        restored = table_from_persist_dict(blob)
        if restored is not None and table_pick_count(restored) > resolved_count:
            out = restored.copy()
            session[DRAFT_ROOM_TABLE_KEY] = out.copy()
            session[DRAFT_ROOM_EDITOR_CACHE_KEY] = out.copy()
            sync_editor_seed(session, out, force_reset=True)
            session["_draft_room_active_board_source"] = f"{DRAFT_ROOM_STATE_KEY}:preserved_over_resolve"
            session["_draft_room_active_board_pick_count"] = table_pick_count(out)
            return out, table_pick_count(out), "preserved_canonical_blob"
    if is_runtime_table(runtime) and runtime_count > resolved_count:
        out = runtime.copy()
        session[DRAFT_ROOM_EDITOR_CACHE_KEY] = out.copy()
        sync_editor_seed(session, out, force_reset=True)
        session["_draft_room_active_board_source"] = f"{DRAFT_ROOM_TABLE_KEY}:preserved_over_resolve"
        session["_draft_room_active_board_pick_count"] = runtime_count
        return out, runtime_count, "preserved_session_table"
    if is_runtime_table(resolved):
        return resolved.copy(), resolved_count, ""
    if is_runtime_table(runtime):
        return runtime.copy(), runtime_count, "fallback_session_table"
    return None, 0, ""


def _base_board_for_reconstruction(session: dict[str, Any]) -> pd.DataFrame:
    for key in (DRAFT_ROOM_EDITOR_SEED_KEY, DRAFT_ROOM_TABLE_KEY, DRAFT_ROOM_EDITOR_CACHE_KEY):
        val = session.get(key)
        if is_runtime_table(val):
            return val.copy()
    return pd.DataFrame()


def _seed_base_source_key(session: dict[str, Any]) -> str:
    for key in (DRAFT_ROOM_EDITOR_SEED_KEY, DRAFT_ROOM_TABLE_KEY, DRAFT_ROOM_EDITOR_CACHE_KEY):
        if is_runtime_table(session.get(key)):
            return key
    return "missing"


def reconstruct_board_from_widget_state(widget_state: dict[str, Any], base: Any) -> pd.DataFrame:
    """Apply data_editor delta dict onto seed/base dataframe."""
    out = base.copy() if is_runtime_table(base) else pd.DataFrame()
    if not widget_state:
        return normalize_board_table(out) if is_runtime_table(out) else out

    columns = _column_names_list(out)
    edited_rows = widget_state.get("edited_rows") or {}
    if isinstance(edited_rows, dict):
        for idx_raw, changes in edited_rows.items():
            try:
                idx = int(idx_raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(changes, dict) or idx < 0:
                continue
            while len(out) <= idx:
                out = pd.concat([out, pd.DataFrame([{}])], ignore_index=True)
                columns = _column_names_list(out)
            normalized_changes = _normalize_row_change_dict(changes, columns)
            for col_name, val in normalized_changes.items():
                out = _apply_cell_change(out, idx, col_name, val)

    deleted_rows = widget_state.get("deleted_rows") or []
    if isinstance(deleted_rows, list) and deleted_rows:
        drop_idx = [int(i) for i in deleted_rows if str(i).isdigit() or isinstance(i, int)]
        if drop_idx and not out.empty:
            out = out.drop(index=[i for i in drop_idx if i in out.index], errors="ignore").reset_index(drop=True)

    added_rows = widget_state.get("added_rows") or []
    if isinstance(added_rows, list) and added_rows:
        columns = _column_names_list(out)
        new_rows: list[dict[str, Any]] = []
        for row in added_rows:
            if not isinstance(row, dict):
                continue
            normalized = _normalize_row_change_dict(row, columns)
            if normalized:
                new_rows.append(normalized)
        if new_rows:
            out = pd.concat([out, pd.DataFrame(new_rows)], ignore_index=True)

    return normalize_board_table(out) if is_runtime_table(out) else out


def _drafted_players_from_table(table: Any) -> list[str]:
    df = coerce_board_table(table)
    if df.empty:
        return []
    col = detect_player_column(df)
    if not col or col not in df.columns:
        return []
    names = [str(v).strip() for v in df[col].tolist() if _player_cell_filled(v)]
    return list(dict.fromkeys(names))


def find_widget_state_in_session(st: Any, widget_key: str) -> tuple[str, Any]:
    """Return (actual_key, raw_value) from Streamlit session state."""
    ss = getattr(st, "session_state", None)
    if ss is None:
        return widget_key, None
    if widget_key in ss:
        return widget_key, ss.get(widget_key)
    prefix = f"{DRAFT_ROOM_EDITOR_KEY_PREFIX}_"
    matches = [str(k) for k in ss.keys() if str(k).startswith(prefix)]

    def _version_num(key: str) -> int:
        try:
            return int(str(key).replace(prefix, "") or "0")
        except ValueError:
            return 0

    if matches:
        last_key = max(matches, key=_version_num)
        return last_key, ss.get(last_key)
    return widget_key, None


def collect_pick_entry_diagnostics(
    session: dict[str, Any],
    st: Any | None = None,
    *,
    player_names_pool: list[str] | None = None,
) -> dict[str, Any]:
    """Locate where drafted player names actually live in session state."""
    table = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    cache = session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)
    seed = session.get(DRAFT_ROOM_EDITOR_SEED_KEY)
    drafted = _drafted_players_from_table(table)
    info: dict[str, Any] = {
        "workflow_primary_board_tab": "Select a player from the Player dropdown in each grid row, OR use Quick draft below.",
        "workflow_draft_assistant": "Draft Assistant → Player actions popover → Draft this player (only on your snake-draft turn).",
        "workflow_not_board_writes": "Simulate Draft Pick, Add to Queue, and Send to Comparison do NOT write the board.",
        "draft_room_table_pick_count": table_pick_count(table),
        "draft_room_table_drafted_players": drafted[:20],
        "draft_room_editor_cache_pick_count": table_pick_count(cache),
        "draft_room_editor_seed_pick_count": table_pick_count(seed),
        "draft_queue": list(session.get("draft_queue") or [])[:15],
        "pending_draft_assistant_player": session.get("pending_draft_assistant_player"),
        "room_your_team": session.get("room_your_team"),
        "next_open_pick_team": None,
        "simulated_draft_room_pick_count": table_pick_count(session.get("simulated_draft_room_table")),
        "live_draft_board_pick_count": 0,
    }
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        live = session.get(LIVE_DRAFT_ROOM_KEY) or {}
        board = live.get("draft_board") if isinstance(live, dict) else None
        if isinstance(board, list):
            info["live_draft_board_pick_count"] = len(board)
    except Exception:
        pass

    if is_runtime_table(table) and not table.empty and "Player" in table.columns and "Team" in table.columns:
        t = table.copy()
        open_mask = t["Player"].fillna("").astype(str).str.strip().eq("")
        if open_mask.any():
            if "Pick" in t.columns:
                t = t.sort_values("Pick", kind="stable")
            for _, row in t.iterrows():
                if str(row.get("Player", "")).strip() == "":
                    info["next_open_pick_team"] = str(row.get("Team", "")).strip()
                    break
        yt = str(session.get("room_your_team") or "").strip()
        nxt = str(info.get("next_open_pick_team") or "").strip()
        info["is_your_team_on_clock"] = bool(yt and nxt and yt == nxt)

    related_keys = _session_keys_matching(session, *_PICK_ENTRY_KEY_TERMS)
    info["draft_related_session_keys"] = related_keys[:40]
    snapshots: dict[str, str] = {}
    for key in related_keys[:25]:
        snapshots[key] = _preview_session_value(session.get(key))
    info["draft_related_session_snapshots"] = snapshots

    pool = [str(p).strip() for p in (player_names_pool or []) if str(p).strip()]
    if pool and drafted:
        info["drafted_players_found_in_pool"] = [p for p in drafted if p in pool]
    if pool:
        name_hits: dict[str, list[str]] = {}
        for name in drafted[:10]:
            hits = [
                k
                for k in related_keys
                if name.lower() in _preview_session_value(session.get(k)).lower()
            ]
            if hits:
                name_hits[name] = hits[:5]
        if name_hits:
            info["session_keys_mentioning_drafted_players"] = name_hits

    widget_key = session.get("_draft_room_last_widget_key") or editor_widget_key(session)
    if st is not None:
        _, widget_raw = find_widget_state_in_session(st, widget_key)
        info["data_editor_widget_has_edits"] = widget_state_has_edits(widget_raw)
        info["data_editor_key_checked"] = widget_key
    info["last_programmatic_pick_reason"] = session.get("_draft_room_last_programmatic_pick_reason")
    session["_draft_room_pick_entry_diagnostics"] = info
    return info


def render_pick_entry_workflow_debug(
    st: Any,
    session: dict[str, Any],
    *,
    player_names_pool: list[str] | None = None,
) -> None:
    """How picks enter the board — and where session state stores them."""
    info = collect_pick_entry_diagnostics(session, st, player_names_pool=player_names_pool)
    with st.expander("Pick entry workflow debug", expanded=False):
        st.markdown("**How to log picks**")
        for key in (
            "workflow_primary_board_tab",
            "workflow_draft_assistant",
            "workflow_not_board_writes",
        ):
            st.text(info.get(key, ""))
        st.markdown("**Where picks are stored now**")
        for key in (
            "draft_room_table_pick_count",
            "draft_room_table_drafted_players",
            "draft_room_editor_cache_pick_count",
            "draft_room_editor_seed_pick_count",
            "draft_queue",
            "pending_draft_assistant_player",
            "room_your_team",
            "next_open_pick_team",
            "is_your_team_on_clock",
            "data_editor_widget_has_edits",
            "data_editor_key_checked",
            "simulated_draft_room_pick_count",
            "live_draft_board_pick_count",
            "last_programmatic_pick_reason",
        ):
            if key in info and info[key] is not None and info[key] != "" and info[key] != []:
                st.text(f"{key}: {info[key]}")
        st.markdown("**Draft-related session keys**")
        st.text(f"draft_related_session_keys: {info.get('draft_related_session_keys')}")
        for key, preview in (info.get("draft_related_session_snapshots") or {}).items():
            st.text(f"  {key}: {preview}")


def render_quick_draft_status(st: Any, session: dict[str, Any]) -> None:
    """Always-visible quick draft result + trace."""
    trace = session.get("_draft_room_last_quick_draft_trace")
    flash = session.get("_draft_room_quick_draft_flash")
    active_count = int(session.get("_draft_room_active_board_pick_count") or 0)
    table_count = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    with st.container(border=True):
        st.markdown("**Quick draft status**")
        if flash:
            st.success(str(flash))
        elif isinstance(trace, dict) and trace.get("error"):
            st.error(str(trace.get("message") or trace.get("error")))
        st.text(f"draft_room_table_pick_count: {table_count}")
        st.text(f"active_board_pick_count: {active_count}")
        seed = session.get(DRAFT_ROOM_EDITOR_SEED_KEY)
        if is_runtime_table(seed):
            st.text(f"seed_player_non_empty: {column_non_empty_counts(seed).get('Player', 0)}")
        st.markdown("**Last quick draft trace**")
        if not isinstance(trace, dict):
            st.warning("No quick draft trace recorded yet — click Log pick to board to run the traced path.")
            return
        for key in (
            "quick_draft_button_clicked",
            "selected_player",
            "selected_team",
            "target_row_index",
            "target_pick",
            "target_round",
            "before_pick_count",
            "after_pick_count",
            "apply_programmatic_board_update_called",
            "blocked_reason",
            "error",
            "message",
            "quick_draft_selected_player",
            "quick_draft_selected_team",
            "quick_draft_target_row_index",
            "quick_draft_target_pick",
            "updated_row_index",
            "used_fallback_open_row",
        ):
            val = trace.get(key)
            if val is None:
                st.text(f"{key}: (none)")
            else:
                st.text(f"{key}: {val}")


def inspect_widget_state_debug(st: Any, session: dict[str, Any], widget_key: str) -> dict[str, Any]:
    """Raw widget-state probe for Board tab debugging."""
    read_key, raw = find_widget_state_in_session(st, widget_key)
    rendered_key = session.get("_draft_room_last_widget_key") or widget_key
    base = _base_board_for_reconstruction(session)
    info: dict[str, Any] = {
        "actual_widget_key_rendered": rendered_key,
        "actual_widget_key_read": read_key,
        "widget_key_in_session": read_key in getattr(st, "session_state", {}),
        "widget_state_type": type(raw).__name__ if raw is not None else "missing",
        "widget_state_repr_first_1000_chars": repr(raw)[:1000] if raw is not None else "",
        "seed_base_source_key": _seed_base_source_key(session),
        "seed_base_columns": _column_names_list(base),
        "seed_base_row_count": len(base) if is_runtime_table(base) else 0,
        "seed_base_non_empty_by_column": column_non_empty_counts(base),
        "editor_column_order": session.get("_draft_room_editor_column_order"),
    }
    if isinstance(raw, dict):
        info["widget_state_keys"] = sorted(str(k) for k in raw.keys())
        info["widget_state_edited_rows"] = raw.get("edited_rows")
        info["widget_state_added_rows"] = raw.get("added_rows")
        info["widget_state_deleted_rows"] = raw.get("deleted_rows")
        edited = raw.get("edited_rows")
        info["widget_state_edited_row_count"] = len(edited) if isinstance(edited, dict) else 0
        if isinstance(edited, dict) and edited:
            first_row = next(iter(edited.values()), {})
            if isinstance(first_row, dict):
                info["widget_state_edited_column_keys_sample"] = [str(k) for k in first_row.keys()]
    if is_runtime_table(raw):
        info["widget_state_columns"] = [str(c) for c in raw.columns]
        info["widget_state_row_count"] = len(raw)
    elif isinstance(raw, list):
        info["widget_state_row_count"] = len(raw)
    widget_dict = _coerce_data_editor_widget_state(raw)
    if widget_dict is not None:
        reconstructed = reconstruct_board_from_widget_state(widget_dict, base)
        info["widget_reconstructed_pick_count"] = table_pick_count(reconstructed)
        info["widget_reconstructed_columns"] = _column_names_list(reconstructed)
        info["widget_reconstructed_non_empty_by_column"] = column_non_empty_counts(reconstructed)
        info["widget_reconstructed_first_5_rows"] = _table_head_preview(reconstructed, limit=5)
        info["widget_reconstructed_player_column"] = detect_player_column(reconstructed)
    session["_draft_room_widget_state_debug"] = info
    return info


def render_raw_widget_state_debug(st: Any, widget_key: str) -> None:
    """Immediately under the Board editor — raw Streamlit widget state."""
    ss = st.session_state
    info = inspect_widget_state_debug(st, ss, widget_key)
    with st.expander("Raw widget state debug", expanded=True):
        for key in (
            "actual_widget_key_rendered",
            "actual_widget_key_read",
            "widget_key_in_session",
            "widget_state_type",
            "widget_state_repr_first_1000_chars",
            "widget_state_keys",
            "widget_state_edited_column_keys_sample",
            "widget_state_columns",
            "widget_state_row_count",
            "widget_state_edited_row_count",
            "widget_state_edited_rows",
            "widget_state_added_rows",
            "widget_state_deleted_rows",
            "seed_base_source_key",
            "seed_base_columns",
            "seed_base_row_count",
            "seed_base_non_empty_by_column",
            "editor_column_order",
            "widget_reconstructed_pick_count",
            "widget_reconstructed_columns",
            "widget_reconstructed_player_column",
            "widget_reconstructed_non_empty_by_column",
            "widget_reconstructed_first_5_rows",
        ):
            if key in info and info[key] is not None and info[key] != "":
                st.text(f"{key}: {info[key]}")


def _board_from_raw_source(name: str, raw: Any, session: dict[str, Any]) -> tuple[pd.DataFrame | None, str, int]:
    widget_dict = _coerce_data_editor_widget_state(raw)
    if widget_dict is not None:
        if not widget_state_has_edits(raw):
            base = _base_board_for_reconstruction(session)
            count = table_pick_count(base)
            if count > 0:
                return base.copy(), f"draft_room_table_via_seed:{name}", count
            return None, name, 0
        base = _base_board_for_reconstruction(session)
        reconstructed = reconstruct_board_from_widget_state(widget_dict, base)
        count = table_pick_count(reconstructed)
        return reconstructed, f"widget_reconstructed:{name}", count
    if is_runtime_table(raw):
        normalized = normalize_board_table(raw)
        if normalized is not None:
            return normalized, name, table_pick_count(normalized)
    return None, name, 0


def resolve_active_board(
    session: dict[str, Any],
    widget_key: str,
    editor_return: Any = None,
    *,
    st: Any | None = None,
) -> tuple[pd.DataFrame | None, str, int]:
    """
    Pick the board source with the most filled picks.
    Keyed data_editor stores edits as {edited_rows, added_rows, deleted_rows} in session state.
    """
    candidates: list[tuple[str, Any]] = []
    if st is not None:
        read_key, widget_raw = find_widget_state_in_session(st, widget_key)
        if widget_raw is not None:
            candidates.append((read_key, widget_raw))
    for key in _draft_related_session_keys(session):
        if is_board_editor_widget_key(key):
            candidates.append((key, session.get(key)))
    candidates.extend(
        [
            ("editor_return", editor_return),
            (DRAFT_ROOM_EDITOR_CACHE_KEY, session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)),
            (DRAFT_ROOM_TABLE_KEY, session.get(DRAFT_ROOM_TABLE_KEY)),
            (DRAFT_ROOM_EDITOR_SEED_KEY, session.get(DRAFT_ROOM_EDITOR_SEED_KEY)),
        ]
    )
    best_name = ""
    best_table: pd.DataFrame | None = None
    best_count = 0
    seen: set[str] = set()
    for name, raw in candidates:
        if raw is None:
            continue
        dedupe = f"{name}:{type(raw).__name__}:{id(raw)}"
        if dedupe in seen:
            continue
        seen.add(dedupe)
        table, source_name, count = _board_from_raw_source(name, raw, session)
        if table is not None and count > best_count:
            best_count = count
            best_table = table
            best_name = source_name
        elif table is not None and best_table is None and count == 0 and best_count == 0:
            best_table = table
            best_name = source_name
    if best_table is not None:
        session["_draft_room_active_board_source"] = best_name
        session["_draft_room_active_board_pick_count"] = best_count
    return best_table, best_name, best_count


def build_board_debug_report(
    session: dict[str, Any],
    widget_key: str,
    editor_return: Any = None,
    *,
    st: Any | None = None,
) -> dict[str, Any]:
    """Deep Board-tab diagnostics to locate where picks actually live."""
    active, source, pick_count = resolve_active_board(session, widget_key, editor_return, st=st)
    sources: list[dict[str, Any]] = []
    if st is not None:
        ss = getattr(st, "session_state", None)
        if ss is not None:
            sources.append(_source_pick_count(f"widget:{widget_key}", ss.get(widget_key)))
    for key in _draft_related_session_keys(session):
        sources.append(_source_pick_count(f"session:{key}", session.get(key)))
    sources.append(_source_pick_count("editor_return", editor_return))
    report: dict[str, Any] = {
        "widget_key": widget_key,
        "editor_version": session.get(DRAFT_ROOM_EDITOR_VERSION_KEY),
        "draft_related_session_keys": _draft_related_session_keys(session),
        "active_board_source": source,
        "active_board_pick_count": pick_count,
        "widget_state_debug": session.get("_draft_room_widget_state_debug"),
        "active_player_column": detect_player_column(active) if is_runtime_table(active) else None,
        "active_board_columns": [str(c) for c in active.columns] if is_runtime_table(active) else [],
        "active_non_empty_by_column": column_non_empty_counts(active) if is_runtime_table(active) else {},
        "active_first_filled_rows": _table_filled_rows_preview(active),
        "source_pick_counts": sources,
    }
    if is_runtime_table(active):
        report["data_editor_columns"] = [str(c) for c in active.columns]
        report["first_5_non_empty_rows"] = _table_filled_rows_preview(active)
    elif is_runtime_table(editor_return):
        report["data_editor_columns"] = [str(c) for c in editor_return.columns]
        report["first_5_non_empty_rows"] = _table_filled_rows_preview(editor_return)
    session["_draft_room_board_debug_report"] = report
    return report


def render_board_debug_expander(st: Any, widget_key: str, editor_return: Any = None) -> None:
    ss = st.session_state
    inspect_widget_state_debug(st, ss, widget_key)
    report = build_board_debug_report(ss, widget_key, editor_return, st=st)
    with st.expander("Debug Board State", expanded=False):
        st.markdown("**Where picks live**")
        st.text(f"active_board_source: {report.get('active_board_source')}")
        st.text(f"active_board_pick_count: {report.get('active_board_pick_count')}")
        st.text(f"active_player_column: {report.get('active_player_column')}")
        st.text(f"data_editor_columns: {report.get('data_editor_columns')}")
        st.text(f"draft_related_session_keys: {report.get('draft_related_session_keys')}")
        st.markdown("**Non-empty cells by column (active board)**")
        for col, cnt in (report.get("active_non_empty_by_column") or {}).items():
            st.text(f"  {col}: {cnt}")
        st.markdown("**First filled rows**")
        for row in report.get("first_5_non_empty_rows") or []:
            st.text(str(row))
        st.markdown("**All candidate sources**")
        for src in report.get("source_pick_counts") or []:
            st.text(str(src))


def table_picks_fingerprint(table: Any) -> str:
    """Hash only filled pick rows — ignores empty grid structure changes."""
    import hashlib

    records: list[dict[str, Any]] = []
    if is_runtime_table(table):
        player_col = detect_player_column(table) or "Player"
        if player_col in table.columns:
            picked = table[table[player_col].apply(_player_cell_filled)]
            records = _json_safe(picked.to_dict(orient="records"))  # type: ignore[assignment]
    elif is_persisted_table_blob(table):
        for row in table.get("table_records") or []:
            if isinstance(row, dict) and _player_cell_filled(row.get("Player")):
                records.append(_json_safe(row))  # type: ignore[arg-type]
    payload = json.dumps(records, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def table_to_persist_dict(table: Any, *, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"_persist_schema": DRAFT_ROOM_PERSIST_SCHEMA, "_persisted_at": _utc_now_iso()}
    if is_runtime_table(table):
        if table.empty:
            out["table_records"] = []
            out["table_columns"] = []
        else:
            out["table_records"] = _json_safe(table.to_dict(orient="records"))
            out["table_columns"] = [str(c) for c in table.columns]
    elif is_persisted_table_blob(table):
        out["table_records"] = _json_safe(table.get("table_records") or [])
        out["table_columns"] = [str(c) for c in (table.get("table_columns") or [])]
    else:
        out["table_records"] = []
        out["table_columns"] = []
    out["pick_count"] = table_pick_count(out)
    if settings:
        for key in DRAFT_ROOM_SETTINGS_KEYS:
            if key in settings:
                out[key] = _json_safe(settings[key])
    return out


def table_from_persist_dict(data: dict[str, Any] | None) -> pd.DataFrame | None:
    if not isinstance(data, dict):
        return None
    records = data.get("table_records")
    columns = data.get("table_columns")
    if records is None and not is_persisted_table_blob(data):
        return None
    if not records:
        return pd.DataFrame(columns=list(columns or []))
    df = pd.DataFrame(records)
    if columns:
        ordered = [c for c in columns if c in df.columns]
        extras = [c for c in df.columns if c not in ordered]
        df = df[ordered + extras]
    return df


def _draft_room_from_blob(state: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    meta = state.get(DRAFT_ROOM_STATE_KEY)
    meta_picks = table_pick_count(meta) if isinstance(meta, dict) else 0
    cache = state.get(DRAFT_ROOM_EDITOR_CACHE_KEY)
    cache_picks = table_pick_count(cache) if is_runtime_table(cache) else 0
    runtime = state.get(DRAFT_ROOM_TABLE_KEY)
    runtime_picks = table_pick_count(runtime) if is_runtime_table(runtime) else 0
    if cache_picks > meta_picks and is_runtime_table(cache):
        return table_to_persist_dict(cache, settings=_room_settings_from_session(state))
    if runtime_picks > meta_picks and is_runtime_table(runtime):
        return table_to_persist_dict(runtime, settings=_room_settings_from_session(state))
    if isinstance(meta, dict) and meta.get("_persist_schema") == DRAFT_ROOM_PERSIST_SCHEMA:
        return copy.deepcopy(meta)
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            tbl = block.get(DRAFT_ROOM_TABLE_KEY)
            if is_persisted_table_blob(tbl):
                return copy.deepcopy(tbl)
            if is_runtime_table(tbl):
                return table_to_persist_dict(tbl)
    tbl = state.get(DRAFT_ROOM_TABLE_KEY)
    if is_persisted_table_blob(tbl):
        return copy.deepcopy(tbl)
    if is_runtime_table(tbl) and table_pick_count(tbl) > 0:
        return table_to_persist_dict(tbl)
    return None


def draft_room_restore_stats(state: dict[str, Any] | None) -> dict[str, Any]:
    """Pick counts from canonical blob and in-memory board sources (richest wins)."""
    session = state or {}
    blob = _draft_room_from_blob(session)
    blob_picks = table_pick_count(blob) if isinstance(blob, dict) else 0
    runtime_picks = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    cache_picks = table_pick_count(session.get(DRAFT_ROOM_EDITOR_CACHE_KEY))
    pick_count = max(blob_picks, runtime_picks, cache_picks, 0)
    pool_count = len(blob.get("table_records") or []) if isinstance(blob, dict) else 0
    if pool_count == 0:
        table, _, _ = _resolve_richest_draft_board(session)
        if table is not None:
            pool_count = len(table)
    return {
        "has_draft_board": pick_count > 0,
        "pick_count": pick_count,
        "pool_count": pool_count,
    }


def draft_board_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Unified diagnostics: canonical draft board (simulator + live)."""
    from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_restore_stats

    room_stats = draft_room_restore_stats(session)
    live_stats = live_draft_restore_stats(session)
    active_page = str(session.get("active_page") or "")
    source_key = ""
    active_draft_page = ""
    runtime_picks = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    cache_picks = table_pick_count(session.get(DRAFT_ROOM_EDITOR_CACHE_KEY))
    blob_picks = table_pick_count(_draft_room_from_blob(session))
    session_pick_count = max(room_stats["pick_count"], runtime_picks, cache_picks, blob_picks)
    session_has_board = session_pick_count > 0

    canonical_meta = get_canonical_draft_meta(session)
    active_mode = get_active_draft_mode(session)

    if active_mode == ACTIVE_DRAFT_MODE_LIVE and live_stats["has_live_draft_state"]:
        source_key = LIVE_DRAFT_ROOM_KEY
        active_draft_page = "Live Draft Room"
        session_pick_count = max(session_pick_count, live_stats["pick_count"])
        session_has_board = True
    elif session_has_board:
        if blob_picks >= cache_picks and blob_picks >= runtime_picks and blob_picks > 0:
            source_key = DRAFT_ROOM_STATE_KEY
        elif cache_picks >= runtime_picks:
            source_key = DRAFT_ROOM_EDITOR_CACHE_KEY
        else:
            source_key = DRAFT_ROOM_TABLE_KEY
        active_draft_page = DRAFT_ROOM_PAGE_BLOCK
    elif live_stats["pick_count"] > 0 or live_stats["has_live_draft_state"]:
        source_key = LIVE_DRAFT_ROOM_KEY
        active_draft_page = "Live Draft Room"
        session_pick_count = live_stats["pick_count"]
        session_has_board = bool(live_stats["has_live_draft_state"])

    pf = session.get("page_filter_state")
    pf_pages = sorted(str(k) for k in pf.keys()) if isinstance(pf, dict) else []

    return {
        "active_draft_page": active_draft_page or active_page or None,
        "active_draft_mode": active_mode,
        "canonical_draft_meta": canonical_meta,
        "draft_board_source_key": source_key or None,
        "session_has_draft_board": session_has_board,
        "session_pick_count": session_pick_count,
        "draft_room_pick_count": session_pick_count,
        "live_draft_pick_count": live_stats["pick_count"],
        "page_filter_pages": pf_pages,
        "active_page": active_page or None,
    }


def is_draft_room_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(DRAFT_ROOM_DIRTY_KEY))


def mark_draft_room_local_edit(session: dict[str, Any]) -> None:
    session[DRAFT_ROOM_DIRTY_KEY] = True
    session[DRAFT_ROOM_LOCAL_EDIT_TS_KEY] = _utc_now_iso()
    session[SUITE_LOCAL_DIRTY_BASEBALL_KEY] = True


def clear_draft_room_local_edit(session: dict[str, Any]) -> None:
    session.pop(DRAFT_ROOM_DIRTY_KEY, None)
    session.pop(DRAFT_ROOM_LOCAL_EDIT_TS_KEY, None)


def effective_board_pick_count(session: dict[str, Any]) -> int:
    """Best-effort filled-pick count across runtime, cache, blob, and last submit trace."""
    counts = [
        table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)),
        table_pick_count(session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)),
    ]
    blob = _draft_room_from_blob(session)
    if isinstance(blob, dict):
        counts.append(table_pick_count(blob))
    submit = session.get(_BOARD_ASSIGN_SUBMIT_TRACE_KEY)
    if isinstance(submit, dict):
        counts.append(int(submit.get("after_pick_count") or 0))
    return max((int(c) for c in counts if c is not None), default=0)


def sync_board_to_session_keys(
    session: dict[str, Any],
    table: Any,
    *,
    local_edit: bool = True,
    reason: str = "board_sync",
) -> pd.DataFrame:
    """Write board to every session key draft tools and diagnostics read."""
    normalized = normalize_board_table(table) if is_runtime_table(table) else coerce_board_table(table)
    pick_count = table_pick_count(normalized)
    session[DRAFT_ROOM_TABLE_KEY] = normalized.copy()
    session[DRAFT_ROOM_EDITOR_CACHE_KEY] = normalized.copy()
    sync_editor_seed(session, normalized, force_reset=True)
    session["_draft_room_picks_fp"] = table_picks_fingerprint(normalized)
    session.pop("_draft_room_save_fp", None)
    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_MANUAL,
        source=reason,
        pick_count=pick_count,
    )
    blob = write_canonical_draft_room_state(session, normalized, reason=reason, local_edit=local_edit)
    session["local_has_draft_room_board"] = pick_count > 0
    session["local_draft_room_pick_count"] = pick_count
    session["session_pick_count"] = pick_count
    session["_draft_room_active_board_pick_count"] = pick_count
    session["payload_has_draft_board"] = pick_count > 0
    session["cloud_payload_pick_count"] = int(blob.get("pick_count") or pick_count)
    session["_draft_room_canonical_sync_reason"] = reason
    session["_draft_room_canonical_pick_count"] = pick_count
    return normalized


def _room_settings_from_session(session: dict[str, Any]) -> dict[str, Any]:
    return {k: session[k] for k in DRAFT_ROOM_SETTINGS_KEYS if k in session}


def _room_settings_from_blob(state: dict[str, Any]) -> dict[str, Any]:
    settings = {k: state[k] for k in DRAFT_ROOM_SETTINGS_KEYS if k in state}
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            for key in DRAFT_ROOM_SETTINGS_KEYS:
                if key in block and key not in settings:
                    settings[key] = block[key]
    return settings


def _sync_page_filter_draft_room_block(session: dict[str, Any], *, blob: dict[str, Any] | None = None) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(DRAFT_ROOM_PAGE_BLOCK, {})
    if not isinstance(block, dict):
        block = {}
        pf[DRAFT_ROOM_PAGE_BLOCK] = block
    src = blob if isinstance(blob, dict) else _draft_room_from_blob(session) or {}
    if src:
        block[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(src)
    for key in DRAFT_ROOM_SETTINGS_KEYS:
        if key in session:
            block[key] = session[key]


def write_canonical_draft_room_state(
    session: dict[str, Any],
    table: Any,
    *,
    reason: str = "",
    local_edit: bool = False,
) -> dict[str, Any]:
    settings = _room_settings_from_session(session)
    blob = table_to_persist_dict(table, settings=settings)
    blob["last_write_reason"] = reason or None
    meta = get_canonical_draft_meta(session)
    if meta:
        blob["canonical_draft_meta"] = _json_safe(meta)
    session[DRAFT_ROOM_STATE_KEY] = blob
    if is_runtime_table(table):
        session[DRAFT_ROOM_TABLE_KEY] = table
    _sync_page_filter_draft_room_block(session, blob=blob)
    if local_edit:
        mark_draft_room_local_edit(session)
    return blob


def prepare_draft_room_state(session: dict[str, Any]) -> pd.DataFrame:
    """Hydrate runtime draft_room_table from canonical blob without clobbering in-memory picks."""
    richest, rich_count, rich_source = _resolve_richest_draft_board(session)
    submit = session.get(_BOARD_ASSIGN_SUBMIT_TRACE_KEY)
    submit_after = (
        int(submit.get("after_pick_count") or 0) if isinstance(submit, dict) else 0
    )

    runtime = session.get(DRAFT_ROOM_TABLE_KEY)
    if not is_runtime_table(runtime):
        coerced = coerce_board_table(runtime)
        session[DRAFT_ROOM_TABLE_KEY] = coerced
        runtime = coerced
    runtime_picks = table_pick_count(runtime)
    cache = session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)
    cache_picks = table_pick_count(cache) if is_runtime_table(cache) else 0

    prefer_richest = (
        is_draft_room_locally_dirty(session)
        or submit_after > runtime_picks
        or rich_count > runtime_picks
    )
    if prefer_richest and rich_count > 0 and richest is not None:
        blob = _draft_room_from_blob(session)
        if isinstance(blob, dict):
            saved_meta = blob.get("canonical_draft_meta")
            if isinstance(saved_meta, dict):
                session[CANONICAL_DRAFT_META_KEY] = copy.deepcopy(saved_meta)
            # Only restore settings from blob when NOT locally dirty.
            # When dirty, the user just edited a setting widget — restoring from
            # blob would overwrite that edit on the very next rerun.
            if not is_draft_room_locally_dirty(session):
                for key in DRAFT_ROOM_SETTINGS_KEYS:
                    if key in blob:
                        session[key] = blob[key]
        return sync_board_to_session_keys(
            session,
            richest,
            local_edit=is_draft_room_locally_dirty(session) or submit_after > 0,
            reason=f"prepare_richest:{rich_source}",
        )

    if is_draft_room_locally_dirty(session):
        best = cache if cache_picks >= runtime_picks and is_runtime_table(cache) else runtime
        if is_runtime_table(best) and table_pick_count(best) > 0:
            write_canonical_draft_room_state(session, best, reason="dirty_runtime_preserve", local_edit=True)
            session[DRAFT_ROOM_EDITOR_CACHE_KEY] = best.copy()
            sync_editor_seed(session, best, force_reset=True)
            return best
        blob = _draft_room_from_blob(session)
        blob_picks = table_pick_count(blob) if isinstance(blob, dict) else 0
        if isinstance(blob, dict) and blob.get("table_records") is not None and blob_picks > 0:
            restored = table_from_persist_dict(blob)
            if restored is not None:
                clear_draft_room_local_edit(session)
                return apply_restored_board_to_session(session, restored, blob=blob, bump_widget=True)
        if is_runtime_table(best):
            session[DRAFT_ROOM_EDITOR_CACHE_KEY] = best.copy()
            sync_editor_seed(session, best, force_reset=True)
            return best
        return ensure_runtime_draft_board(session)

    blob = _draft_room_from_blob(session)
    blob_picks = table_pick_count(blob) if isinstance(blob, dict) else 0
    if runtime_picks > blob_picks and is_runtime_table(runtime):
        write_canonical_draft_room_state(session, runtime, reason="runtime_wins", local_edit=False)
        session[DRAFT_ROOM_EDITOR_CACHE_KEY] = runtime.copy()
        sync_editor_seed(session, runtime, force_reset=True)
        return runtime
    if cache_picks > blob_picks and is_runtime_table(cache):
        write_canonical_draft_room_state(session, cache, reason="cache_wins", local_edit=False)
        return apply_restored_board_to_session(session, cache, bump_widget=False)

    table = runtime
    if isinstance(blob, dict) and blob.get("table_records") is not None:
        restored = table_from_persist_dict(blob)
        restored_picks = table_pick_count(restored) if restored is not None else 0
        if restored is not None and restored_picks >= runtime_picks:
            for key in DRAFT_ROOM_SETTINGS_KEYS:
                if key in blob:
                    session[key] = blob[key]
            saved_meta = blob.get("canonical_draft_meta")
            if isinstance(saved_meta, dict):
                session[CANONICAL_DRAFT_META_KEY] = copy.deepcopy(saved_meta)
            return apply_restored_board_to_session(session, restored, blob=blob, bump_widget=True)
    if is_runtime_table(table):
        write_canonical_draft_room_state(session, table, reason="session_hydrate", local_edit=False)
        return table
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            legacy = block.get(DRAFT_ROOM_TABLE_KEY)
            if is_persisted_table_blob(legacy) or is_runtime_table(legacy):
                restored = table_from_persist_dict(legacy) if is_persisted_table_blob(legacy) else legacy
                if restored is not None:
                    write_canonical_draft_room_state(session, restored, reason="page_filter_hydrate", local_edit=False)
                    for key in DRAFT_ROOM_SETTINGS_KEYS:
                        if key in block:
                            session[key] = block[key]
                    return apply_restored_board_to_session(session, restored, bump_widget=True)
    return ensure_runtime_draft_board(session)


def _resolve_richest_draft_board(session: dict[str, Any]) -> tuple[pd.DataFrame, int, str]:
    """Pick the board source with the most filled picks (never prefer empty over blob)."""
    best_table: pd.DataFrame | None = None
    best_count = -1
    best_name = "missing"
    for name, raw in (
        ("runtime", session.get(DRAFT_ROOM_TABLE_KEY)),
        ("cache", session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)),
        ("seed", session.get(DRAFT_ROOM_EDITOR_SEED_KEY)),
        ("blob", _draft_room_from_blob(session)),
    ):
        if is_runtime_table(raw):
            table = normalize_board_table(raw)
        elif isinstance(raw, dict) and raw.get("table_records") is not None:
            table = table_from_persist_dict(raw)
        else:
            continue
        if table is None:
            continue
        count = table_pick_count(table)
        if count > best_count:
            best_table = table
            best_count = count
            best_name = name
    if best_table is None:
        best_table = ensure_runtime_draft_board(session)
        best_count = table_pick_count(best_table)
        best_name = "fresh"
    return best_table, best_count, best_name


def sync_draft_room_session_before_save(session: dict[str, Any]) -> None:
    table, pick_count, source = _resolve_richest_draft_board(session)
    session[DRAFT_ROOM_TABLE_KEY] = table.copy()
    session[DRAFT_ROOM_EDITOR_CACHE_KEY] = table.copy()
    session["_draft_room_pre_save_sync_source"] = source
    write_canonical_draft_room_state(
        session,
        table,
        reason="pre_save_sync",
        local_edit=is_draft_room_locally_dirty(session) and pick_count > 0,
    )


def enrich_save_payload_with_draft_room(
    session: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    diag: dict[str, Any] = {
        "payload_has_draft_board": False,
        "cloud_payload_pick_count": 0,
        "enrich_source": "",
    }
    sync_draft_room_session_before_save(session)
    table, pick_count, source = _resolve_richest_draft_board(session)
    blob: dict[str, Any] | None = None
    if pick_count > 0 and table is not None:
        blob = table_to_persist_dict(table, settings=_room_settings_from_session(session))
        diag["enrich_source"] = source
    if not blob or table_pick_count(blob) <= 0:
        blob = _draft_room_from_blob(session) or _draft_room_from_blob(state)
        if blob:
            diag["enrich_source"] = diag.get("enrich_source") or "session_blob"
    if not blob or table_pick_count(blob) <= 0:
        return state, diag

    safe_blob = copy.deepcopy(blob)
    out = copy.deepcopy(state)
    out[DRAFT_ROOM_STATE_KEY] = safe_blob
    out[DRAFT_ROOM_TABLE_KEY] = safe_blob
    meta = get_canonical_draft_meta(session)
    if meta:
        out[CANONICAL_DRAFT_META_KEY] = copy.deepcopy(_json_safe(meta))
        safe_blob["canonical_draft_meta"] = _json_safe(meta)
    pf = out.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        pf = {}
        out["page_filter_state"] = pf
    block = pf.setdefault(DRAFT_ROOM_PAGE_BLOCK, {})
    if isinstance(block, dict):
        block[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(safe_blob)
        for key in DRAFT_ROOM_SETTINGS_KEYS:
            if key in session:
                block[key] = session[key]
    pick_count = int(safe_blob.get("pick_count") or table_pick_count(safe_blob))
    diag["payload_has_draft_board"] = pick_count > 0
    diag["cloud_payload_pick_count"] = pick_count
    session["cloud_payload_has_draft_board"] = diag["payload_has_draft_board"]
    session["cloud_payload_pick_count"] = pick_count
    board_diag = draft_board_diagnostics(session)
    session.update(
        {
            "active_draft_page": board_diag.get("active_draft_page"),
            "draft_board_source_key": board_diag.get("draft_board_source_key"),
            "session_has_draft_board": board_diag.get("session_has_draft_board"),
            "session_pick_count": board_diag.get("session_pick_count"),
            "payload_has_draft_board": diag["payload_has_draft_board"],
        }
    )
    return out, diag


def sanitize_state_dict_for_json(
    state: dict[str, Any],
    *,
    diag: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure persisted full_session has no runtime DataFrames (Supabase uses strict JSON)."""
    report: dict[str, Any] = diag if diag is not None else {}
    report.setdefault("dataframe_keys_in_payload", [])
    report.setdefault("non_json_safe_keys", [])
    report.setdefault("stripped_runtime_keys", [])
    report.setdefault("json_serialization_error_key", "")

    report["payload_pick_count_before_json"] = int(
        draft_room_restore_stats(state).get("pick_count") or 0
    )
    _collect_dataframe_paths(state, "", report["dataframe_keys_in_payload"])

    out = copy.deepcopy(state)
    table = out.get(DRAFT_ROOM_TABLE_KEY)
    blob = out.get(DRAFT_ROOM_STATE_KEY)
    if is_runtime_table(table):
        blob = table_to_persist_dict(table, settings=_room_settings_from_blob(out))
    elif is_persisted_table_blob(table):
        blob = copy.deepcopy(table)
    elif isinstance(blob, dict) and blob.get("table_records") is not None:
        blob = copy.deepcopy(blob)
    elif isinstance(out.get("page_filter_state"), dict):
        block = out["page_filter_state"].get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            pr = block.get(DRAFT_ROOM_TABLE_KEY)
            if is_runtime_table(pr):
                blob = table_to_persist_dict(pr, settings=_room_settings_from_blob(out))
            elif is_persisted_table_blob(pr):
                blob = copy.deepcopy(pr)
    if blob:
        safe_blob = copy.deepcopy(blob)
        out[DRAFT_ROOM_STATE_KEY] = safe_blob
        out[DRAFT_ROOM_TABLE_KEY] = safe_blob
        pf = out.get("page_filter_state")
        if isinstance(pf, dict):
            page_block = pf.setdefault(DRAFT_ROOM_PAGE_BLOCK, {})
            if isinstance(page_block, dict):
                page_block[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(safe_blob)

    runtime_strip_keys = (
        DRAFT_ROOM_EDITOR_CACHE_KEY,
        DRAFT_ROOM_EDITOR_SEED_KEY,
        DRAFT_ROOM_EDITOR_VERSION_KEY,
    )
    for key in runtime_strip_keys:
        if key in out:
            out.pop(key, None)
            report["stripped_runtime_keys"].append(key)

    pf = out.get("page_filter_state")
    if isinstance(pf, dict):
        for page_name, block in pf.items():
            if not isinstance(block, dict):
                continue
            for key in list(block.keys()):
                if key in runtime_strip_keys:
                    block.pop(key, None)
                    report["stripped_runtime_keys"].append(f"page_filter_state.{page_name}.{key}")
                elif key == DRAFT_ROOM_TABLE_KEY and is_runtime_table(block.get(key)):
                    block[key] = copy.deepcopy(
                        table_to_persist_dict(block[key], settings=_room_settings_from_blob(out))
                    )
                elif is_runtime_table(block.get(key)):
                    block.pop(key, None)
                    report["stripped_runtime_keys"].append(f"page_filter_state.{page_name}.{key}")

    out = _deep_convert_runtime_tables(out, report)
    report["payload_pick_count_after_sanitize"] = int(
        draft_room_restore_stats(out).get("pick_count") or 0
    )
    ok, err, offenders = verify_json_serializable(out)
    report["json_serialization_ok"] = ok
    if not ok:
        report["json_serialization_error_key"] = err
        report["non_json_safe_keys"] = offenders
    else:
        report["json_serialization_error_key"] = ""
    return out


def _collect_dataframe_paths(obj: Any, path: str, out: list[str]) -> None:
    if is_runtime_table(obj) or isinstance(obj, pd.DataFrame):
        out.append(path or "<root>")
        return
    if isinstance(obj, dict):
        for key, val in obj.items():
            child = f"{path}.{key}" if path else str(key)
            _collect_dataframe_paths(val, child, out)
    elif isinstance(obj, list):
        for idx, val in enumerate(obj):
            _collect_dataframe_paths(val, f"{path}[{idx}]", out)


def _deep_convert_runtime_tables(obj: Any, report: dict[str, Any]) -> Any:
    if is_runtime_table(obj):
        return table_to_persist_dict(obj)
    if isinstance(obj, pd.DataFrame):
        return _json_safe(obj.to_dict(orient="records"))
    if isinstance(obj, dict):
        converted: dict[str, Any] = {}
        for key, val in obj.items():
            if key in (
                DRAFT_ROOM_EDITOR_CACHE_KEY,
                DRAFT_ROOM_EDITOR_SEED_KEY,
                DRAFT_ROOM_EDITOR_VERSION_KEY,
            ):
                report["stripped_runtime_keys"].append(str(key))
                continue
            converted[key] = _deep_convert_runtime_tables(val, report)
        return converted
    if isinstance(obj, list):
        return [_deep_convert_runtime_tables(val, report) for val in obj]
    if isinstance(obj, tuple):
        return [_deep_convert_runtime_tables(val, report) for val in obj]
    return sanitize_for_json(obj)


def _find_non_json_keys(obj: Any, path: str = "") -> list[str]:
    offenders: list[str] = []
    if is_runtime_table(obj) or isinstance(obj, pd.DataFrame):
        return [path or "<root>"]
    try:
        json.dumps(obj)
        return offenders
    except TypeError:
        pass
    if isinstance(obj, dict):
        for key, val in obj.items():
            child = f"{path}.{key}" if path else str(key)
            offenders.extend(_find_non_json_keys(val, child))
    elif isinstance(obj, list):
        for idx, val in enumerate(obj):
            offenders.extend(_find_non_json_keys(val, f"{path}[{idx}]"))
    else:
        offenders.append(path or "<root>")
    return offenders


def verify_json_serializable(state: dict[str, Any]) -> tuple[bool, str, list[str]]:
    """Strict JSON check (no default=str) — matches Supabase requests encoding."""
    try:
        json.dumps(state)
        return True, "", []
    except TypeError as exc:
        return False, f"{type(exc).__name__}: {exc}", _find_non_json_keys(state)


def read_board_for_save(
    session: dict[str, Any],
    board: Any = None,
    *,
    st: Any | None = None,
    widget_key: str | None = None,
) -> pd.DataFrame | None:
    """Read board for manual save — prefer explicit board, then capture from editor."""
    wkey = widget_key or editor_widget_key(session)
    if is_runtime_table(board) and table_pick_count(board) > 0:
        norm = normalize_board_table(board)
        return (norm if norm is not None else board).copy()
    if st is not None:
        captured, count, _ = capture_board_from_data_editor(session, wkey, board, st=st)
        if count > 0:
            return captured
    active, _, _ = resolve_active_board(session, wkey, board, st=st)
    if is_runtime_table(active) and table_pick_count(active) > 0:
        return active.copy()
    if is_runtime_table(board):
        return board.copy()
    return None


def record_board_editor_diagnostics(
    session: dict[str, Any],
    edited_table: Any,
    *,
    editor_key: str | None = None,
) -> dict[str, Any]:
    """Capture data_editor vs session_state wiring for Developer Mode."""
    if not editor_key:
        editor_key = editor_widget_key(session)
    session_table = session.get(DRAFT_ROOM_TABLE_KEY)
    blob = _draft_room_from_blob(session) or {}
    diag = {
        "data_editor_key": editor_key,
        "data_editor_returned_rows": table_row_count(edited_table),
        "data_editor_returned_pick_count": table_pick_count(edited_table),
        "session_draft_room_table_rows": table_row_count(session_table),
        "session_draft_room_table_pick_count": table_pick_count(session_table),
        "commit_input_pick_count": table_pick_count(edited_table),
        "persisted_pick_count": int(blob.get("pick_count") or table_pick_count(blob)),
        "persisted_rows": table_row_count(blob),
        "picks_fingerprint": table_picks_fingerprint(edited_table),
    }
    session["_draft_room_editor_diagnostics"] = diag
    return diag


def commit_draft_room_table_if_changed(
    st: Any,
    session: dict[str, Any],
    table: Any,
    *,
    reason: str = "board_edit",
    editor_key: str = DRAFT_ROOM_EDITOR_KEY,
) -> dict[str, Any]:
    """Force-save only when filled picks changed — avoids empty-grid autosaves."""
    editor_diag = record_board_editor_diagnostics(session, table, editor_key=editor_key)
    pick_count = table_pick_count(table)
    picks_fp = table_picks_fingerprint(table)
    prev_picks_fp = session.get("_draft_room_picks_fp")
    prev_pick_count = session.get("_draft_room_last_committed_pick_count")

    if (
        reason == "board_edit"
        and prev_picks_fp == picks_fp
        and prev_pick_count == pick_count
        and pick_count > 0
    ):
        trace = {
            "reason": reason,
            "skipped": "picks_unchanged",
            "saved": False,
            **editor_diag,
            **draft_board_diagnostics(session),
        }
        session["_draft_room_last_save_trace"] = trace
        return trace

    if reason == "board_edit" and pick_count == 0:
        if prev_picks_fp is None or prev_picks_fp == picks_fp:
            trace = {
                "reason": reason,
                "skipped": "no_picks_yet",
                "saved": False,
                **editor_diag,
                **draft_board_diagnostics(session),
            }
            session["_draft_room_last_save_trace"] = trace
            return trace

    session["_draft_room_picks_fp"] = picks_fp
    trace = commit_draft_room_table(st, session, table, reason=reason, editor_key=editor_key)
    session["_draft_room_last_committed_pick_count"] = pick_count
    return trace


def commit_draft_room_table(
    st: Any,
    session: dict[str, Any],
    table: Any,
    *,
    reason: str = "board_edit",
    editor_key: str = DRAFT_ROOM_EDITOR_KEY,
) -> dict[str, Any]:
    """Canonical write + force-save after Draft Room Simulator board change."""
    trace: dict[str, Any] = {"reason": reason, "saved": False, "disk": False, "cloud": False, "error": ""}
    import hashlib
    import json

    editor_diag = record_board_editor_diagnostics(session, table, editor_key=editor_key)
    trace.update(editor_diag)

    write_canonical_draft_room_state(session, table, reason=reason, local_edit=True)
    if reason == "live_draft_sync":
        pass
    elif reason not in ("simulator_add_player", "simulator_paste", "reset_canonical_board"):
        set_canonical_draft_meta(
            session,
            mode=ACTIVE_DRAFT_MODE_MANUAL,
            source=reason,
            pick_count=table_pick_count(table),
        )
    blob = _draft_room_from_blob(session) or {}
    trace["persisted_pick_count"] = int(blob.get("pick_count") or table_pick_count(blob))
    trace["persisted_rows"] = table_row_count(blob)
    fp = hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()[:16]
    if session.get("_draft_room_save_fp") == fp and reason in ("board_edit",):
        trace["skipped"] = "blob_unchanged"
        trace.update(draft_board_diagnostics(session))
        session["_draft_room_last_save_trace"] = trace
        return trace
    session["_draft_room_save_fp"] = fp
    board_diag = draft_board_diagnostics(session)
    trace.update(board_diag)
    try:
        from baseball_persistent_state import force_save_baseball_state

        trace["force_save_called"] = True
        trace["force_save_reason"] = reason or session.get("_suite_pending_save_reason") or "draft_room_pick"
        trace["saved"] = bool(force_save_baseball_state(st, reason=reason or "draft_room_pick"))
        trace["disk"] = bool(session.get("_suite_persist_last_save_disk"))
        trace["cloud"] = bool(session.get("_suite_persist_last_save_cloud"))
        trace["saved_pick_count"] = table_pick_count(table)
        trace["payload_has_draft_board"] = bool(session.get("payload_has_draft_board"))
        trace["cloud_payload_pick_count"] = session.get("cloud_payload_pick_count")
        trace["cloud_blocked_reason"] = session.get("_suite_autosave_cloud_blocked_reason")
        if session.get("_suite_persist_last_cloud_error"):
            trace["cloud_write_error"] = str(session.get("_suite_persist_last_cloud_error"))
            trace["error"] = trace["cloud_write_error"]
        elif session.get("_suite_autosave_cloud_blocked_reason"):
            trace["error"] = f"cloud_blocked:{session.get('_suite_autosave_cloud_blocked_reason')}"
        if trace["saved"] and trace["cloud"] and trace.get("payload_has_draft_board"):
            clear_draft_room_local_edit(session)
        if trace.get("saved") and int(trace.get("persisted_pick_count") or 0) > 0 and reason in (
            "manual_save",
            "simulator_add_player",
            "simulator_paste",
        ):
            try:
                from baseball_persistent_state import build_baseball_disk_state

                saved_state = build_baseball_disk_state(st)
                from suite_user_persistence import _lock_fingerprint_after_restore

                _lock_fingerprint_after_restore(st, "baseball", saved_state)
                session["restored_draft_room_pick_count"] = int(trace.get("persisted_pick_count") or 0)
            except Exception:
                pass
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
    session["_draft_room_last_save_trace"] = trace
    return trace


def apply_cloud_draft_room_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            return False
        code = str(
            session.get("active_shared_draft_room_code")
            or state.get("active_shared_draft_room_code")
            or ""
        ).strip()
        if code:
            return False
    except ImportError:
        pass
    if is_draft_room_locally_dirty(session):
        return False
    blob = _draft_room_from_blob(state)
    if not blob or not blob.get("table_records"):
        return False
    restored = table_from_persist_dict(blob)
    if restored is None:
        return False
    skip_team_settings = False
    try:
        from draft_room_context import is_multiplayer_draft_active

        skip_team_settings = bool(
            is_multiplayer_draft_active(session)
            or str(session.get("active_shared_draft_room_code") or state.get("active_shared_draft_room_code") or "").strip()
        )
    except ImportError:
        pass
    for key in DRAFT_ROOM_SETTINGS_KEYS:
        if key in blob:
            if skip_team_settings and key == "room_your_team":
                continue
            session[key] = blob[key]
    apply_restored_board_to_session(session, restored, blob=copy.deepcopy(blob), bump_widget=True)
    session["_draft_room_restore_source"] = "cloud_or_workspace"
    return True


def unified_draft_restore_stats(state: dict[str, Any] | None) -> dict[str, Any]:
    """Combined stats for restore winner (Draft Room Simulator + Live Draft Room)."""
    room = draft_room_restore_stats(state)
    try:
        from live_draft_state import live_draft_restore_stats

        live = live_draft_restore_stats(state)
    except ImportError:
        live = {"has_live_draft_state": False, "pick_count": 0, "pool_count": 0}
    return {
        "has_any_draft": bool(room["pick_count"] > 0 or live.get("pick_count", 0) > 0),
        "draft_room_pick_count": room["pick_count"],
        "live_draft_pick_count": live.get("pick_count", 0),
        "local_has_live_draft_state": live.get("has_live_draft_state", False),
        "local_has_draft_room_board": room["has_draft_board"],
    }


def persist_draft_board_to_storage(
    st: Any,
    session: dict[str, Any],
    table: Any,
    *,
    reason: str = "draft_room_pick",
) -> dict[str, Any]:
    """Write canonical board blob and force-save disk + cloud."""
    board = coerce_board_table(table)
    session[DRAFT_ROOM_TABLE_KEY] = board.copy()
    session[DRAFT_ROOM_EDITOR_CACHE_KEY] = board.copy()
    write_canonical_draft_room_state(session, board, reason=reason, local_edit=True)
    return commit_draft_room_table(st, session, board, reason=reason)


_BOARD_MANUAL_SAVE_TRACE_KEY = "_draft_room_manual_save_result"
MANUAL_SAVE_REQUEST_KEY = "_draft_room_manual_save_requested"
MANUAL_SAVE_BUTTON_KEY = "dr_manual_save_board_v14"


def record_manual_save_button_click(session: dict[str, Any]) -> dict[str, Any]:
    """Stamp session immediately when Save Draft Board Now is clicked."""
    ts = _utc_now_iso()
    stub: dict[str, Any] = {
        "path": "save_draft_board_now",
        "save_button_clicked": True,
        "save_button_timestamp": ts,
        "save_reason": "manual_save_button_click",
        "saved": False,
        "saved_cloud": False,
        "direct_cloud_save_attempted": False,
        "direct_cloud_save_ok": False,
        "cloud_payload_pick_count": session.get("cloud_payload_pick_count"),
    }
    session[_BOARD_MANUAL_SAVE_TRACE_KEY] = stub
    session["_draft_room_last_save_trace"] = stub
    session["save_button_clicked"] = True
    session["save_button_timestamp"] = ts
    session[MANUAL_SAVE_REQUEST_KEY] = True
    return stub


def record_manual_save_error(session: dict[str, Any], exc: BaseException) -> None:
    trace = session.get(_BOARD_MANUAL_SAVE_TRACE_KEY)
    if not isinstance(trace, dict):
        trace = record_manual_save_button_click(session)
    trace["error"] = f"{type(exc).__name__}: {exc}"
    trace["cloud_write_error"] = trace["error"]
    trace["saved"] = False
    trace["saved_cloud"] = False
    session[_BOARD_MANUAL_SAVE_TRACE_KEY] = trace
    session["_draft_room_last_save_trace"] = trace

_MANUAL_SAVE_READBACK_FIELDS = (
    "save_button_clicked",
    "save_button_timestamp",
    "saved_cloud",
    "direct_cloud_save_attempted",
    "direct_cloud_save_ok",
    "cloud_write_mode",
    "cloud_write_error",
    "cloud_blocked_reason",
    "cloud_target_user_id",
    "cloud_target_app_id",
    "cloud_payload_pick_count",
    "payload_pick_count_before_json",
    "payload_pick_count_after_sanitize",
    "dataframe_keys_in_payload",
    "non_json_safe_keys",
    "json_serialization_error_key",
    "supabase_row_pick_count_after_write",
    "supabase_row_updated_at_after_write",
    "cloud_row_count",
    "cloud_row_pick_counts",
    "cloud_timestamp_before",
    "cloud_timestamp_after",
    "cloud_fetch_pick_count",
    "cloud_fetch_updated_at",
    "error",
)


def _format_diag_value(val: Any) -> str:
    if val is None:
        return "—"
    if val is False:
        return "False"
    if val is True:
        return "True"
    if val == "":
        return "—"
    return str(val)


def _deploy_build_label() -> str:
    try:
        from suite_deploy_marker import GIT_BRANCH, GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

        return f"{SUITE_BUILD_LABEL} · {GIT_COMMIT_SHORT} · {GIT_BRANCH}"
    except Exception:
        return "deploy_marker_unavailable"


def render_manual_save_readback_panel(st: Any) -> None:
    """Always-visible Supabase readback panel directly under Save Draft Board Now."""
    ss = st.session_state
    manual = ss.get(_BOARD_MANUAL_SAVE_TRACE_KEY)
    if not isinstance(manual, dict):
        manual = {}
    with st.container(border=True):
        st.markdown("**Manual save — Supabase readback**")
        st.caption(f"deploy_build: {_deploy_build_label()}")
        if manual.get("path") != "save_draft_board_now":
            st.caption("Click **Save Draft Board Now** to populate readback fields.")
        for key in _MANUAL_SAVE_READBACK_FIELDS:
            val = manual.get(key)
            if val is None and key in (
                "cloud_fetch_pick_count",
                "cloud_fetch_updated_at",
                "supabase_row_pick_count_after_write",
                "supabase_row_updated_at_after_write",
                "cloud_row_count",
                "cloud_row_pick_counts",
            ):
                val = ss.get(key)
            st.text(f"{key}: {_format_diag_value(val)}")
        readback = int(manual.get("supabase_row_pick_count_after_write") or ss.get("supabase_row_pick_count_after_write") or 0)
        saved = int(manual.get("saved_pick_count") or ss.get("session_pick_count") or 0)
        if manual.get("save_button_clicked"):
            if manual.get("saved_cloud") and readback >= saved and saved > 0:
                st.success(f"Supabase readback OK: {readback} pick(s) persisted.")
            elif manual.get("direct_cloud_save_attempted"):
                st.warning(
                    "Cloud readback not confirmed. "
                    f"payload={manual.get('cloud_payload_pick_count')} "
                    f"readback={readback} "
                    f"error={manual.get('cloud_write_error') or manual.get('error') or '—'}"
                )


_BOARD_MANUAL_SAVE_FIELDS = (
    "save_button_clicked",
    "save_reason",
    "saved_pick_count",
    "saved_disk",
    "saved_cloud",
    "disk_payload_pick_count",
    "cloud_payload_pick_count",
    "cloud_timestamp_before",
    "cloud_timestamp_after",
    "cloud_write_error",
    "force_save_called",
    "force_save_reason",
    "cloud_blocked_reason",
    "direct_cloud_save_attempted",
    "direct_cloud_save_ok",
    "cloud_write_mode",
    "cloud_target_user_id",
    "cloud_target_app_id",
    "supabase_row_pick_count_after_write",
    "supabase_row_updated_at_after_write",
    "cloud_row_count",
    "cloud_row_pick_counts",
    "cloud_fetch_pick_count",
    "error",
)


def _attach_cloud_boundary_diagnostics(
    trace: dict[str, Any],
    *,
    app_id: str = "baseball",
) -> dict[str, Any]:
    """Merge authoritative Supabase read-back into a save/restore trace."""
    try:
        from suite_cloud_state import read_cloud_persistence_boundary

        boundary = read_cloud_persistence_boundary(app_id)
        trace.update(
            {
                "cloud_target_user_id": boundary.get("cloud_target_user_id"),
                "cloud_target_app_id": boundary.get("cloud_target_app_id"),
                "cloud_fetch_user_id": boundary.get("cloud_fetch_user_id"),
                "cloud_fetch_app_id": boundary.get("cloud_fetch_app_id"),
                "cloud_fetch_attempted": boundary.get("cloud_fetch_attempted"),
                "cloud_fetch_success": boundary.get("cloud_fetch_success"),
                "cloud_fetch_updated_at": boundary.get("cloud_fetch_updated_at"),
                "cloud_fetch_pick_count": boundary.get("cloud_fetch_pick_count"),
                "supabase_row_pick_count_after_write": boundary.get(
                    "supabase_row_pick_count_after_write"
                ),
                "supabase_row_updated_at_after_write": boundary.get(
                    "supabase_row_updated_at_after_write"
                ),
                "cloud_row_count": boundary.get("cloud_row_count"),
                "cloud_row_pick_counts": boundary.get("cloud_row_pick_counts"),
            }
        )
        try:
            from suite_cloud_state import last_cloud_write_meta

            trace["cloud_write_mode"] = last_cloud_write_meta().get("write_mode")
        except ImportError:
            pass
        if boundary.get("cloud_load_error") and not trace.get("cloud_write_error"):
            trace["cloud_readback_error"] = boundary.get("cloud_load_error")
    except Exception as exc:
        trace["cloud_readback_error"] = f"{type(exc).__name__}:{exc}"
    return trace


def _refresh_cloud_draft_room_stats(
    session: dict[str, Any],
    *,
    cloud_ts: str | None = None,
) -> dict[str, Any]:
    """Reload cloud draft-room stats into session after a save attempt."""
    stats: dict[str, Any] = {
        "cloud_has_draft_room_board": False,
        "cloud_draft_room_pick_count": 0,
        "cloud_fetch_updated_at": cloud_ts,
        "cloud_fetch_pick_count": 0,
        "supabase_row_pick_count_after_write": 0,
    }
    try:
        from suite_cloud_state import load_cloud_full_session, read_cloud_persistence_boundary

        boundary = read_cloud_persistence_boundary("baseball")
        stats.update(
            {
                "cloud_fetch_attempted": boundary.get("cloud_fetch_attempted"),
                "cloud_fetch_success": boundary.get("cloud_fetch_success"),
                "cloud_fetch_user_id": boundary.get("cloud_fetch_user_id"),
                "cloud_fetch_app_id": boundary.get("cloud_fetch_app_id"),
                "cloud_fetch_pick_count": int(boundary.get("cloud_fetch_pick_count") or 0),
                "supabase_row_pick_count_after_write": int(
                    boundary.get("supabase_row_pick_count_after_write") or 0
                ),
                "supabase_row_updated_at_after_write": boundary.get(
                    "supabase_row_updated_at_after_write"
                ),
                "cloud_row_count": boundary.get("cloud_row_count"),
                "cloud_row_pick_counts": boundary.get("cloud_row_pick_counts"),
            }
        )
        cloud_state, cloud_updated = load_cloud_full_session("baseball")
        if cloud_ts is None:
            cloud_ts = cloud_updated or stats.get("cloud_fetch_updated_at")
        stats["cloud_fetch_updated_at"] = cloud_ts
        cloud_dr = draft_room_restore_stats(cloud_state)
        stats["cloud_has_draft_room_board"] = bool(cloud_dr.get("has_draft_board"))
        stats["cloud_draft_room_pick_count"] = int(cloud_dr.get("pick_count") or 0)
        if int(stats.get("cloud_fetch_pick_count") or 0) == 0:
            stats["cloud_fetch_pick_count"] = stats["cloud_draft_room_pick_count"]
        if int(stats.get("supabase_row_pick_count_after_write") or 0) == 0:
            stats["supabase_row_pick_count_after_write"] = stats["cloud_draft_room_pick_count"]
    except Exception as exc:
        stats["cloud_refresh_error"] = f"{type(exc).__name__}: {exc}"
    session["cloud_has_draft_room_board"] = stats["cloud_has_draft_room_board"]
    session["cloud_draft_room_pick_count"] = stats["cloud_draft_room_pick_count"]
    session["cloud_fetch_pick_count"] = stats.get("cloud_fetch_pick_count")
    session["supabase_row_pick_count_after_write"] = stats.get("supabase_row_pick_count_after_write")
    if stats.get("cloud_fetch_updated_at"):
        session["cloud_fetch_updated_at"] = stats["cloud_fetch_updated_at"]
        session["_suite_cloud_fetch_updated_at"] = stats["cloud_fetch_updated_at"]
    return stats


def save_draft_board_direct_to_cloud(
    st: Any,
    session: dict[str, Any],
    *,
    board: Any = None,
) -> dict[str, Any]:
    """Direct Supabase write for manual save when force_autosave cloud leg fails."""
    trace: dict[str, Any] = {
        "path": "direct_cloud_save_draft_room",
        "saved_cloud": False,
        "cloud_timestamp_changed": False,
        "cloud_write_error": "",
        "error": "",
        "payload_has_draft_board": False,
        "cloud_payload_pick_count": 0,
    }
    try:
        from suite_storage_config import cloud_storage_enabled

        trace["cloud_storage_enabled"] = cloud_storage_enabled()
    except Exception as exc:
        trace["cloud_storage_enabled"] = False
        trace["error"] = f"config:{type(exc).__name__}:{exc}"
        trace["cloud_write_error"] = trace["error"]
        return trace

    if not trace.get("cloud_storage_enabled"):
        trace["error"] = "cloud_storage_disabled"
        trace["cloud_write_error"] = trace["error"]
        return trace

    try:
        from suite_cloud_state import load_cloud_full_session, save_cloud_full_session_with_result, session_page_summary
        from baseball_persistent_state import build_baseball_disk_state

        cloud_before, ts_before = load_cloud_full_session("baseball")
        trace["cloud_timestamp_before"] = ts_before
        trace["cloud_pick_count_before"] = draft_room_restore_stats(cloud_before).get("pick_count")

        if is_runtime_table(board) and table_pick_count(board) > 0:
            sync_board_to_session_keys(session, board, local_edit=True, reason="direct_cloud_save")
        else:
            sync_draft_room_session_before_save(session)

        session["_suite_pending_save_reason"] = "manual_save_direct_cloud"
        session.pop("_suite_autosave_cloud_blocked_reason", None)
        state = build_baseball_disk_state(st)
        state, enrich_diag = enrich_save_payload_with_draft_room(session, state)
        trace["enrich_source"] = enrich_diag.get("enrich_source")
        trace["payload_has_draft_board"] = bool(enrich_diag.get("payload_has_draft_board"))
        trace["cloud_payload_pick_count"] = int(enrich_diag.get("cloud_payload_pick_count") or 0)
        session["payload_has_draft_board"] = trace["payload_has_draft_board"]
        session["cloud_payload_pick_count"] = trace["cloud_payload_pick_count"]

        if not trace["payload_has_draft_board"]:
            trace["error"] = "payload_missing_draft_board"
            trace["cloud_write_error"] = trace["error"]
            return trace

        page, summary = session_page_summary("baseball", state)
        expected_picks = int(trace.get("cloud_payload_pick_count") or 0)

        serde_diag: dict[str, Any] = {}
        try:
            from live_draft_state import sanitize_state_dict_for_json as sanitize_live_draft

            state = sanitize_live_draft(state)
        except ImportError:
            pass
        state = sanitize_state_dict_for_json(state, diag=serde_diag)
        for key in (
            "json_serialization_error_key",
            "non_json_safe_keys",
            "dataframe_keys_in_payload",
            "payload_pick_count_before_json",
            "payload_pick_count_after_sanitize",
            "json_serialization_ok",
            "stripped_runtime_keys",
        ):
            if key in serde_diag:
                trace[key] = serde_diag[key]

        if serde_diag.get("json_serialization_ok") is False:
            trace["error"] = str(serde_diag.get("json_serialization_error_key") or "json_not_serializable")
            trace["cloud_write_error"] = trace["error"]
            return trace

        ok, cloud_err = save_cloud_full_session_with_result(
            "baseball",
            state,
            page=page,
            summary=summary,
            min_draft_pick_count=expected_picks,
        )
        trace["saved_cloud"] = ok
        trace["cloud_write_error"] = cloud_err or ""
        if cloud_err:
            trace["error"] = cloud_err
            session["_suite_persist_last_cloud_error"] = cloud_err
        else:
            session.pop("_suite_persist_last_cloud_error", None)

        _attach_cloud_boundary_diagnostics(trace)
        cloud_after, ts_after = load_cloud_full_session("baseball")
        trace["cloud_timestamp_after"] = ts_after or trace.get("supabase_row_updated_at_after_write")
        trace["cloud_timestamp_changed"] = bool(
            ts_after
            and trace.get("cloud_timestamp_before")
            and ts_after != trace.get("cloud_timestamp_before")
        )
        trace["cloud_pick_count_after"] = draft_room_restore_stats(cloud_after).get("pick_count")
        if ok:
            session["_suite_persist_last_save_cloud"] = True
            session["_suite_persist_last_save_reason"] = "manual_save_direct_cloud"
            cloud_stats = _refresh_cloud_draft_room_stats(session, cloud_ts=ts_after)
            trace.update(cloud_stats)
            _attach_cloud_boundary_diagnostics(trace)
            readback = int(trace.get("supabase_row_pick_count_after_write") or 0)
            if readback < expected_picks:
                trace["saved_cloud"] = False
                trace["error"] = (
                    f"readback_pick_mismatch:expected={expected_picks} got={readback}"
                )
                trace["cloud_write_error"] = trace["error"]
                session["_suite_persist_last_cloud_error"] = trace["error"]
            elif readback > 0:
                clear_draft_room_local_edit(session)
        else:
            session["_suite_persist_last_save_cloud"] = False
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
        trace["cloud_write_error"] = trace["error"]
    return trace


def save_draft_board_now(
    st: Any,
    session: dict[str, Any],
    *,
    board: Any = None,
    widget_key: str | None = None,
) -> dict[str, Any]:
    """Explicit Board-tab save: editor → draft_room_state → disk + cloud."""
    click_ts = session.get("save_button_timestamp") or _utc_now_iso()
    trace: dict[str, Any] = {
        "path": "save_draft_board_now",
        "save_button_clicked": True,
        "save_button_timestamp": click_ts,
        "save_reason": "manual_save",
        "saved": False,
        "saved_disk": False,
        "saved_cloud": False,
        "saved_pick_count": 0,
        "force_save_called": False,
        "force_save_reason": "",
        "cloud_write_error": "",
        "cloud_blocked_reason": "",
        "direct_cloud_save_attempted": False,
        "direct_cloud_save_ok": False,
        "error": "",
    }
    prior = session.get(_BOARD_MANUAL_SAVE_TRACE_KEY)
    if isinstance(prior, dict):
        trace["save_button_timestamp"] = prior.get("save_button_timestamp") or click_ts
    session[_BOARD_MANUAL_SAVE_TRACE_KEY] = trace
    session["save_button_clicked"] = True
    session["save_button_timestamp"] = trace["save_button_timestamp"]
    try:
        return _save_draft_board_now_impl(st, session, board=board, widget_key=widget_key, trace=trace)
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
        trace["cloud_write_error"] = trace["error"]
        session[_BOARD_MANUAL_SAVE_TRACE_KEY] = trace
        session["_draft_room_last_save_trace"] = trace
        raise


def _save_draft_board_now_impl(
    st: Any,
    session: dict[str, Any],
    *,
    board: Any = None,
    widget_key: str | None = None,
    trace: dict[str, Any],
) -> dict[str, Any]:
    cloud_ts_before = None
    try:
        from suite_cloud_state import load_cloud_full_session

        _, cloud_ts_before = load_cloud_full_session("baseball")
    except Exception as exc:
        trace["cloud_timestamp_before_error"] = f"{type(exc).__name__}: {exc}"
    trace["cloud_timestamp_before"] = cloud_ts_before

    try:
        from suite_user_persistence import _autosave_block_key

        session.pop(_autosave_block_key("baseball"), None)
        session.pop("_suite_autosave_block_reason", None)
    except ImportError:
        pass

    wkey = widget_key or editor_widget_key(session)
    board = read_board_for_save(session, board, st=st, widget_key=wkey)
    if board is None:
        trace["error"] = "editor_state_missing"
        session[_BOARD_MANUAL_SAVE_TRACE_KEY] = trace
        session["_draft_room_last_save_trace"] = trace
        return trace

    pick_count = table_pick_count(board)
    trace["saved_pick_count"] = pick_count
    trace["active_board_source"] = session.get("_draft_room_active_board_source")
    record_board_editor_diagnostics(session, board, editor_key=wkey)
    sync_board_to_session_keys(session, board, local_edit=True, reason="manual_save_prepare")

    save_trace = commit_draft_room_table(st, session, board, reason="manual_save", editor_key=wkey)
    trace.update(save_trace)
    trace["saved_pick_count"] = pick_count
    trace["saved_disk"] = bool(trace.get("disk"))
    trace["saved_cloud"] = bool(trace.get("cloud"))
    trace["save_button_clicked"] = True
    trace["save_reason"] = "manual_save"
    trace["cloud_blocked_reason"] = (
        trace.get("cloud_blocked_reason")
        or session.get("_suite_autosave_cloud_blocked_reason")
        or ""
    )
    trace["cloud_write_error"] = (
        trace.get("cloud_write_error")
        or session.get("_suite_persist_last_cloud_error")
        or ""
    )

    if pick_count > 0:
        trace["direct_cloud_save_attempted"] = True
        direct = save_draft_board_direct_to_cloud(st, session, board=board)
        trace["direct_cloud_save_ok"] = bool(direct.get("saved_cloud"))
        trace["cloud_write_mode"] = direct.get("cloud_write_mode")
        for key in (
            "cloud_target_user_id",
            "cloud_target_app_id",
            "cloud_write_error",
            "cloud_row_count",
            "cloud_row_pick_counts",
            "supabase_row_pick_count_after_write",
            "supabase_row_updated_at_after_write",
            "cloud_fetch_pick_count",
            "cloud_timestamp_after",
            "cloud_timestamp_changed",
            "json_serialization_error_key",
            "non_json_safe_keys",
            "dataframe_keys_in_payload",
            "payload_pick_count_before_json",
            "payload_pick_count_after_sanitize",
        ):
            if direct.get(key) is not None and direct.get(key) != "":
                trace[key] = direct.get(key)
        if direct.get("saved_cloud"):
            trace["saved_cloud"] = True
            trace["cloud"] = True
            trace["saved"] = True
            trace["cloud_payload_pick_count"] = direct.get("cloud_payload_pick_count")
            trace["payload_has_draft_board"] = direct.get("payload_has_draft_board")
            trace.pop("error", None)
            trace.pop("cloud_write_error", None)
            session["_suite_persist_last_save_cloud"] = True
        else:
            trace["saved_cloud"] = False
            trace["cloud"] = False
            if direct.get("error"):
                trace["error"] = direct.get("error")
                trace["cloud_write_error"] = direct.get("cloud_write_error") or direct.get("error")
            session["_suite_persist_last_save_cloud"] = False

    if trace.get("saved") and pick_count > 0:
        sync_editor_seed(session, board, force_reset=True)
        session[DRAFT_ROOM_EDITOR_CACHE_KEY] = board.copy()
        try:
            from suite_user_persistence import _autosave_block_key

            session[_autosave_block_key("baseball")] = True
            session["_suite_autosave_block_reason"] = "post_manual_save"
            session["restored_draft_room_pick_count"] = pick_count
        except ImportError:
            pass

    try:
        from baseball_persistent_state import build_baseball_disk_state

        disk_preview = build_baseball_disk_state(st)
        dr_stats = draft_room_restore_stats(disk_preview)
        trace["disk_payload_pick_count"] = dr_stats.get("pick_count")
        if trace.get("payload_has_draft_board") is None:
            trace["payload_has_draft_board"] = bool(session.get("payload_has_draft_board"))
        if trace.get("cloud_payload_pick_count") is None:
            trace["cloud_payload_pick_count"] = session.get("cloud_payload_pick_count")
    except Exception as exc:
        trace["disk_payload_preview_error"] = f"{type(exc).__name__}: {exc}"

    cloud_stats = _refresh_cloud_draft_room_stats(session)
    trace["cloud_timestamp_after"] = cloud_stats.get("cloud_fetch_updated_at")
    trace["cloud_has_draft_room_board_after"] = cloud_stats.get("cloud_has_draft_room_board")
    trace["cloud_draft_room_pick_count_after"] = cloud_stats.get("cloud_draft_room_pick_count")
    trace["last_save_reason"] = session.get("_suite_persist_last_save_reason")
    _attach_cloud_boundary_diagnostics(trace)

    session[_BOARD_MANUAL_SAVE_TRACE_KEY] = trace
    session["_draft_room_last_save_trace"] = trace
    for key in _MANUAL_SAVE_READBACK_FIELDS:
        if key in trace and trace.get(key) is not None:
            session[key] = trace.get(key)
    return trace


def board_tab_diagnostics(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    """Live Board-tab fields shown directly under the editor."""
    widget_key = session.get("_draft_room_last_widget_key") or editor_widget_key(session)
    capture_dbg = session.get("_draft_room_widget_capture_debug")
    effective_picks = effective_board_pick_count(session)
    if isinstance(capture_dbg, dict):
        active_picks = max(int(capture_dbg.get("capture_pick_count") or 0), effective_picks)
        source = str(capture_dbg.get("capture_source") or "")
    else:
        active_picks = effective_picks
        source = str(session.get("_draft_room_active_board_source") or "")
    editor_diag = session.get("_draft_room_editor_diagnostics")
    trace = session.get("_draft_room_last_save_trace")
    out = {
        "data_editor_key": widget_key,
        "editor_state_exists": effective_picks > 0,
        "editor_version": session.get(DRAFT_ROOM_EDITOR_VERSION_KEY),
        "active_board_source": session.get("_draft_room_active_board_source") or source,
        "data_editor_returned_pick_count": active_picks,
        "commit_input_pick_count": (
            editor_diag.get("commit_input_pick_count") if isinstance(editor_diag, dict) else active_picks
        ),
        "session_pick_count": effective_picks,
        "draft_room_pick_count": effective_picks,
        "payload_has_draft_board": session.get("payload_has_draft_board"),
        "cloud_payload_pick_count": session.get("cloud_payload_pick_count"),
        "restored_draft_room_pick_count": session.get("restored_draft_room_pick_count"),
        "restore_source": session.get("restore_source"),
        "restore_reason": session.get("restore_reason"),
        "local_has_draft_room_board": effective_picks > 0,
        "cloud_has_draft_room_board": session.get("cloud_has_draft_room_board"),
        "cloud_fetch_attempted": session.get("cloud_fetch_attempted"),
        "cloud_fetch_success": session.get("cloud_fetch_success"),
        "cloud_fetch_user_id": session.get("cloud_fetch_user_id"),
        "cloud_fetch_app_id": session.get("cloud_fetch_app_id"),
        "cloud_fetch_pick_count": session.get("cloud_fetch_pick_count"),
        "cloud_fetch_updated_at": session.get("cloud_fetch_updated_at"),
        "supabase_row_pick_count_after_write": session.get("supabase_row_pick_count_after_write"),
        "supabase_row_updated_at_after_write": session.get("supabase_row_updated_at_after_write"),
        "cloud_row_count": session.get("cloud_row_count"),
        "cloud_row_pick_counts": session.get("cloud_row_pick_counts"),
        "deploy_build": _deploy_build_label(),
        "last_draft_room_save_trace": trace if isinstance(trace, dict) else None,
    }
    session["_draft_room_board_tab_diagnostics"] = out
    return out


def render_board_tab_diagnostics(st: Any) -> None:
    """Always-visible Board tab status panel (not dev-mode only)."""
    ss = st.session_state
    diag = board_tab_diagnostics(ss, st=st)
    manual = ss.get(_BOARD_MANUAL_SAVE_TRACE_KEY)
    with st.container(border=True):
        st.markdown("**Board save status**")
        st.caption(f"deploy_build: {diag.get('deploy_build') or _deploy_build_label()}")
        for key in (
            "data_editor_key",
            "editor_state_exists",
            "active_board_source",
            "data_editor_returned_pick_count",
            "commit_input_pick_count",
            "session_pick_count",
            "draft_room_pick_count",
            "payload_has_draft_board",
            "cloud_payload_pick_count",
            "restored_draft_room_pick_count",
            "restore_source",
            "restore_reason",
            "local_has_draft_room_board",
            "cloud_has_draft_room_board",
            "local_draft_room_pick_count",
            "cloud_draft_room_pick_count",
            "cloud_fetch_attempted",
            "cloud_fetch_success",
            "cloud_fetch_user_id",
            "cloud_fetch_app_id",
            "cloud_fetch_pick_count",
            "cloud_fetch_updated_at",
            "supabase_row_pick_count_after_write",
            "supabase_row_updated_at_after_write",
            "cloud_row_count",
            "cloud_row_pick_counts",
            "_suite_autosave_block_kept_pick_loss",
            "_suite_autosave_skipped_draft_room_drop",
        ):
            val = diag.get(key)
            if val is None:
                val = ss.get(key)
            st.text(f"{key}: {_format_diag_value(val)}")
        trace = diag.get("last_draft_room_save_trace")
        if isinstance(trace, dict):
            st.text(f"last_draft_room_save_trace.reason: {trace.get('reason')}")
            st.text(f"last_draft_room_save_trace.saved: {trace.get('saved')}")
            st.text(f"last_draft_room_save_trace.saved_pick_count: {trace.get('saved_pick_count')}")
            st.text(f"last_draft_room_save_trace.session_pick_count: {trace.get('session_pick_count')}")
            st.text(f"last_draft_room_save_trace.saved_disk: {trace.get('saved_disk')}")
            st.text(f"last_draft_room_save_trace.saved_cloud: {trace.get('saved_cloud')}")
            st.text(f"last_draft_room_save_trace.disk_payload_pick_count: {trace.get('disk_payload_pick_count')}")
            st.text(f"last_draft_room_save_trace.cloud_payload_pick_count: {trace.get('cloud_payload_pick_count')}")
            st.text(f"last_draft_room_save_trace.last_save_reason: {trace.get('last_save_reason') or ss.get('_suite_persist_last_save_reason')}")
            st.text(f"last_draft_room_save_trace.error: {trace.get('error') or ''}")
        if isinstance(manual, dict) and manual.get("path") == "save_draft_board_now":
            st.markdown("**Manual save trace (raw)**")
            for key in _BOARD_MANUAL_SAVE_FIELDS:
                st.text(f"{key}: {_format_diag_value(manual.get(key))}")
        active_picks = diag.get("draft_room_pick_count") or diag.get("session_pick_count")
        if active_picks is not None:
            st.text(f"active_board_pick_count: {active_picks}")
        capture_dbg = ss.get("_draft_room_widget_capture_debug")
        if isinstance(capture_dbg, dict):
            st.markdown("**Editor capture (this run)**")
            for key in (
                "widget_key",
                "read_key",
                "widget_state_type",
                "editor_return_type",
                "editor_return_pick_count",
                "widget_reconstructed_pick_count",
                "capture_source",
                "capture_pick_count",
                "edited_rows",
            ):
                val = capture_dbg.get(key)
                if val is not None and val != "":
                    st.text(f"{key}: {val}")
        submit_trace = ss.get("_draft_room_assign_submit_trace")
        if isinstance(submit_trace, dict) and submit_trace.get("assignment_button_clicked"):
            st.markdown("**Assignment submit (last click)**")
            for key in (
                "assignment_button_clicked",
                "selected_pick",
                "selected_player_search_text",
                "selected_player_match",
                "selected_player_official_name",
                "assign_player_to_board_row_called",
                "target_row_index",
                "before_pick_count",
                "after_pick_count",
                "draft_room_state_pick_count",
                "canonical_meta_pick_count",
                "local_has_draft_room_board",
                "error",
                "message",
            ):
                val = submit_trace.get(key)
                if val is not None and val != "":
                    st.text(f"{key}: {val}")


def render_draft_board_diagnostics(st: Any) -> None:
    ss = st.session_state
    board = draft_board_diagnostics(ss)
    trace = ss.get("_draft_room_last_save_trace")
    with st.expander("Draft board save / restore trace", expanded=False):
        st.markdown("**Active draft board**")
        for key, val in board.items():
            st.text(f"{key}: {val}")
        st.text(f"payload_has_draft_board: {ss.get('payload_has_draft_board')}")
        st.text(f"cloud_payload_pick_count: {ss.get('cloud_payload_pick_count')}")
        if isinstance(trace, dict):
            st.markdown("**Last Draft Room save**")
            for key, val in trace.items():
                st.text(f"{key}: {val}")
        editor_diag = ss.get("_draft_room_editor_diagnostics")
        if isinstance(editor_diag, dict):
            st.markdown("**Board editor wiring**")
            for key, val in editor_diag.items():
                st.text(f"{key}: {val}")
        st.text(f"local_has_draft_room_board: {draft_room_restore_stats(ss).get('has_draft_board')}")
        st.text(f"cloud_has_draft_room: {ss.get('cloud_has_draft_room_board')}")


def push_local_draft_room_to_cloud(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Recovery: push Draft Room Simulator board from disk/session to Supabase."""
    trace: dict[str, Any] = {"path": "push_draft_room_to_cloud", "merged_from_disk": False}
    try:
        from suite_user_persistence import _load_raw

        disk_state, _, disk_ts = _load_raw("baseball")
        disk_stats = draft_room_restore_stats(disk_state)
        session_stats = draft_room_restore_stats(session)
        trace["local_disk_updated_at"] = disk_ts
        trace["local_disk_pick_count"] = disk_stats.get("pick_count")
        trace["session_pick_count"] = session_stats.get("pick_count")
        if (
            session_stats.get("pick_count", 0) <= 0
            and disk_stats.get("pick_count", 0) > 0
            and isinstance(disk_state, dict)
        ):
            apply_cloud_draft_room_state_if_allowed(session, disk_state)
            prepare_draft_room_state(session)
            trace["merged_from_disk"] = True
    except Exception as exc:
        trace["disk_merge_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from baseball_persistent_state import force_save_baseball_state

        sync_draft_room_session_before_save(session)
        trace["saved"] = bool(force_save_baseball_state(st, reason="push_draft_room_to_cloud"))
        trace["disk"] = bool(session.get("_suite_persist_last_save_disk"))
        trace["cloud"] = bool(session.get("_suite_persist_last_save_cloud"))
        trace["payload_has_draft_board"] = bool(session.get("payload_has_draft_board"))
        trace["cloud_payload_pick_count"] = session.get("cloud_payload_pick_count")
        if session.get("_suite_persist_last_cloud_error"):
            trace["error"] = str(session.get("_suite_persist_last_cloud_error"))
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
    session["_draft_room_push_local_trace"] = trace
    return trace
