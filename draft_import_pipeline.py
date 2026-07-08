"""Shared uploaded-draft import pipeline for Draft Room and Standings entry points."""

from __future__ import annotations

from dataclasses import dataclass
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

IMPORT_BLOCK_PLACEMENT_LABEL = "above Board / Rosters / League setup tabs"

REQUIRED_IMPORT_COLUMNS = ("Round", "Pick", "Team", "Player")

_STAGED_BYTES_KEY = "_draft_import_staged_bytes"
_STAGED_FILENAME_KEY = "_draft_import_staged_filename"
_DEBUG_STATUS_KEY = "_draft_import_debug_status"

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


@dataclass(frozen=True)
class StagedUploadFile:
    """Minimal uploaded-file shape backed by session-staged bytes."""

    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def stage_draft_import_upload(session: dict[str, Any], *, widget_key: str) -> None:
    """Persist latest uploader payload so reruns can still parse after widget clears."""
    uploaded = session.get(widget_key)
    if uploaded is None:
        return
    try:
        session[_STAGED_BYTES_KEY] = uploaded.getvalue()
    except Exception:
        session.pop(_STAGED_BYTES_KEY, None)
        return
    session[_STAGED_FILENAME_KEY] = str(getattr(uploaded, "name", "") or "")
    session.pop(_DEBUG_STATUS_KEY, None)


def resolve_uploaded_file_for_import(
    session: dict[str, Any],
    uploaded_file: Any,
    *,
    widget_key: str,
) -> Any | None:
    """Prefer live widget value; fall back to staged bytes captured on upload."""
    if uploaded_file is not None:
        stage_draft_import_upload(session, widget_key=widget_key)
        return uploaded_file
    staged = session.get(_STAGED_BYTES_KEY)
    if isinstance(staged, (bytes, bytearray)) and staged:
        return StagedUploadFile(
            name=str(session.get(_STAGED_FILENAME_KEY) or "uploaded_draft.csv"),
            data=bytes(staged),
        )
    return None


def teams_in_pick_order_from_df(df: pd.DataFrame | None) -> list[str]:
    """Unique team names in first-seen pick order from an import/board dataframe."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    team_col = "Team"
    if team_col not in df.columns:
        if "Fantasy Team" in df.columns:
            team_col = "Fantasy Team"
        else:
            return []
    seen: set[str] = set()
    ordered: list[str] = []
    sort_col = "Pick" if "Pick" in df.columns else None
    rows = df.sort_values(sort_col, kind="stable") if sort_col else df
    for raw in rows[team_col].astype(str).tolist():
        name = str(raw).strip()
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def teams_sorted_from_df(df: pd.DataFrame | None) -> list[str]:
    """Alphabetical unique teams — matches Create Shared League selectbox ordering."""
    return sorted(teams_in_pick_order_from_df(df))


def teams_from_room_settings(session: dict[str, Any]) -> list[str]:
    """Draft Room League setup names (room_team_names) — not used by import pipeline."""
    lines = str(session.get("room_team_names") or "").strip()
    if not lines:
        return []
    return [x.strip() for x in lines.splitlines() if x.strip()]


def teams_from_draft_board(session: dict[str, Any]) -> list[str]:
    """Teams on the live Draft Room board after apply (draft_room_table)."""
    try:
        from draft_room_state import coerce_board_table

        table = coerce_board_table(session.get("draft_room_table"))
    except ImportError:
        table = None
    return teams_in_pick_order_from_df(table)


def teams_for_shared_league_creation(review: dict[str, Any] | None) -> list[str]:
    """Teams offered in Create Shared League — derived from validated import review."""
    if not isinstance(review, dict):
        return []
    import_df = review.get("import_df")
    return teams_sorted_from_df(import_df if isinstance(import_df, pd.DataFrame) else None)


def teams_from_active_league_claim(session: dict[str, Any]) -> list[str]:
    """Teams in the active real_league context roster (post-create claim list)."""
    try:
        from fantasy_league_context import get_active_league_context
    except ImportError:
        return []
    context = get_active_league_context(session, respect_source_priority=False)
    if not isinstance(context, dict) or str(context.get("context_type") or "") != "real_league":
        return []
    rosters = context.get("league_rosters")
    if not isinstance(rosters, dict):
        return []
    return sorted(str(k).strip() for k in rosters.keys() if str(k).strip())


def build_import_board_state_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Runtime vs persisted pick counts — surfaces richest-restore clobber risks."""
    try:
        from draft_room_state import (
            DRAFT_ROOM_EDITOR_CACHE_KEY,
            _draft_room_from_blob,
            coerce_board_table,
            draft_room_board_authority_active,
            is_runtime_table,
            table_pick_count,
        )
    except ImportError:
        return {}

    runtime = coerce_board_table(session.get("draft_room_table"))
    blob = _draft_room_from_blob(session)
    cache = session.get(DRAFT_ROOM_EDITOR_CACHE_KEY)
    runtime_picks = table_pick_count(runtime)
    blob_picks = table_pick_count(blob) if isinstance(blob, dict) else 0
    cache_picks = table_pick_count(cache) if is_runtime_table(cache) else 0
    authority = draft_room_board_authority_active(session)
    return {
        "runtime_pick_count": runtime_picks,
        "blob_pick_count": blob_picks,
        "cache_pick_count": cache_picks,
        "board_authority": authority,
        "richest_restore_risk": max(blob_picks, cache_picks) > runtime_picks,
    }


def format_team_name_list(teams: list[str]) -> str:
    if not teams:
        return "[]"
    return "[" + ", ".join(teams) + "]"


def build_import_team_name_diagnostics(
    session: dict[str, Any],
    *,
    review: dict[str, Any] | None = None,
    parsed_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compare team-name sources across CSV parse, board, settings, and league creation."""
    import_df = None
    if isinstance(review, dict):
        candidate = review.get("import_df")
        if isinstance(candidate, pd.DataFrame):
            import_df = candidate
    if import_df is None and isinstance(parsed_df, pd.DataFrame):
        import_df = parsed_df

    parsed_teams = teams_in_pick_order_from_df(import_df)
    room_teams = teams_from_room_settings(session)
    board_teams = teams_from_draft_board(session)
    shared_league_teams = teams_for_shared_league_creation(review)
    claim_teams = teams_from_active_league_claim(session)

    board_applied = bool(board_teams)
    league_created = bool(claim_teams)

    return {
        "parsed_csv_teams": parsed_teams,
        "draft_room_settings_teams": room_teams,
        "board_teams": board_teams,
        "shared_league_teams": shared_league_teams,
        "shared_league_claim_teams": claim_teams,
        "board_applied": board_applied,
        "league_created": league_created,
        "parsed_matches_board": parsed_teams == board_teams if board_applied else None,
        "parsed_matches_shared_league": parsed_teams == shared_league_teams if shared_league_teams else None,
        "parsed_matches_room_settings": parsed_teams == room_teams if room_teams else None,
        "shared_league_matches_claim": shared_league_teams == claim_teams if league_created else None,
    }


def render_import_team_name_diagnostics_panel(
    st: Any,
    session: dict[str, Any],
    *,
    review: dict[str, Any] | None = None,
    parsed_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Show which team-name source feeds each import workflow step."""
    diag = build_import_team_name_diagnostics(session, review=review, parsed_df=parsed_df)
    if not (
        diag.get("parsed_csv_teams")
        or diag.get("draft_room_settings_teams")
        or diag.get("board_teams")
        or diag.get("shared_league_teams")
        or diag.get("shared_league_claim_teams")
    ):
        return diag

    with st.expander("Import team name sources", expanded=True):
        st.caption(
            "Use this panel to see whether team names come from the CSV, Draft Room League setup, "
            "the applied board, or shared-league creation."
        )
        st.markdown(
            f"**Parsed CSV teams:** `{format_team_name_list(diag.get('parsed_csv_teams') or [])}`"
        )
        st.markdown(
            "**Draft Room settings (room_team_names):** "
            f"`{format_team_name_list(diag.get('draft_room_settings_teams') or [])}`"
        )
        if diag.get("board_applied"):
            st.markdown(
                f"**Board teams (draft_room_table after apply):** "
                f"`{format_team_name_list(diag.get('board_teams') or [])}`"
            )
        else:
            st.markdown("**Board teams (draft_room_table after apply):** `(not applied yet)`")

        if diag.get("shared_league_teams"):
            st.markdown(
                "**Create Shared League teams:** "
                f"`{format_team_name_list(diag.get('shared_league_teams') or [])}`"
            )
        else:
            st.markdown("**Create Shared League teams:** `(validation review not ready)`")

        if diag.get("league_created"):
            st.markdown(
                "**Shared League claim teams:** "
                f"`{format_team_name_list(diag.get('shared_league_claim_teams') or [])}`"
            )
        else:
            st.markdown("**Shared League claim teams:** `(league not created yet)`")

        parsed = diag.get("parsed_csv_teams") or []
        room = diag.get("draft_room_settings_teams") or []
        board = diag.get("board_teams") or []
        shared = diag.get("shared_league_teams") or []
        claim = diag.get("shared_league_claim_teams") or []

        if room and parsed and parsed != room:
            st.info(
                "Draft Room League setup names differ from the parsed CSV. "
                "Import validation and Create Shared League use **CSV teams**, not `room_team_names`."
            )
        if diag.get("board_applied") and parsed and parsed != board:
            st.warning(
                "Board teams differ from the parsed CSV. The board may have been edited separately "
                "or not refreshed from the latest validated import."
            )
        if shared and parsed and parsed != shared:
            st.warning("Create Shared League team list differs from parsed CSV teams.")
        if diag.get("league_created") and shared and shared != claim:
            st.warning(
                "Active league claim teams differ from the Create Shared League team list."
            )
        if (
            parsed
            and diag.get("board_applied")
            and diag.get("parsed_matches_board")
            and (not shared or diag.get("parsed_matches_shared_league"))
        ):
            st.success("Parsed CSV team names match the board and shared-league team lists.")

        board_diag = build_import_board_state_diagnostics(session)
        if board_diag:
            st.markdown(
                "**Board pick counts:** "
                f"runtime={int(board_diag.get('runtime_pick_count') or 0)}, "
                f"blob={int(board_diag.get('blob_pick_count') or 0)}, "
                f"cache={int(board_diag.get('cache_pick_count') or 0)}"
            )
            auth = board_diag.get("board_authority")
            if isinstance(auth, dict) and auth.get("reason"):
                st.caption(
                    f"Board authority pin: `{auth.get('reason')}` "
                    f"({int(auth.get('pick_count') or 0)} pick(s))"
                )
            if board_diag.get("richest_restore_risk"):
                st.warning(
                    "Persisted board/cache has more picks than the runtime table. "
                    "Draft Room prepare logic may restore stale picks unless import apply pinned board authority."
                )

    session["_draft_import_team_name_diag"] = diag
    return diag


def _unresolved_player_count(review: dict[str, Any] | None) -> int:
    if not isinstance(review, dict):
        return 0
    count = 0
    for row in review.get("rows") or []:
        if row.get("status") == "empty":
            continue
        if row.get("skip"):
            continue
        if str(row.get("resolved_canonical") or "").strip():
            continue
        if row.get("status") == "exact":
            continue
        count += 1
    return count


def build_draft_import_debug_status(
    session: dict[str, Any],
    *,
    entry_point: str,
    uploaded_file: Any,
    widget_key: str,
    import_block_entered: bool = False,
    pipeline_called: bool = False,
    raw_df: pd.DataFrame | None = None,
    parsed_df: pd.DataFrame | None = None,
    parse_error: str = "",
    review: dict[str, Any] | None = None,
    pool_size: int = 0,
    layout_label: str = IMPORT_BLOCK_PLACEMENT_LABEL,
) -> dict[str, Any]:
    config = get_entry_config(entry_point)
    session_key = config["session_key"]
    resolved = resolve_uploaded_file_for_import(session, uploaded_file, widget_key=widget_key)
    raw_columns: list[str] = []
    if isinstance(raw_df, pd.DataFrame):
        raw_columns = [str(c) for c in raw_df.columns.tolist()]
    status = {
        "entry_point": entry_point,
        "layout_label": layout_label,
        "import_block_entered": bool(import_block_entered),
        "render_uploaded_draft_import_section_called": bool(pipeline_called),
        "uploaded_file_present": resolved is not None,
        "widget_uploaded_file_present": uploaded_file is not None,
        "staged_bytes_present": bool(session.get(_STAGED_BYTES_KEY)),
        "uploaded_filename": str(
            getattr(resolved, "name", None)
            or session.get(_STAGED_FILENAME_KEY)
            or session.get("draft_room_import_uploaded_filename")
            or ""
        ),
        "detected_columns": raw_columns,
        "parsed_row_count": int(len(parsed_df)) if isinstance(parsed_df, pd.DataFrame) else 0,
        "parse_error": str(parse_error or ""),
        "validation_review_created": bool(isinstance(review, dict) and review.get("rows")),
        "unresolved_player_count": _unresolved_player_count(review),
        "session_key_used_for_review": session_key,
        "review_row_count": len((review or {}).get("rows") or []),
        "pool_size": int(pool_size or 0),
        "session_has_review": bool(isinstance(session.get(session_key), dict) and session.get(session_key, {}).get("rows")),
    }
    session[_DEBUG_STATUS_KEY] = status
    return status


def render_draft_import_debug_panel(st: Any, status: dict[str, Any]) -> None:
    """Always-visible import pipeline diagnostics for deploy troubleshooting."""
    with st.expander("Import pipeline status", expanded=True):
        st.markdown(
            f"**Placement:** {status.get('layout_label') or IMPORT_BLOCK_PLACEMENT_LABEL}"
        )
        st.markdown(f"1. **uploaded_file is present:** {'yes' if status.get('uploaded_file_present') else 'no'}")
        st.markdown(f"2. **uploaded filename:** `{status.get('uploaded_filename') or '—'}`")
        cols = status.get("detected_columns") or []
        st.markdown(f"3. **detected columns:** `{', '.join(cols) if cols else '—'}`")
        st.markdown(f"4. **parsed row count:** {int(status.get('parsed_row_count') or 0)}")
        st.markdown(
            f"5. **validation review created:** {'yes' if status.get('validation_review_created') else 'no'}"
        )
        st.markdown(f"6. **unresolved player count:** {int(status.get('unresolved_player_count') or 0)}")
        st.markdown(f"7. **session key used for review:** `{status.get('session_key_used_for_review') or '—'}`")
        st.markdown(
            "8. **render_uploaded_draft_import_section called:** "
            f"{'yes' if status.get('render_uploaded_draft_import_section_called') else 'no'}"
        )
        st.caption(
            "Widget file present: "
            f"{'yes' if status.get('widget_uploaded_file_present') else 'no'} · "
            "Staged bytes present: "
            f"{'yes' if status.get('staged_bytes_present') else 'no'} · "
            f"Pool size: {int(status.get('pool_size') or 0)} · "
            f"Session review cached: {'yes' if status.get('session_has_review') else 'no'}"
        )
        parse_error = str(status.get("parse_error") or "").strip()
        if parse_error:
            st.warning(parse_error)


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
    raw_columns: list[str] = []
    try:
        raw = read_imported_draft_file(uploaded_file, read_table_fn=read_table_fn)
        raw_columns = [str(c) for c in raw.columns.tolist()]
    except Exception as exc:
        return pd.DataFrame(columns=list(REQUIRED_IMPORT_COLUMNS)), str(exc)
    normalized = normalize_imported_draft_columns(raw)
    if normalized.empty:
        cols = ", ".join(raw_columns[:12]) if raw_columns else "(none detected)"
        return (
            normalized,
            "No usable Team/Player rows were found in the uploaded draft. "
            f"Detected columns: {cols}. Expected at least Team/Owner and Player/Name columns.",
        )
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
    rerun: bool = True,
) -> None:
    """Replace the Draft Room board with a validated import (never merge with stale picks)."""
    from draft_room_state import (
        ACTIVE_DRAFT_MODE_MANUAL,
        DRAFT_ROOM_EDITOR_SEED_KEY,
        bump_editor_version,
        coerce_board_table,
        mark_draft_room_board_authority,
        persist_draft_board_to_storage,
        set_canonical_draft_meta,
        sync_board_to_session_keys,
        table_pick_count,
    )

    board = coerce_board_table(validated_df)
    pick_count = table_pick_count(board)

    # Purge stale editor/sync artifacts so _resolve_richest_draft_board cannot resurrect old picks.
    session.pop(DRAFT_ROOM_EDITOR_SEED_KEY, None)
    session.pop("draft_room_board_editor_seed", None)
    session.pop("draft_room_board_editor_cache", None)
    session.pop("_draft_room_skip_editor_resolve_clobber", None)
    session.pop("_draft_room_assign_submit_trace", None)

    sync_board_to_session_keys(session, board, local_edit=True, reason="validated_import")
    bump_editor_version(session)
    mark_draft_room_board_authority(session, pick_count=pick_count, reason="validated_import")
    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_MANUAL,
        source="validated_import",
        pick_count=pick_count,
    )

    try:
        from draft_actions import _clear_ami_draft_cache

        _clear_ami_draft_cache(session)
    except ImportError:
        pass

    if remove_drafted_from_queue_fn is not None:
        remove_drafted_from_queue_fn()

    persist_draft_board_to_storage(
        st,
        session,
        board,
        reason="validated_import",
    )
    filled = int(board["Player"].astype(str).str.strip().ne("").sum()) if "Player" in board.columns else pick_count
    session["workflow_sidebar_flash"] = (
        f"{flash_prefix} {filled} validated pick(s) into the Draft Room. "
        "Previous board picks were replaced."
    )
    session.pop(session_key, None)
    session.pop("_draft_import_file_id", None)
    session.pop(_STAGED_BYTES_KEY, None)
    session.pop(_STAGED_FILENAME_KEY, None)
    if rerun:
        st.rerun()


def render_shared_league_creation_panel(
    st: Any,
    session: dict[str, Any],
    review: dict[str, Any],
    pool_df: pd.DataFrame,
    *,
    session_key: str,
    entry_point: str,
    remove_drafted_from_queue_fn: Callable[[], None] | None = None,
) -> None:
    """Create real_league from a fully validated import review (strict gate)."""
    if not import_review_ready_for_league(review, pool_df):
        return

    import_df = review.get("import_df")
    if not isinstance(import_df, pd.DataFrame) or import_df.empty:
        return

    teams = sorted({str(t).strip() for t in import_df["Team"].astype(str).tolist() if str(t).strip()})
    if not teams:
        return

    default_league_name = str(session.get("draft_room_import_uploaded_filename") or "").strip()
    if default_league_name.lower().endswith((".csv", ".xlsx", ".xls")):
        default_league_name = default_league_name.rsplit(".", 1)[0]
    if not default_league_name:
        default_league_name = f"Imported {len(teams)}-Team League"

    with st.expander("Create shared league from validated import", expanded=True):
        st.caption(
            "All players are resolved. Save as a shared league, claim your team, "
            "and add the import to Saved Drafts as your Active League."
        )
        league_name = st.text_input(
            "League name",
            value=default_league_name,
            key=f"{session_key}_shared_league_name",
        )
        my_team = st.selectbox(
            "Which team is yours?",
            teams,
            key=f"{session_key}_shared_league_team",
        )
        if st.button(
            "Create Shared League",
            key=f"{session_key}_create_shared_league",
            type="primary",
        ):
            if not import_review_ready_for_league(review, pool_df):
                st.error("Resolve every imported player before creating a shared league.")
                return
            validated = build_validated_import_dataframe(review)
            try:
                from fantasy_league_context import save_imported_league_context

                config = get_entry_config(entry_point)
                apply_validated_import_to_board(
                    st,
                    session,
                    validated,
                    flash_prefix=config["flash_prefix"],
                    session_key=session_key,
                    remove_drafted_from_queue_fn=remove_drafted_from_queue_fn,
                    rerun=False,
                )
                _entry, context = save_imported_league_context(
                    session,
                    validated,
                    my_team_name=my_team,
                    draft_name=str(league_name or default_league_name).strip(),
                    league_name=str(league_name or default_league_name).strip(),
                    assign_team=True,
                )
                league_id = str((context.get("metadata") or {}).get("league_id") or "").strip()
                session["workflow_sidebar_flash"] = (
                    f"Created shared league **{league_name}** and claimed **{my_team}**."
                    + (f" League ID: `{league_id}`." if league_id else "")
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not create shared league: {exc}")


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

    render_import_team_name_diagnostics_panel(
        st,
        session,
        review=review,
        parsed_df=imported_df,
    )

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

    live_review = session.get(session_key) or review
    render_shared_league_creation_panel(
        st,
        session,
        live_review,
        pool_df,
        session_key=session_key,
        entry_point=entry_point,
        remove_drafted_from_queue_fn=remove_drafted_from_queue_fn,
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
    widget_key: str = "",
    layout_label: str = IMPORT_BLOCK_PLACEMENT_LABEL,
) -> dict[str, Any]:
    """Full upload → parse → validate pipeline used by Draft Room and Standings."""
    config = get_entry_config(entry_point)
    session_key = config["session_key"]
    raw_df: pd.DataFrame | None = None
    parsed_df: pd.DataFrame | None = None
    parse_error = ""
    review: dict[str, Any] | None = None

    if uploaded_filename_session_key and uploaded_file is not None:
        session[uploaded_filename_session_key] = str(getattr(uploaded_file, "name", "") or "")

    try:
        raw_df = read_imported_draft_file(uploaded_file, read_table_fn=read_table_fn)
    except Exception as exc:
        parse_error = str(exc)
        status = build_draft_import_debug_status(
            session,
            entry_point=entry_point,
            uploaded_file=uploaded_file,
            widget_key=widget_key,
            import_block_entered=True,
            pipeline_called=True,
            raw_df=raw_df,
            parsed_df=parsed_df,
            parse_error=parse_error,
            review=review,
            pool_size=len(pool_df) if isinstance(pool_df, pd.DataFrame) else 0,
            layout_label=layout_label,
        )
        render_draft_import_debug_panel(st, status)
        st.error(f"Could not read uploaded draft file: {parse_error}")
        return status

    parsed_df, parse_error = parse_uploaded_draft_file(
        uploaded_file,
        read_table_fn=read_table_fn,
    )
    if parse_error:
        status = build_draft_import_debug_status(
            session,
            entry_point=entry_point,
            uploaded_file=uploaded_file,
            widget_key=widget_key,
            import_block_entered=True,
            pipeline_called=True,
            raw_df=raw_df,
            parsed_df=parsed_df,
            parse_error=parse_error,
            review=review,
            pool_size=len(pool_df) if isinstance(pool_df, pd.DataFrame) else 0,
            layout_label=layout_label,
        )
        render_draft_import_debug_panel(st, status)
        if parsed_df is None or parsed_df.empty:
            st.warning(parse_error)
        else:
            st.error(parse_error)
        return status

    file_hash_key = config.get("file_hash_session_key") or ""
    if file_hash_key:
        import hashlib

        file_sig = hashlib.md5(uploaded_file.getvalue()).hexdigest()[:12]
        if session.get(file_hash_key) != file_sig:
            session[file_hash_key] = file_sig
            session.pop(config["session_key"], None)

    if pool_df.empty:
        status = build_draft_import_debug_status(
            session,
            entry_point=entry_point,
            uploaded_file=uploaded_file,
            widget_key=widget_key,
            import_block_entered=True,
            pipeline_called=True,
            raw_df=raw_df,
            parsed_df=parsed_df,
            parse_error="Player pool is empty — cannot validate import names.",
            review=review,
            pool_size=0,
            layout_label=layout_label,
        )
        render_draft_import_debug_panel(st, status)
        st.error("Player pool is empty — cannot validate import names.")
        return status

    render_validated_draft_import(
        st,
        session,
        parsed_df,
        pool_df,
        entry_point=entry_point,
        strict=strict,
        show_league_readiness=show_league_readiness,
        remove_drafted_from_queue_fn=remove_drafted_from_queue_fn,
        render_preview_table_fn=render_preview_table_fn,
    )
    review = session.get(session_key)
    status = build_draft_import_debug_status(
        session,
        entry_point=entry_point,
        uploaded_file=uploaded_file,
        widget_key=widget_key,
        import_block_entered=True,
        pipeline_called=True,
        raw_df=raw_df,
        parsed_df=parsed_df,
        parse_error="",
        review=review if isinstance(review, dict) else None,
        pool_size=len(pool_df) if isinstance(pool_df, pd.DataFrame) else 0,
        layout_label=layout_label,
    )
    render_draft_import_debug_panel(st, status)
    return status


def render_import_pending_banner(st: Any, session: dict[str, Any]) -> None:
    """Surface in-progress import review above tabbed layouts (Streamlit resets to tab 1 on rerun)."""
    review = session.get("_draft_import_review") or session.get("_standings_draft_import_review")
    if not isinstance(review, dict) or not review.get("rows"):
        return
    summary = review.get("summary") or {}
    exact = int(summary.get("exact") or 0)
    needs = int(summary.get("close") or 0) + int(summary.get("ambiguous") or 0) + int(summary.get("invalid") or 0)
    st.info(
        f"**Draft import ready for review** — {exact} exact match(es), {needs} row(s) need confirmation. "
        "Use the **Import existing draft** section below to validate names, apply to the board, "
        "or create a shared league."
    )


def render_draft_room_import_block(
    st: Any,
    session: dict[str, Any],
    *,
    read_table_fn: Callable[[bytes, str], pd.DataFrame],
    pool_fn: Callable[[], pd.DataFrame],
    remove_drafted_from_queue_fn: Callable[[], None] | None = None,
    render_preview_table_fn: Callable[..., None] | None = None,
    layout_label: str = IMPORT_BLOCK_PLACEMENT_LABEL,
) -> None:
    """Always-visible Draft Room import entry (must not be hidden inside a inactive tab)."""
    session["_draft_import_block_entered"] = True
    widget_key = "draft_room_import_uploader"
    config = get_entry_config(ENTRY_DRAFT_ROOM)
    session_key = config["session_key"]

    st.subheader("Import existing draft")
    st.caption(
        f"Upload CSV or Excel with **Team/Owner** and **Player** columns (optional Pick/Round). "
        f"Placement: **{layout_label}**. Validation appears here immediately after upload."
    )

    def _on_upload_change() -> None:
        stage_draft_import_upload(session, widget_key=widget_key)

    imported_draft_file = st.file_uploader(
        "Upload existing draft board CSV or Excel",
        type=["csv", "xlsx", "xls"],
        key=widget_key,
        on_change=_on_upload_change,
    )
    resolved_file = resolve_uploaded_file_for_import(session, imported_draft_file, widget_key=widget_key)
    cached_review = session.get(session_key)

    if resolved_file is None:
        status = build_draft_import_debug_status(
            session,
            entry_point=ENTRY_DRAFT_ROOM,
            uploaded_file=imported_draft_file,
            widget_key=widget_key,
            import_block_entered=True,
            pipeline_called=False,
            review=cached_review if isinstance(cached_review, dict) else None,
            layout_label=layout_label,
        )
        render_draft_import_debug_panel(st, status)
        if isinstance(cached_review, dict) and cached_review.get("rows"):
            import_df = cached_review.get("import_df")
            if isinstance(import_df, pd.DataFrame) and not import_df.empty:
                st.info("Restored cached import review from session — widget file is empty on this rerun.")
                try:
                    pool_df = pool_fn()
                except Exception as exc:
                    st.error(f"Player pool failed to load: {exc}")
                    return
                render_validated_draft_import(
                    st,
                    session,
                    import_df,
                    pool_df,
                    entry_point=ENTRY_DRAFT_ROOM,
                    remove_drafted_from_queue_fn=remove_drafted_from_queue_fn,
                    render_preview_table_fn=render_preview_table_fn,
                )
        elif str(session.get(_STAGED_FILENAME_KEY) or session.get("draft_room_import_uploaded_filename") or "").strip():
            st.warning(
                "A filename is remembered but no upload bytes are available on this rerun. "
                "Please re-select the CSV file once to continue."
            )
        return

    try:
        pool_df = pool_fn()
    except Exception as exc:
        status = build_draft_import_debug_status(
            session,
            entry_point=ENTRY_DRAFT_ROOM,
            uploaded_file=resolved_file,
            widget_key=widget_key,
            import_block_entered=True,
            pipeline_called=False,
            parse_error=f"Player pool failed to load: {exc}",
            layout_label=layout_label,
        )
        render_draft_import_debug_panel(st, status)
        st.error(f"Player pool failed to load: {exc}")
        return

    try:
        render_uploaded_draft_import_section(
            st,
            session,
            resolved_file,
            pool_df,
            entry_point=ENTRY_DRAFT_ROOM,
            read_table_fn=read_table_fn,
            remove_drafted_from_queue_fn=remove_drafted_from_queue_fn,
            render_preview_table_fn=render_preview_table_fn,
            uploaded_filename_session_key="draft_room_import_uploaded_filename",
            widget_key=widget_key,
            layout_label=layout_label,
        )
    except Exception as exc:
        status = build_draft_import_debug_status(
            session,
            entry_point=ENTRY_DRAFT_ROOM,
            uploaded_file=resolved_file,
            widget_key=widget_key,
            import_block_entered=True,
            pipeline_called=True,
            parse_error=str(exc),
            layout_label=layout_label,
        )
        render_draft_import_debug_panel(st, status)
        st.error(f"Could not read uploaded draft file: {exc}")


__all__ = [
    "ENTRY_DRAFT_ROOM",
    "ENTRY_STANDINGS",
    "REQUIRED_IMPORT_COLUMNS",
    "apply_validated_import_to_board",
    "build_draft_import_debug_status",
    "build_import_board_state_diagnostics",
    "build_import_team_name_diagnostics",
    "build_import_review",
    "format_team_name_list",
    "build_validated_import_dataframe",
    "classify_draft_player_import_name",
    "get_entry_config",
    "import_columns_valid",
    "import_review_ready",
    "import_review_ready_for_league",
    "normalize_imported_draft_columns",
    "parse_uploaded_draft_file",
    "read_imported_draft_file",
    "render_draft_import_debug_panel",
    "render_draft_import_validation_ui",
    "render_draft_room_import_block",
    "render_import_pending_banner",
    "render_shared_league_creation_panel",
    "render_uploaded_draft_import_section",
    "render_validated_draft_import",
    "resolve_uploaded_file_for_import",
    "stage_draft_import_upload",
    "teams_for_shared_league_creation",
    "teams_from_draft_board",
    "teams_from_room_settings",
    "teams_in_pick_order_from_df",
    "validate_imported_draft_df",
]
