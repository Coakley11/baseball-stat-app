"""Canonical Draft Room Simulator state — JSON-safe persistence for draft_room_table."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


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


def prepare_board_editor_for_render(session: dict[str, Any], canonical_table: Any) -> tuple[pd.DataFrame, str]:
    """Return (initial_df, widget_key) for st.data_editor — never touches widget session key."""
    if not is_runtime_table(canonical_table):
        canonical_table = pd.DataFrame()
    if DRAFT_ROOM_EDITOR_VERSION_KEY not in session:
        session[DRAFT_ROOM_EDITOR_VERSION_KEY] = 0
    sync_editor_seed(session, canonical_table)
    seed = session.get(DRAFT_ROOM_EDITOR_SEED_KEY)
    initial = seed.copy() if is_runtime_table(seed) else canonical_table.copy()
    session["_draft_room_editor_column_order"] = _column_names_list(initial)
    return initial, editor_widget_key(session)


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


def find_widget_state_in_session(st: Any, widget_key: str) -> tuple[str, Any]:
    """Return (actual_key, raw_value) from Streamlit session state."""
    ss = getattr(st, "session_state", None)
    if ss is None:
        return widget_key, None
    if widget_key in ss:
        return widget_key, ss.get(widget_key)
    prefix = f"{DRAFT_ROOM_EDITOR_KEY_PREFIX}_"
    matches = sorted(str(k) for k in ss.keys() if str(k).startswith(prefix))
    if matches:
        last_key = matches[-1]
        return last_key, ss.get(last_key)
    return widget_key, None


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
    with st.expander("Raw widget state debug", expanded=False):
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
        if key.startswith(DRAFT_ROOM_EDITOR_KEY_PREFIX):
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
    blob = _draft_room_from_blob(state or {})
    pick_count = int(blob.get("pick_count") or 0) if isinstance(blob, dict) else 0
    if blob and not pick_count:
        pick_count = table_pick_count(blob)
    return {
        "has_draft_board": pick_count > 0,
        "pick_count": pick_count,
        "pool_count": len(blob.get("table_records") or []) if isinstance(blob, dict) else 0,
    }


def draft_board_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Unified diagnostics: Draft Room Simulator vs Live Draft Room."""
    from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_restore_stats

    room_stats = draft_room_restore_stats(session)
    live_stats = live_draft_restore_stats(session)
    active_page = str(session.get("active_page") or "")
    source_key = ""
    active_draft_page = ""
    runtime_picks = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    cache_picks = table_pick_count(session.get(DRAFT_ROOM_EDITOR_CACHE_KEY))
    session_pick_count = max(room_stats["pick_count"], runtime_picks, cache_picks)
    session_has_board = session_pick_count > 0

    if session_has_board:
        source_key = DRAFT_ROOM_EDITOR_CACHE_KEY if cache_picks >= runtime_picks else DRAFT_ROOM_TABLE_KEY
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
        "draft_board_source_key": source_key or None,
        "session_has_draft_board": session_has_board,
        "session_pick_count": session_pick_count,
        "draft_room_pick_count": room_stats["pick_count"],
        "live_draft_pick_count": live_stats["pick_count"],
        "page_filter_pages": pf_pages,
        "active_page": active_page or None,
    }


def is_draft_room_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(DRAFT_ROOM_DIRTY_KEY))


def mark_draft_room_local_edit(session: dict[str, Any]) -> None:
    session[DRAFT_ROOM_DIRTY_KEY] = True
    session[DRAFT_ROOM_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_draft_room_local_edit(session: dict[str, Any]) -> None:
    session.pop(DRAFT_ROOM_DIRTY_KEY, None)
    session.pop(DRAFT_ROOM_LOCAL_EDIT_TS_KEY, None)


def _room_settings_from_session(session: dict[str, Any]) -> dict[str, Any]:
    return {k: session[k] for k in DRAFT_ROOM_SETTINGS_KEYS if k in session}


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
    session[DRAFT_ROOM_STATE_KEY] = blob
    if is_runtime_table(table):
        session[DRAFT_ROOM_TABLE_KEY] = table
    _sync_page_filter_draft_room_block(session, blob=blob)
    if local_edit:
        mark_draft_room_local_edit(session)
    return blob


def prepare_draft_room_state(session: dict[str, Any]) -> pd.DataFrame | None:
    """Hydrate runtime draft_room_table from canonical blob without clobbering in-memory picks."""
    runtime = session.get(DRAFT_ROOM_TABLE_KEY)
    runtime_picks = table_pick_count(runtime) if is_runtime_table(runtime) else 0
    cache = session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)
    cache_picks = table_pick_count(cache) if is_runtime_table(cache) else 0

    if is_draft_room_locally_dirty(session):
        best = cache if cache_picks >= runtime_picks and is_runtime_table(cache) else runtime
        if is_runtime_table(best) and table_pick_count(best) > 0:
            write_canonical_draft_room_state(session, best, reason="dirty_runtime_preserve", local_edit=True)
            session[DRAFT_ROOM_EDITOR_CACHE_KEY] = best.copy()
            sync_editor_seed(session, best, force_reset=True)
            return best

    blob = _draft_room_from_blob(session)
    blob_picks = table_pick_count(blob) if isinstance(blob, dict) else 0
    if runtime_picks > blob_picks and is_runtime_table(runtime):
        write_canonical_draft_room_state(session, runtime, reason="runtime_wins", local_edit=False)
        session[DRAFT_ROOM_EDITOR_CACHE_KEY] = runtime.copy()
        sync_editor_seed(session, runtime, force_reset=True)
        return runtime
    if cache_picks > blob_picks and is_runtime_table(cache):
        write_canonical_draft_room_state(session, cache, reason="cache_wins", local_edit=False)
        session[DRAFT_ROOM_TABLE_KEY] = cache.copy()
        return cache

    table = runtime
    if isinstance(blob, dict) and blob.get("table_records") is not None:
        restored = table_from_persist_dict(blob)
        if restored is not None:
            for key in DRAFT_ROOM_SETTINGS_KEYS:
                if key in blob:
                    session[key] = blob[key]
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
    return table if is_runtime_table(table) else None


def sync_draft_room_session_before_save(session: dict[str, Any]) -> None:
    table = session.get(DRAFT_ROOM_TABLE_KEY)
    if is_runtime_table(table):
        write_canonical_draft_room_state(
            session,
            table,
            reason="pre_save_sync",
            local_edit=is_draft_room_locally_dirty(session),
        )


def enrich_save_payload_with_draft_room(
    session: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    diag: dict[str, Any] = {
        "payload_has_draft_board": False,
        "cloud_payload_pick_count": 0,
    }
    sync_draft_room_session_before_save(session)
    blob = _draft_room_from_blob(session) or _draft_room_from_blob(state)
    if not blob or not blob.get("table_records"):
        existing = _draft_room_from_blob(state)
        if existing:
            blob = existing
        else:
            return state, diag

    safe_blob = copy.deepcopy(blob)
    out = copy.deepcopy(state)
    out[DRAFT_ROOM_STATE_KEY] = safe_blob
    out[DRAFT_ROOM_TABLE_KEY] = safe_blob
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


def sanitize_state_dict_for_json(state: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(state)
    table = out.get(DRAFT_ROOM_TABLE_KEY)
    blob = out.get(DRAFT_ROOM_STATE_KEY)
    if is_runtime_table(table):
        blob = table_to_persist_dict(table)
    elif is_persisted_table_blob(table):
        blob = copy.deepcopy(table)
    elif isinstance(blob, dict) and blob.get("table_records") is not None:
        blob = copy.deepcopy(blob)
    elif isinstance(out.get("page_filter_state"), dict):
        block = out["page_filter_state"].get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            pr = block.get(DRAFT_ROOM_TABLE_KEY)
            if is_runtime_table(pr):
                blob = table_to_persist_dict(pr)
            elif is_persisted_table_blob(pr):
                blob = copy.deepcopy(pr)
    if blob:
        out[DRAFT_ROOM_STATE_KEY] = copy.deepcopy(blob)
        out[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(blob)
        pf = out.get("page_filter_state")
        if isinstance(pf, dict):
            page_block = pf.setdefault(DRAFT_ROOM_PAGE_BLOCK, {})
            if isinstance(page_block, dict):
                page_block[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(blob)
    return out


def read_board_for_save(
    session: dict[str, Any],
    board: Any = None,
    *,
    st: Any | None = None,
    widget_key: str | None = None,
) -> pd.DataFrame | None:
    """Read board for manual save — prefer widget session state, then render return, then cache."""
    wkey = widget_key or editor_widget_key(session)
    active, _, _ = resolve_active_board(session, wkey, board, st=st)
    if is_runtime_table(active):
        return active.copy()
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
    blob = _draft_room_from_blob(session) or {}
    trace["persisted_pick_count"] = int(blob.get("pick_count") or table_pick_count(blob))
    trace["persisted_rows"] = table_row_count(blob)
    fp = hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()[:16]
    if session.get("_draft_room_save_fp") == fp and reason == "board_edit":
        trace["skipped"] = "blob_unchanged"
        trace.update(draft_board_diagnostics(session))
        session["_draft_room_last_save_trace"] = trace
        return trace
    session["_draft_room_save_fp"] = fp
    board_diag = draft_board_diagnostics(session)
    trace.update(board_diag)
    try:
        from baseball_persistent_state import force_save_baseball_state

        trace["saved"] = bool(force_save_baseball_state(st, reason="draft_room_pick"))
        trace["disk"] = bool(session.get("_suite_persist_last_save_disk"))
        trace["cloud"] = bool(session.get("_suite_persist_last_save_cloud"))
        trace["saved_pick_count"] = table_pick_count(table)
        trace["payload_has_draft_board"] = bool(session.get("payload_has_draft_board"))
        trace["cloud_payload_pick_count"] = session.get("cloud_payload_pick_count")
        if session.get("_suite_persist_last_cloud_error"):
            trace["error"] = str(session.get("_suite_persist_last_cloud_error"))
        elif session.get("_suite_autosave_cloud_blocked_reason"):
            trace["error"] = f"cloud_blocked:{session.get('_suite_autosave_cloud_blocked_reason')}"
        if trace["saved"] and trace["cloud"] and trace.get("payload_has_draft_board"):
            clear_draft_room_local_edit(session)
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
    session["_draft_room_last_save_trace"] = trace
    return trace


def apply_cloud_draft_room_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_draft_room_locally_dirty(session):
        return False
    blob = _draft_room_from_blob(state)
    if not blob or not blob.get("table_records"):
        return False
    restored = table_from_persist_dict(blob)
    if restored is None:
        return False
    for key in DRAFT_ROOM_SETTINGS_KEYS:
        if key in blob:
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


def save_draft_board_now(
    st: Any,
    session: dict[str, Any],
    *,
    board: Any = None,
    widget_key: str | None = None,
) -> dict[str, Any]:
    """Explicit Board-tab save: editor → draft_room_state → disk + cloud."""
    trace: dict[str, Any] = {
        "path": "save_draft_board_now",
        "saved": False,
        "disk": False,
        "cloud": False,
        "saved_pick_count": 0,
        "error": "",
    }
    cloud_ts_before = None
    try:
        from suite_cloud_state import load_cloud_full_session

        _, cloud_ts_before = load_cloud_full_session("baseball")
    except Exception as exc:
        trace["cloud_timestamp_before_error"] = f"{type(exc).__name__}: {exc}"
    trace["cloud_timestamp_before"] = cloud_ts_before

    wkey = widget_key or editor_widget_key(session)
    board = read_board_for_save(session, board, st=st, widget_key=wkey)
    if board is None:
        trace["error"] = "editor_state_missing"
        session["_draft_room_manual_save_result"] = trace
        session["_draft_room_last_save_trace"] = trace
        return trace

    pick_count = table_pick_count(board)
    trace["saved_pick_count"] = pick_count
    trace["active_board_source"] = session.get("_draft_room_active_board_source")
    record_board_editor_diagnostics(session, board, editor_key=wkey)
    session[DRAFT_ROOM_TABLE_KEY] = board.copy()
    session[DRAFT_ROOM_EDITOR_CACHE_KEY] = board.copy()
    session["_draft_room_picks_fp"] = table_picks_fingerprint(board)
    session.pop("_draft_room_save_fp", None)

    save_trace = commit_draft_room_table(st, session, board, reason="manual_save", editor_key=wkey)
    trace.update(save_trace)
    trace["saved_pick_count"] = pick_count
    trace["cloud_timestamp_before"] = cloud_ts_before

    cloud_ts_after = None
    try:
        from suite_cloud_state import load_cloud_full_session

        _, cloud_ts_after = load_cloud_full_session("baseball")
    except Exception as exc:
        trace["cloud_timestamp_after_error"] = f"{type(exc).__name__}: {exc}"
    trace["cloud_timestamp_after"] = cloud_ts_after

    session["_draft_room_manual_save_result"] = trace
    session["_draft_room_last_save_trace"] = trace
    return trace


def board_tab_diagnostics(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    """Live Board-tab fields shown directly under the editor."""
    widget_key = session.get("_draft_room_last_widget_key") or editor_widget_key(session)
    editor_return = session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)
    active, source, active_picks = resolve_active_board(session, widget_key, editor_return, st=st)
    if is_runtime_table(active):
        session[DRAFT_ROOM_EDITOR_CACHE_KEY] = active.copy()
        session[DRAFT_ROOM_TABLE_KEY] = active.copy()
    editor_diag = session.get("_draft_room_editor_diagnostics")
    if not isinstance(editor_diag, dict) and is_runtime_table(active):
        editor_diag = record_board_editor_diagnostics(session, active, editor_key=widget_key)
    board = draft_board_diagnostics(session)
    trace = session.get("_draft_room_last_save_trace")
    out = {
        "data_editor_key": widget_key,
        "editor_state_exists": is_runtime_table(active),
        "editor_version": session.get(DRAFT_ROOM_EDITOR_VERSION_KEY),
        "active_board_source": source,
        "data_editor_returned_pick_count": active_picks,
        "commit_input_pick_count": (
            editor_diag.get("commit_input_pick_count") if isinstance(editor_diag, dict) else active_picks
        ),
        "session_pick_count": board.get("session_pick_count"),
        "draft_room_pick_count": board.get("draft_room_pick_count"),
        "payload_has_draft_board": session.get("payload_has_draft_board"),
        "cloud_payload_pick_count": session.get("cloud_payload_pick_count"),
        "last_draft_room_save_trace": trace if isinstance(trace, dict) else None,
    }
    session["_draft_room_board_tab_diagnostics"] = out
    return out


def render_board_tab_diagnostics(st: Any) -> None:
    """Always-visible Board tab status panel (not dev-mode only)."""
    ss = st.session_state
    diag = board_tab_diagnostics(ss, st=st)
    manual = ss.get("_draft_room_manual_save_result")
    with st.container(border=True):
        st.markdown("**Board save status**")
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
        ):
            st.text(f"{key}: {diag.get(key)}")
        trace = diag.get("last_draft_room_save_trace")
        if isinstance(trace, dict):
            st.text(f"last_draft_room_save_trace.reason: {trace.get('reason')}")
            st.text(f"last_draft_room_save_trace.saved: {trace.get('saved')}")
            st.text(f"last_draft_room_save_trace.saved_pick_count: {trace.get('saved_pick_count')}")
            st.text(f"last_draft_room_save_trace.error: {trace.get('error') or ''}")
        if isinstance(manual, dict) and manual.get("path") == "save_draft_board_now":
            st.text(f"manual_save.cloud_timestamp_before: {manual.get('cloud_timestamp_before')}")
            st.text(f"manual_save.cloud_timestamp_after: {manual.get('cloud_timestamp_after')}")


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
        trace["saved"] = bool(force_save_baseball_state(st, reason="draft_room_pick"))
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
