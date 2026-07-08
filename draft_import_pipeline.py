"""Shared uploaded-draft import pipeline for Draft Room and Standings entry points."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from draft_import_validation import (
    build_validated_import_dataframe,
    import_review_ready,
    import_review_ready_for_league,
    render_draft_import_validation_ui,
    validate_imported_draft_df,
)
from draft_player_names import classify_draft_player_import_name

ENTRY_DRAFT_ROOM = "draft_room"
ENTRY_STANDINGS = "standings"

REQUIRED_IMPORT_COLUMNS = ("Round", "Pick", "Team", "Player")

_ENTRY_CONFIG: dict[str, dict[str, str]] = {
    ENTRY_DRAFT_ROOM: {
        "session_key": "_draft_import_review",
        "file_hash_session_key": "draft_room_import_last_processed_hash",
        "apply_label": "Apply validated import to draft board",
        "flash_prefix": "Loaded",
    },
    ENTRY_STANDINGS: {
        "session_key": "_standings_draft_import_review",
        "file_hash_session_key": "_standings_draft_import_last_processed_hash",
        "apply_label": "Apply validated import to Draft Room Simulator board",
        "flash_prefix": "Standings: loaded",
    },
}


def get_entry_config(entry_point: str) -> dict[str, str]:
    """Return session keys and labels for a pipeline entry point."""
    key = str(entry_point or "").strip()
    if key not in _ENTRY_CONFIG:
        raise ValueError(f"Unknown draft import entry point: {entry_point!r}")
    return dict(_ENTRY_CONFIG[key])


def normalize_imported_draft_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize uploaded draft board columns into Round/Pick/Team/Player."""
    out = df.copy()
    rename_map: dict[str, str] = {}
    for col in out.columns:
        lc = str(col).strip().lower()
        if lc in ["team", "owner", "fantasy team", "fantasy_team", "manager"]:
            rename_map[col] = "Team"
        elif lc in ["player", "name", "player name", "player_name", "full name", "fullname"]:
            rename_map[col] = "Player"
        elif lc in ["round", "rd"]:
            rename_map[col] = "Round"
        elif lc in ["pick", "pick number", "pick_number", "overall pick", "overall_pick"]:
            rename_map[col] = "Pick"
    out = out.rename(columns=rename_map)
    if "Team" not in out.columns:
        out["Team"] = ""
    if "Player" not in out.columns:
        out["Player"] = ""
    out["Team"] = out["Team"].astype(str).str.strip()
    out["Player"] = out["Player"].astype(str).str.strip()
    out = out[(out["Team"] != "") & (out["Player"] != "")].copy()
    if "Pick" not in out.columns:
        out["Pick"] = range(1, len(out) + 1)
    out["Pick"] = pd.to_numeric(out["Pick"], errors="coerce")
    out = out.sort_values("Pick", na_position="last").reset_index(drop=True)
    out["Pick"] = range(1, len(out) + 1)
    if "Round" not in out.columns:
        team_count = max(1, out["Team"].nunique())
        out["Round"] = ((out["Pick"] - 1) // team_count) + 1
    out["Round"] = pd.to_numeric(out["Round"], errors="coerce").fillna(1).astype(int)
    return out[["Round", "Pick", "Team", "Player"]]


def read_imported_draft_file(
    uploaded_file: Any,
    *,
    read_table_fn: Callable[[bytes, str], pd.DataFrame],
) -> pd.DataFrame:
    """Read uploaded draft CSV or Excel via the app's cached table reader."""
    name = str(getattr(uploaded_file, "name", "")).lower()
    return read_table_fn(uploaded_file.getvalue(), name)


def import_columns_valid(df: pd.DataFrame) -> bool:
    """True when normalized import has required columns and at least one row."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return False
    return all(col in df.columns for col in REQUIRED_IMPORT_COLUMNS)


def parse_uploaded_draft_file(
    uploaded_file: Any,
    *,
    read_table_fn: Callable[[bytes, str], pd.DataFrame],
) -> tuple[pd.DataFrame, str]:
    """Parse and normalize an upload. Returns (dataframe, error_message)."""
    try:
        raw = read_imported_draft_file(uploaded_file, read_table_fn=read_table_fn)
    except Exception as exc:
        return pd.DataFrame(columns=list(REQUIRED_IMPORT_COLUMNS)), str(exc)
    normalized = normalize_imported_draft_columns(raw)
    if normalized.empty:
        return normalized, "No usable Team/Player rows were found in the uploaded draft."
    if not import_columns_valid(normalized):
        return normalized, "Uploaded draft is missing required columns."
    return normalized, ""


def build_import_review(import_df: pd.DataFrame, pool_df: pd.DataFrame) -> dict[str, Any]:
    """Validate every imported player row against the canonical draft pool."""
    return validate_imported_draft_df(import_df, pool_df)


def apply_validated_import_to_board(
    st: Any,
    session: dict[str, Any],
    validated_df: pd.DataFrame,
    *,
    flash_prefix: str = "Loaded",
    session_key: str = "_draft_import_review",
    remove_drafted_from_queue_fn: Callable[[], None] | None = None,
) -> None:
    """Write a validated import onto the Draft Room Simulator board."""
    from draft_room_state import (
        ACTIVE_DRAFT_MODE_MANUAL,
        persist_draft_board_to_storage,
        set_canonical_draft_meta,
        table_pick_count,
    )

    session["draft_room_table"] = validated_df.copy()
    if remove_drafted_from_queue_fn is not None:
        remove_drafted_from_queue_fn()
    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_MANUAL,
        source="validated_import",
        pick_count=table_pick_count(validated_df),
    )
    persist_draft_board_to_storage(
        st,
        session,
        validated_df,
        reason="validated_import",
    )
    filled = int(validated_df["Player"].astype(str).str.strip().ne("").sum())
    session["workflow_sidebar_flash"] = (
        f"{flash_prefix} {filled} validated pick(s) into the Draft Room."
    )
    session.pop(session_key, None)
    session.pop("_draft_import_file_id", None)
    st.rerun()


def render_validated_draft_import(
    st: Any,
    session: dict[str, Any],
    imported_df: pd.DataFrame,
    pool_df: pd.DataFrame,
    *,
    entry_point: str,
    strict: bool = False,
    show_league_readiness: bool = True,
    remove_drafted_from_queue_fn: Callable[[], None] | None = None,
    render_preview_table_fn: Callable[..., None] | None = None,
) -> None:
    """Shared validation UI + optional board apply for any entry point."""
    config = get_entry_config(entry_point)
    session_key = config["session_key"]
    review = build_import_review(imported_df, pool_df)
    session[session_key] = review

    render_draft_import_validation_ui(
        st,
        review=review,
        pool_df=pool_df,
        session_key=session_key,
        apply_label=config["apply_label"],
        strict=strict,
        show_league_readiness=show_league_readiness,
        on_apply=lambda validated: apply_validated_import_to_board(
            st,
            session,
            validated,
            flash_prefix=config["flash_prefix"],
            session_key=session_key,
            remove_drafted_from_queue_fn=remove_drafted_from_queue_fn,
        ),
    )

    if render_preview_table_fn is not None:
        st.caption("Uploaded draft preview (raw import — not saved until validated):")
        render_preview_table_fn(
            imported_df.head(50),
            key=f"{session_key}_preview",
            file_name="uploaded_draft_preview.csv",
            display_rows=50,
        )


def render_uploaded_draft_import_section(
    st: Any,
    session: dict[str, Any],
    uploaded_file: Any,
    pool_df: pd.DataFrame,
    *,
    entry_point: str,
    read_table_fn: Callable[[bytes, str], pd.DataFrame],
    strict: bool = False,
    show_league_readiness: bool = True,
    remove_drafted_from_queue_fn: Callable[[], None] | None = None,
    render_preview_table_fn: Callable[..., None] | None = None,
    uploaded_filename_session_key: str = "",
) -> None:
    """Full upload → parse → validate pipeline used by Draft Room and Standings."""
    config = get_entry_config(entry_point)
    if uploaded_filename_session_key:
        session[uploaded_filename_session_key] = str(getattr(uploaded_file, "name", "") or "")

    imported_df, parse_error = parse_uploaded_draft_file(
        uploaded_file,
        read_table_fn=read_table_fn,
    )
    if parse_error:
        if imported_df.empty:
            st.warning(parse_error)
        else:
            st.error(parse_error)
        return

    file_hash_key = config.get("file_hash_session_key") or ""
    if file_hash_key:
        import hashlib

        file_sig = hashlib.md5(uploaded_file.getvalue()).hexdigest()[:12]
        if session.get(file_hash_key) != file_sig:
            session[file_hash_key] = file_sig
            session.pop(config["session_key"], None)

    if pool_df.empty:
        st.error("Player pool is empty — cannot validate import names.")
        return

    render_validated_draft_import(
        st,
        session,
        imported_df,
        pool_df,
        entry_point=entry_point,
        strict=strict,
        show_league_readiness=show_league_readiness,
        remove_drafted_from_queue_fn=remove_drafted_from_queue_fn,
        render_preview_table_fn=render_preview_table_fn,
    )


__all__ = [
    "ENTRY_DRAFT_ROOM",
    "ENTRY_STANDINGS",
    "REQUIRED_IMPORT_COLUMNS",
    "apply_validated_import_to_board",
    "build_import_review",
    "build_validated_import_dataframe",
    "classify_draft_player_import_name",
    "get_entry_config",
    "import_columns_valid",
    "import_review_ready",
    "import_review_ready_for_league",
    "normalize_imported_draft_columns",
    "parse_uploaded_draft_file",
    "read_imported_draft_file",
    "render_draft_import_validation_ui",
    "render_uploaded_draft_import_section",
    "render_validated_draft_import",
    "validate_imported_draft_df",
]
