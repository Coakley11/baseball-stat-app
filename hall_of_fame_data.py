"""Hall of Fame flags, filters, and Case Mode AMI packet builders."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HOF_STAR = "⭐"
HOF_TARGET_STAR = "🔴"
HOF_SCATTER_COLOR_COL = "Hall of Fame"
HOF_SCATTER_HOF_LABEL = "Hall of Famer"
HOF_SCATTER_NON_HOF_LABEL = "Non-Hall of Famer"
HOF_FILTER_ALL = "All Players"
HOF_FILTER_ONLY = "Hall of Famers only"
HOF_FILTER_NON = "Non-Hall of Famers only"
HOF_FILTER_OPTIONS = (HOF_FILTER_ALL, HOF_FILTER_ONLY, HOF_FILTER_NON)
_LEGACY_HOF_FILTER_LABELS = {
    "Hall of Famers Only": HOF_FILTER_ONLY,
    "Non-Hall of Famers Only": HOF_FILTER_NON,
}


def normalize_hof_filter_value(filter_value: str | None) -> str:
    """Map saved/legacy labels to current HOF player-scope filter options."""
    mode = str(filter_value or HOF_FILTER_ALL).strip()
    return _LEGACY_HOF_FILTER_LABELS.get(mode, mode)

CAREER_HOF_FILTER_KEY = "career_hof_membership_filter"
HISTORICAL_HOF_FILTER_KEY = "historical_hof_membership_filter"
CAREER_HOF_CASE_MODE_KEY = "career_hof_case_mode"
CAREER_HOF_CASE_TARGET_KEY = "career_hof_case_target_player"
HOF_CASE_PACKET_KEY = "_hof_case_packet"


def career_hof_case_mode_active(session: dict[str, Any]) -> bool:
    """True when Career Totals Hall of Fame Case Mode is enabled."""
    return bool(session.get(CAREER_HOF_CASE_MODE_KEY))


def snapshot_hof_case_mode_state(session: dict[str, Any]) -> dict[str, Any]:
    """Capture persistent HOF Case Mode keys (survives insight dismiss / cloud restore)."""
    out: dict[str, Any] = {}
    if not career_hof_case_mode_active(session):
        return out
    out[CAREER_HOF_CASE_MODE_KEY] = True
    target = str(session.get(CAREER_HOF_CASE_TARGET_KEY) or "").strip()
    if target:
        out[CAREER_HOF_CASE_TARGET_KEY] = target
    packet = session.get(HOF_CASE_PACKET_KEY)
    if isinstance(packet, dict) and packet:
        out[HOF_CASE_PACKET_KEY] = copy.deepcopy(packet)
    filt = session.get(CAREER_HOF_FILTER_KEY)
    if filt is not None:
        out[CAREER_HOF_FILTER_KEY] = normalize_hof_filter_value(filt)
    return out


def restore_hof_case_mode_state(session: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
    """Re-apply pinned HOF Case Mode keys without touching unrelated session state."""
    if not isinstance(snapshot, dict) or not snapshot.get(CAREER_HOF_CASE_MODE_KEY):
        return
    session[CAREER_HOF_CASE_MODE_KEY] = True
    target = str(snapshot.get(CAREER_HOF_CASE_TARGET_KEY) or "").strip()
    if target:
        session[CAREER_HOF_CASE_TARGET_KEY] = target
    packet = snapshot.get(HOF_CASE_PACKET_KEY)
    if isinstance(packet, dict) and packet:
        session[HOF_CASE_PACKET_KEY] = copy.deepcopy(packet)
    if CAREER_HOF_FILTER_KEY in snapshot:
        session[CAREER_HOF_FILTER_KEY] = normalize_hof_filter_value(snapshot[CAREER_HOF_FILTER_KEY])


def migrate_legacy_historical_hof_filter(session: dict[str, Any]) -> None:
    """Use one shared player-scope key; drop legacy Historical-only filter."""
    legacy = session.pop(HISTORICAL_HOF_FILTER_KEY, None)
    if legacy is None:
        return
    current = normalize_hof_filter_value(session.get(CAREER_HOF_FILTER_KEY))
    if current == HOF_FILTER_ALL:
        session[CAREER_HOF_FILTER_KEY] = normalize_hof_filter_value(legacy)


def resolve_shared_hof_membership_filter(session: dict[str, Any]) -> str:
    """Shared HOF player-scope value when Case Mode is on; otherwise All Players."""
    migrate_legacy_historical_hof_filter(session)
    if not career_hof_case_mode_active(session):
        return HOF_FILTER_ALL
    return normalize_hof_filter_value(session.get(CAREER_HOF_FILTER_KEY) or HOF_FILTER_ALL)


def clear_career_hof_case_scope_state(session: dict[str, Any]) -> None:
    """Reset HOF player-scope UI state when Case Mode is off (no filter, badges, or scatter color)."""
    # Case Mode toggle is independent — never clear CAREER_HOF_CASE_MODE_KEY here.
    session.pop(CAREER_HOF_FILTER_KEY, None)
    session.pop(HISTORICAL_HOF_FILTER_KEY, None)

    meta = session.get("career_state")
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        meta["filters"].pop(CAREER_HOF_FILTER_KEY, None)

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        for page_name in ("Career Totals", "Historical Explorer"):
            block = pf.get(page_name)
            if not isinstance(block, dict):
                continue
            block.pop(CAREER_HOF_FILTER_KEY, None)
            block.pop(HISTORICAL_HOF_FILTER_KEY, None)
            inner = block.get("career_state")
            if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
                inner["filters"].pop(CAREER_HOF_FILTER_KEY, None)

    hist_meta = session.get("historical_state")
    if isinstance(hist_meta, dict) and isinstance(hist_meta.get("filters"), dict):
        hist_meta["filters"].pop(HISTORICAL_HOF_FILTER_KEY, None)
        hist_meta["filters"].pop(CAREER_HOF_FILTER_KEY, None)

    for color_key in ("career_scatter_color", "hist_scatter_color"):
        if session.get(color_key) == HOF_SCATTER_COLOR_COL:
            session.pop(color_key, None)


def ensure_hof_case_scope_ui_state(session: dict[str, Any]) -> bool:
    """When Case Mode is off, strip HOF scope keys from session and page snapshots. Returns active mode."""
    active = career_hof_case_mode_active(session)
    if not active:
        clear_career_hof_case_scope_state(session)
    return active


def render_hof_case_scope_controls(
    st: Any,
    session: dict[str, Any],
    *,
    on_change: Any = None,
    base_dir: str | Path | None = None,
) -> str:
    """Hall of Fame player-scope dropdown — only valid when Case Mode is already ON."""
    session[CAREER_HOF_FILTER_KEY] = normalize_hof_filter_value(
        session.get(CAREER_HOF_FILTER_KEY) or HOF_FILTER_ALL
    )
    st.selectbox(
        "Hall of Fame player scope",
        list(HOF_FILTER_OPTIONS),
        key=CAREER_HOF_FILTER_KEY,
        on_change=on_change,
    )
    if base_dir is not None and not hof_data_available(str(base_dir)):
        st.caption(hof_data_setup_message())
    return resolve_shared_hof_membership_filter(session)


def build_hof_page_runtime_diag(
    session: dict[str, Any],
    *,
    page_name: str,
    hof_case_mode: bool,
    hof_dropdown_render_path_active: bool,
) -> dict[str, Any]:
    """Snapshot for temporary HOF deploy/runtime verification."""
    try:
        from suite_deploy_marker import GIT_BRANCH, GIT_COMMIT_SHORT
    except ImportError:
        GIT_COMMIT_SHORT = "unknown"
        GIT_BRANCH = "unknown"
    hof_keys = sorted(
        k
        for k in session.keys()
        if isinstance(k, str)
        and (
            "hof" in k.lower()
            or k in (CAREER_HOF_FILTER_KEY, HISTORICAL_HOF_FILTER_KEY, CAREER_HOF_CASE_MODE_KEY)
        )
    )
    pending = session.get("_ami_pending_insight")
    pending_id = ""
    pending_qid = ""
    if isinstance(pending, dict):
        pending_id = str(pending.get("insight_id") or "")
        pending_qid = str(pending.get("question_id") or "")
    dismissed = session.get("_ami_dismissed_insight_ids")
    scatter_opts: list[str] = []
    for prefix in ("career", "hist"):
        color_key = f"{prefix}_scatter_color"
        if color_key in session:
            scatter_opts.append(f"{color_key}={session.get(color_key)!r}")
    return {
        "git_commit": GIT_COMMIT_SHORT,
        "git_branch": GIT_BRANCH,
        "page": page_name,
        "hof_case_mode_active": bool(hof_case_mode),
        "hof_dropdown_render_path_active": bool(hof_dropdown_render_path_active),
        "hof_related_session_keys": {k: session.get(k) for k in hof_keys},
        "scatter_color_session": scatter_opts,
        "insight_pending_id": pending_id,
        "insight_pending_question_id": pending_qid,
        "insight_staged_key": session.get("_hof_case_insight_staged_for_resume"),
        "insight_force_render": bool(session.get("_ami_force_insight_render")),
        "insight_submit_render_this_run": bool(session.get("_ami_submit_render_insight_this_run")),
        "insight_dismissed_ids": list(dismissed) if isinstance(dismissed, (list, tuple)) else sorted(dismissed or []),
        "insight_hydrated_id": session.get("_ami_hydrated_insight_id"),
        "workspace_snapshot_restored": bool(session.get("_hof_case_workspace_restored")),
        "career_year_range_filter": session.get("career_year_range_filter"),
        "historical_year_range_filter": session.get("historical_year_range_filter"),
        "career_hof_membership_filter": session.get(CAREER_HOF_FILTER_KEY),
        "historical_hof_membership_filter": session.get(HISTORICAL_HOF_FILTER_KEY),
        "career_hof_case_target_player": session.get(CAREER_HOF_CASE_TARGET_KEY),
        "hof_pending_overlay": bool(session.get("_hof_case_pending_overlay")),
    }


def render_hof_page_runtime_diag(
    st: Any,
    session: dict[str, Any],
    *,
    page_name: str,
    hof_case_mode: bool,
    hof_dropdown_render_path_active: bool,
    developer_mode: bool = False,
) -> None:
    """Deploy audit for Career Totals / Historical Explorer — developer mode only."""
    if not developer_mode:
        return
    audit = build_hof_page_runtime_diag(
        session,
        page_name=page_name,
        hof_case_mode=hof_case_mode,
        hof_dropdown_render_path_active=hof_dropdown_render_path_active,
    )
    with st.expander("Deploy runtime audit (HOF)", expanded=False):
        st.caption(
            f"Commit `{audit.get('git_commit')}` on `{audit.get('git_branch')}`. "
            "If HOF dropdown appears while `hof_case_mode_active` is false, the deployed build is stale."
        )
        st.json(audit)


CASE_SCORE_LABEL = "Hall of Fame Statistical Case Score"

_HOF_INTERNAL_PROMPT_MARKERS = (
    "hof_case_packet",
    "target_awards_summary",
    "cohort_award_comparison",
    "Respond with one of",
    "Hall of Fame Case Mode — assign",
)


def is_hof_ami_internal_prompt(text: str) -> bool:
    """True when text is the long internal AMI instruction, not a user question."""
    blob = str(text or "").strip()
    if not blob:
        return False
    return any(marker in blob for marker in _HOF_INTERNAL_PROMPT_MARKERS)


def hof_case_disclaimer_text(packet: dict[str, Any] | None = None, *, include_awards: bool | None = None) -> str:
    """Footer disclaimer — mentions awards only when awards evidence is part of the case."""
    base = (
        "Statistical Hall of Fame case analysis only — not true Hall of Fame induction odds. "
        "Use cohort strength, career totals, and position-adjusted rarity"
    )
    has_awards = include_awards
    if has_awards is None and isinstance(packet, dict):
        awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
        has_awards = bool(awards.get("data_available") and int(awards.get("major_award_count") or 0) >= 1)
    if has_awards:
        return (
            f"{base}, and supporting awards evidence. "
            "Do not present a guaranteed probability of induction."
        )
    return f"{base}. Do not present a guaranteed probability of induction."
CASE_SCORE_BUCKETS = ("Weak", "Borderline", "Solid", "Strong", "Very Strong")
HOF_CASE_MODE_EXPLANATION = (
    "Hall of Fame Case Mode lets you evaluate whether a player belongs to a statistical cohort "
    "that historically contains many Hall of Famers. Choose a player, create a career-stat comparison "
    "group using the filters, then send the cohort to AMI for a Hall of Fame statistical case analysis."
)
HOF_CASE_MODE_INSTRUCTIONS = (
    "Select a player, then use the Career Totals filters above to create a comparison group. "
    "The selected player must appear in the filtered results before a Hall of Fame case can be analyzed."
)
HOF_CASE_MODE_HISTORICAL_NOTICE = (
    "Hall of Fame Case Mode is ON. To turn it off, unselect Hall of Fame Case Mode on the Career Totals page."
)
HOF_CASE_ANALYZE_BUTTON_LABEL = "Analyze Hall of Fame Statistical Case with AMI"
HOF_CASE_TARGET_ALREADY_IN_HOF_MSG = (
    "Target player must be a non-Hall of Famer. Please select another player."
)
HOF_DATA_FILENAME = "HallOfFame.csv"
HOF_PLAYER_CATEGORY = "Player"
KNOWN_HOF_PLAYER_IDS = ("ruthba01", "aaronha01", "mayswi01")


def hof_case_target_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return s or "player"


def resolve_hof_case_target_slug(slug: str, player_names: list[str] | None = None) -> str:
    """Map resume slug (e.g. albert-pujols) back to a display name when possible."""
    target_slug = str(slug or "").strip().lower()
    for name in player_names or []:
        if hof_case_target_slug(name) == target_slug:
            return str(name).strip()
    cleaned = str(slug or "").replace("-", " ").strip()
    return cleaned.title() if cleaned else ""


def target_player_is_hall_of_famer(
    target: str,
    df: pd.DataFrame | None,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
) -> bool:
    """True when the named target player is already inducted (not eligible for Case Mode)."""
    name = str(target or "").strip()
    if not name or df is None or df.empty or player_col not in df.columns or hof_col not in df.columns:
        return False
    rows = df[df[player_col].astype(str).str.strip() == name]
    if rows.empty:
        return False
    return bool(rows[hof_col].fillna(False).astype(bool).any())


def hof_case_target_player_options(
    df: pd.DataFrame | None,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
) -> list[str]:
    """Player names eligible as Hall of Fame Case Mode targets (non-inducted only)."""
    if df is None or df.empty or player_col not in df.columns:
        return []
    working = df
    if hof_col in working.columns:
        working = working.loc[~working[hof_col].fillna(False).astype(bool)]
    names = working[player_col].dropna().astype(str).str.strip()
    return sorted({n for n in names if n})


def hall_of_fame_csv_path(base_dir: Path | str) -> Path:
    """Absolute path to Lahman ``HallOfFame.csv`` (same folder as ``streamlit_app.py``)."""
    return Path(base_dir) / HOF_DATA_FILENAME


def hof_data_available(base_dir: Path | str) -> bool:
    """True when inducted player HOF data can be loaded from disk."""
    return len(load_hall_of_fame_player_ids(base_dir)) > 0


def hof_file_cache_key(base_dir: Path | str) -> float:
    """Change when ``HallOfFame.csv`` is added or updated (for Streamlit cache busting)."""
    path = hall_of_fame_csv_path(base_dir)
    try:
        return float(path.stat().st_mtime) if path.exists() else 0.0
    except OSError:
        return 0.0


def _column_lookup(df: pd.DataFrame, *names: str) -> str | None:
    lower = {str(c).lower(): str(c) for c in df.columns}
    for name in names:
        hit = lower.get(name.lower())
        if hit:
            return hit
    return None


def _parse_hof_dataframe(hof: pd.DataFrame) -> pd.DataFrame:
    """Normalize Lahman HallOfFame column names and inducted/category values."""
    if hof is None or hof.empty:
        return pd.DataFrame(columns=["playerID", "inducted", "category"])
    out = hof.copy()
    rename: dict[str, str] = {}
    pid_col = _column_lookup(out, "playerID", "playerid")
    inducted_col = _column_lookup(out, "inducted")
    category_col = _column_lookup(out, "category")
    if pid_col and pid_col != "playerID":
        rename[pid_col] = "playerID"
    if inducted_col and inducted_col != "inducted":
        rename[inducted_col] = "inducted"
    if category_col and category_col != "category":
        rename[category_col] = "category"
    if rename:
        out = out.rename(columns=rename)
    if "playerID" not in out.columns:
        return pd.DataFrame(columns=["playerID", "inducted", "category"])
    out["playerID"] = out["playerID"].astype(str).str.strip()
    out = out[out["playerID"].ne("") & out["playerID"].ne("nan")]
    if "inducted" in out.columns:
        out["inducted"] = out["inducted"].astype(str).str.strip().str.upper()
        out = out[out["inducted"].eq("Y")]
    if "category" in out.columns:
        out["category"] = out["category"].astype(str).str.strip()
        out = out[out["category"].str.casefold().eq(HOF_PLAYER_CATEGORY.casefold())]
    return out.drop_duplicates(subset=["playerID"], keep="first")


def load_hall_of_fame_player_ids(base_dir: Path | str) -> frozenset[str]:
    """Inducted player-category playerIDs from Lahman ``HallOfFame.csv``."""
    path = hall_of_fame_csv_path(base_dir)
    if not path.exists():
        return frozenset()
    try:
        hof = pd.read_csv(path, low_memory=False)
    except Exception:
        return frozenset()
    parsed = _parse_hof_dataframe(hof)
    if parsed.empty or "playerID" not in parsed.columns:
        return frozenset()
    return frozenset(parsed["playerID"].astype(str).tolist())


def hof_csv_modified_time(base_dir: Path | str) -> str | None:
    path = hall_of_fame_csv_path(base_dir)
    try:
        if not path.exists():
            return None
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return None


def count_hof_true(df: pd.DataFrame | None, *, hof_col: str = "isHallOfFamer") -> int:
    if df is None or df.empty or hof_col not in df.columns:
        return 0
    return int(df[hof_col].fillna(False).astype(bool).sum())


def build_hof_cohort_summary_text(
    results_df: pd.DataFrame | None,
    *,
    hof_data_loaded: bool = True,
    hof_col: str = "isHallOfFamer",
) -> str | None:
    """Plain Hall of Fame cohort core (count/rate only). Prefer build_hof_cohort_display_text for UI."""
    line = _hof_cohort_core_line(results_df, hof_data_loaded=hof_data_loaded, hof_col=hof_col)
    return f"Hall of Fame cohort: {line}" if line else None


def _hof_cohort_core_line(
    results_df: pd.DataFrame | None,
    *,
    hof_data_loaded: bool = True,
    hof_col: str = "isHallOfFamer",
) -> str | None:
    if results_df is None or results_df.empty:
        return None
    total = int(len(results_df))
    if not hof_data_loaded:
        return "Hall of Fame data unavailable — add HallOfFame.csv to calculate cohort rate."
    if hof_col not in results_df.columns:
        return "Hall of Fame flags are not available for this result set."
    hof_count = count_hof_true(results_df, hof_col=hof_col)
    rate = round(100.0 * hof_count / total, 1) if total else 0.0
    return f"{hof_count} of {total} players are Hall of Famers ({rate}%)"


def _compact_stat_min_criteria(session: dict[str, Any], *, prefix: str) -> str:
    try:
        from stat_filter_summary import RATE_STAT_COLUMNS, gather_active_stat_min_filters
    except ImportError:
        return ""
    parts: list[str] = []
    for stat, val in gather_active_stat_min_filters(session, prefix=prefix):
        if stat in RATE_STAT_COLUMNS:
            parts.append(f"{stat} >= {val:.3f}")
        elif abs(val - round(val)) < 1e-9:
            parts.append(f"{stat} >= {int(round(val)):,}")
        else:
            parts.append(f"{stat} >= {val:g}")
    return ", ".join(parts)


def build_hof_cohort_display_text(
    session: dict[str, Any],
    results_df: pd.DataFrame | None,
    *,
    mode: str = "career",
    hof_data_loaded: bool = True,
    hof_col: str = "isHallOfFamer",
) -> str | None:
    """Single-line HOF cohort message; optional stat-min prefix when filters are active."""
    core = _hof_cohort_core_line(results_df, hof_data_loaded=hof_data_loaded, hof_col=hof_col)
    if not core:
        return None
    prefix_key = "career" if str(mode).strip().lower() != "historical" else "hist"
    criteria = _compact_stat_min_criteria(session, prefix=prefix_key)
    cohort_part = f"Hall of Fame cohort: {core}"
    if criteria:
        totals_label = "career totals" if prefix_key == "career" else "single-season totals"
        return f"Players with {totals_label} of {criteria} — {cohort_part}"
    return cohort_part


def render_hof_cohort_summary(st: Any, summary_text: str | None) -> None:
    if summary_text:
        st.markdown(summary_text)


def render_hof_candidate_header(
    st: Any,
    target_player: str,
    results_df: pd.DataFrame | None = None,
    *,
    subtitle: str = "",
) -> None:
    """Player headshot + name banner for Hall of Fame candidate selection."""
    target = str(target_player or "").strip()
    if not target:
        return
    player_id = None
    if results_df is not None and not results_df.empty and "fullName" in results_df.columns:
        match = results_df[results_df["fullName"].astype(str).str.strip().eq(target)]
        if not match.empty and "playerID" in match.columns:
            player_id = str(match.iloc[0]["playerID"]).strip() or None
    try:
        from player_photos import get_player_photo_info, render_player_headshot_row

        photo_info = get_player_photo_info(player_id=player_id, full_name=target, use_api=True)
        render_player_headshot_row(st, photo_info, title=target, subtitle=subtitle)
        try:
            from components.applied_math_context_diagnostics import applied_math_developer_mode_enabled

            if applied_math_developer_mode_enabled(st):
                with st.expander("Developer: player photo resolve", expanded=False):
                    st.json(photo_info)
        except ImportError:
            pass
    except ImportError:
        st.markdown(f"### {target}")
        if subtitle:
            st.caption(subtitle)


def build_hof_runtime_diagnostics(
    base_dir: Path | str,
    *,
    results_df: pd.DataFrame | None = None,
    batting_df: pd.DataFrame | None = None,
    hof_player_ids: frozenset[str] | None = None,
    hof_cache_key: float | None = None,
    git_commit: str = "",
    hof_filter_value: str = "",
    page_label: str = "",
) -> dict[str, Any]:
    """Full runtime diagnostic bundle for developer panels."""
    path = hall_of_fame_csv_path(base_dir)
    base = Path(base_dir)
    ids = hof_player_ids if hof_player_ids is not None else load_hall_of_fame_player_ids(base_dir)
    first_five = sorted(ids)[:5]
    diag = hof_load_diagnostics(base_dir)
    diag.update(
        {
            "page": page_label,
            "git_commit": git_commit or "unknown",
            "app_base_dir": str(base.resolve()),
            "csv_path_resolved": str(path.resolve()),
            "csv_modified_utc": hof_csv_modified_time(base_dir),
            "hof_cache_key": hof_cache_key,
            "hof_filter_active": str(hof_filter_value or HOF_FILTER_ALL),
            "loaded_hof_player_id_count": len(ids),
            "first_5_hof_player_ids": first_five,
            "batting_df_row_count": int(len(batting_df)) if batting_df is not None else 0,
            "batting_df_isHallOfFamer_true_count": count_hof_true(batting_df),
            "results_df_row_count": int(len(results_df)) if results_df is not None else 0,
            "results_df_isHallOfFamer_true_count": count_hof_true(results_df),
            "root_csv_files": sorted(p.name for p in base.glob("*.csv")),
        }
    )
    diag["sample_player_ids"] = first_five
    return diag


def hof_load_diagnostics(base_dir: Path | str) -> dict[str, Any]:
    """Runtime diagnostics for HOF CSV path, parse, and known-ID checks."""
    path = hall_of_fame_csv_path(base_dir)
    diag: dict[str, Any] = {
        "csv_path": str(path.resolve()),
        "csv_exists": path.exists(),
        "csv_filename": HOF_DATA_FILENAME,
        "hof_data_available": False,
        "inducted_player_count": 0,
        "sample_player_ids": [],
        "known_ids_present": {pid: False for pid in KNOWN_HOF_PLAYER_IDS},
        "columns": [],
        "csv_modified_utc": hof_csv_modified_time(base_dir),
    }
    if not path.exists():
        return diag
    try:
        raw = pd.read_csv(path, low_memory=False, nrows=0)
        diag["columns"] = [str(c) for c in raw.columns]
    except Exception as exc:
        diag["read_error"] = str(exc)
        return diag
    ids = load_hall_of_fame_player_ids(base_dir)
    sample = sorted(ids)[:10]
    diag.update(
        {
            "hof_data_available": bool(ids),
            "inducted_player_count": len(ids),
            "sample_player_ids": sample,
            "known_ids_present": {pid: pid in ids for pid in KNOWN_HOF_PLAYER_IDS},
        }
    )
    return diag


def hof_data_setup_message() -> str:
    return (
        f"Hall of Fame badges and Case Mode require Lahman `{HOF_DATA_FILENAME}` in the app root "
        f"(same folder as `People.csv`, `Batting.csv`, and `Fielding.csv`). "
        f"Download from the [Lahman database](https://sabr.org/lahman-database/) and upload "
        f"`{HOF_DATA_FILENAME}` alongside the other CSVs. Until then, filters still work but "
        f"no ⭐ badges or HOF cohort stats will appear."
    )


def attach_hof_flag(df: pd.DataFrame, hof_ids: frozenset[str], *, id_col: str = "playerID") -> pd.DataFrame:
    """Add or refresh ``isHallOfFamer`` via ``playerID`` membership (never player name)."""
    if df is None or df.empty or id_col not in df.columns:
        return df
    out = df.copy()
    if "isHallOfFamer" in out.columns:
        out = out.drop(columns=["isHallOfFamer"])
    pid = out[id_col].astype(str).str.strip()
    out["isHallOfFamer"] = pid.isin(hof_ids)
    return out


def merge_hof_flag(df: pd.DataFrame, hof_ids: frozenset[str], *, id_col: str = "playerID") -> pd.DataFrame:
    """Attach HOF flag on aggregated page results (always keyed on ``playerID``)."""
    return attach_hof_flag(df, hof_ids, id_col=id_col)


def hof_scatter_color_available(df: pd.DataFrame | None) -> bool:
    if df is None or df.empty:
        return False
    return HOF_SCATTER_COLOR_COL in df.columns or "isHallOfFamer" in df.columns


def ensure_hof_scatter_columns(
    df: pd.DataFrame | None,
    hof_ids: frozenset[str] | None = None,
) -> pd.DataFrame:
    """Ensure scatter plot data has ``isHallOfFamer`` and categorical ``Hall of Fame`` columns."""
    if df is None or df.empty:
        return df
    out = attach_hof_flag(df, hof_ids, id_col="playerID") if hof_ids and "playerID" in df.columns else df.copy()
    if "isHallOfFamer" not in out.columns:
        return out
    hof_mask = out["isHallOfFamer"].fillna(False).astype(bool)
    out[HOF_SCATTER_COLOR_COL] = np.where(
        hof_mask,
        HOF_SCATTER_HOF_LABEL,
        HOF_SCATTER_NON_HOF_LABEL,
    )
    return out


def apply_hof_membership_filter(
    df: pd.DataFrame,
    filter_value: str,
    *,
    hof_col: str = "isHallOfFamer",
) -> pd.DataFrame:
    if df is None or df.empty or hof_col not in df.columns:
        return df
    mode = normalize_hof_filter_value(filter_value)
    if mode == HOF_FILTER_ONLY:
        return df[df[hof_col].fillna(False).astype(bool)].copy()
    if mode == HOF_FILTER_NON:
        return df[~df[hof_col].fillna(False).astype(bool)].copy()
    return df


def decorate_player_name(name: Any, is_hof: Any, *, is_target: bool = False) -> str:
    label = str(name or "").strip()
    if not label:
        return label
    if is_target and not bool(is_hof):
        if not label.startswith(HOF_TARGET_STAR):
            return f"{HOF_TARGET_STAR} {label}"
    if bool(is_hof):
        if not label.startswith(HOF_STAR):
            return f"{HOF_STAR} {label}"
    return label


def decorate_player_column(df: pd.DataFrame, *, name_col: str = "fullName", hof_col: str = "isHallOfFamer") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns:
        return df
    out = df.copy()
    if hof_col in out.columns:
        out[name_col] = [
            decorate_player_name(n, h) for n, h in zip(out[name_col], out[hof_col], strict=False)
        ]
    return out


def _resolve_display_name_column(df: pd.DataFrame, name_col: str | None = None) -> str | None:
    if name_col and name_col in df.columns:
        return name_col
    for candidate in ("Player", "fullName", "Name", "player_name", "full_name"):
        if candidate in df.columns:
            return candidate
    return None


def badge_hof_players_for_table(
    table_df: pd.DataFrame,
    source_df: pd.DataFrame | None = None,
    *,
    name_col: str | None = None,
    hof_col: str = "isHallOfFamer",
    target_player: str | None = None,
    target_name_col: str = "fullName",
) -> pd.DataFrame:
    """Apply ⭐ to Hall of Famers and 🔴 to the HOF case target player in the rendered table."""
    if table_df is None or table_df.empty:
        return table_df
    out = table_df.copy()
    col = _resolve_display_name_column(out, name_col)
    if not col:
        return out.drop(columns=[hof_col], errors="ignore")
    flags = None
    if hof_col in out.columns:
        flags = out[hof_col]
    elif source_df is not None and hof_col in source_df.columns:
        if out.index.equals(source_df.index):
            flags = source_df[hof_col]
        else:
            flags = source_df.reindex(out.index)[hof_col]
    if flags is None:
        return out.drop(columns=[hof_col], errors="ignore")
    target_norm = str(target_player or "").strip().casefold()
    match_names = None
    if target_norm and source_df is not None and target_name_col in source_df.columns:
        if out.index.equals(source_df.index):
            match_names = source_df[target_name_col]
        else:
            match_names = source_df.reindex(out.index)[target_name_col]
    out[col] = [
        decorate_player_name(
            n,
            h,
            is_target=bool(
                target_norm
                and str((match_names.iloc[i] if match_names is not None else n) or "").strip().casefold()
                == target_norm
            ),
        )
        for i, (n, h) in enumerate(zip(out[col], flags, strict=False))
    ]
    return out.drop(columns=[hof_col], errors="ignore")


def _json_safe_value(val: Any) -> Any:
    if val is None or (not isinstance(val, (list, dict, tuple)) and pd.isna(val)):
        return None
    if isinstance(val, (bool,)):
        return bool(val)
    type_name = type(val).__name__
    if type_name in ("bool_", "bool8"):
        return bool(val)
    if type_name in ("int64", "int32", "int16", "int8", "uint64", "uint32", "uint16", "uint8"):
        return int(val)
    if type_name in ("float64", "float32", "float16"):
        return float(val)
    if isinstance(val, (int, float, str)):
        return val
    return str(val)


def _json_safe_row(row: pd.Series) -> dict[str, Any]:
    return {str(k): _json_safe_value(row[k]) for k in row.index if pd.notna(row[k])}


def _num(val: Any) -> float | None:
    n = pd.to_numeric(val, errors="coerce")
    if pd.isna(n):
        return None
    return float(n)


HOF_CASE_STAT_KEYS = (
    "G",
    "AB",
    "R",
    "H",
    "2B",
    "3B",
    "HR",
    "RBI",
    "SB",
    "BB",
    "BA",
    "OBP",
    "SLG",
    "OPS",
)

# Optional Lahman / derived columns included when present on the target or cohort rows.
HOF_OPTIONAL_ADVANCED_STAT_KEYS = (
    "W",
    "L",
    "SO",
    "IPouts",
    "ERA",
    "SH",
    "SF",
    "HBP",
    "proj_WAR",
    "WAR",
    "JAWS",
    "OPS_plus",
    "OPS+",
    "wRC_plus",
    "wRC+",
    "ERA_plus",
    "ERA+",
)

HOF_CAREER_MILESTONES: tuple[tuple[str, float, str], ...] = (
    ("HR", 500, "500 home runs"),
    ("HR", 400, "400 home runs"),
    ("H", 3000, "3,000 hits"),
    ("H", 2500, "2,500 hits"),
    ("RBI", 1500, "1,500 RBI"),
    ("RBI", 1000, "1,000 RBI"),
    ("R", 2000, "2,000 runs"),
    ("SB", 500, "500 stolen bases"),
    ("SB", 300, "300 stolen bases"),
    ("2B", 600, "600 doubles"),
    ("BB", 1500, "1,500 walks"),
    ("W", 300, "300 wins"),
    ("SO", 3000, "3,000 strikeouts"),
    ("G", 2000, "2,000 games"),
)

HOF_AMI_CONTEXT_TYPE = "baseball_hof_case"
HOF_AMI_SOURCE_APP = "baseball_analytics"
HOF_AMI_SOURCE_PAGE = "career_totals"
HOF_COHORT_TABLE_ROW_LIMIT = 50
HOF_COMPARABLE_PLAYER_LIMIT = 5


def _resolve_primary_position(row: pd.Series | dict[str, Any]) -> str:
    if isinstance(row, dict):
        row = pd.Series(row)
    for col in ("Primary Position", "displayPosition", "careerPrimaryPos", "primaryPos", "POS"):
        if col in row.index:
            val = str(row.get(col) or "").strip()
            if val and val.lower() not in ("nan", "none", ""):
                return val
    return "Unknown"


def _stat_columns_present(df: pd.DataFrame, stats: tuple[str, ...] = HOF_CASE_STAT_KEYS) -> list[str]:
    if df is None or df.empty:
        return []
    return [c for c in stats if c in df.columns]


def _cohort_stat_summary(working: pd.DataFrame, stat: str) -> dict[str, Any]:
    if stat not in working.columns or working.empty:
        return {}
    series = pd.to_numeric(working[stat], errors="coerce").dropna()
    if series.empty:
        return {}
    return {
        "min": float(series.min()),
        "max": float(series.max()),
        "median": float(series.median()),
        "mean": round(float(series.mean()), 3),
        "count": int(series.count()),
    }


def _rank_in_frame(
    df: pd.DataFrame,
    target: str,
    stat: str,
    *,
    player_col: str = "fullName",
    ascending: bool = False,
) -> dict[str, Any] | None:
    if df is None or df.empty or stat not in df.columns or player_col not in df.columns:
        return None
    ranked = df.sort_values(stat, ascending=ascending, na_position="last").reset_index(drop=True)
    names = ranked[player_col].astype(str).str.strip()
    match = names.eq(target)
    if not match.any():
        return None
    idx = int(match.idxmax())
    total = int(len(ranked))
    rank = idx + 1
    value = _num(ranked.iloc[idx].get(stat))
    percentile = round(100.0 * (total - rank) / max(total - 1, 1), 1) if total > 1 else 100.0
    if not ascending:
        percentile = round(100.0 * (total - rank) / max(total - 1, 1), 1) if total > 1 else 100.0
    else:
        percentile = round(100.0 * (rank - 1) / max(total - 1, 1), 1) if total > 1 else 100.0
    return {
        "stat": stat,
        "rank": rank,
        "of": total,
        "value": value,
        "percentile_top": percentile,
        "tier": _percentile_tier(percentile),
    }


def _percentile_tier(percentile_top: float) -> str:
    if percentile_top >= 99:
        return "top 1%"
    if percentile_top >= 95:
        return "top 5%"
    if percentile_top >= 90:
        return "top 10%"
    if percentile_top >= 75:
        return "top quartile"
    if percentile_top >= 50:
        return "above median"
    if percentile_top >= 25:
        return "below median"
    return "bottom quartile"


def _build_cohort_stat_context(
    working: pd.DataFrame,
    target: str,
    *,
    player_col: str = "fullName",
    stats: tuple[str, ...] = HOF_CASE_STAT_KEYS,
) -> dict[str, Any]:
    stat_cols = _stat_columns_present(working, stats)
    summaries: dict[str, Any] = {}
    target_ranks: dict[str, Any] = {}
    for stat in stat_cols:
        summary = _cohort_stat_summary(working, stat)
        if summary:
            summaries[stat] = summary
        rank = _rank_in_frame(working, target, stat, player_col=player_col)
        if rank:
            target_ranks[stat] = rank
    strengths = [s for s, r in target_ranks.items() if r.get("percentile_top", 0) >= 75]
    weaknesses = [s for s, r in target_ranks.items() if r.get("percentile_top", 0) < 25]
    return {
        "cohort_stat_summaries": summaries,
        "target_cohort_ranks": target_ranks,
        "cohort_strength_stats": strengths[:6],
        "cohort_weakness_stats": weaknesses[:6],
    }


def _assess_cohort_selectivity(
    filters_summary: dict[str, Any],
    *,
    total: int,
    hof_rate: float,
    sort_stat: str,
) -> dict[str, Any]:
    stat_mins = filters_summary.get("stat_minimums") if isinstance(filters_summary.get("stat_minimums"), dict) else {}
    threshold_notes: list[str] = []
    selectivity_score = 0
    for stat, val in stat_mins.items():
        n = _num(val)
        if n is None:
            continue
        if stat == "HR" and n >= 500:
            threshold_notes.append("A 500+ HR cohort is historically very Hall-of-Fame heavy.")
            selectivity_score += 3
        elif stat == "HR" and n >= 400:
            threshold_notes.append("A 400+ HR threshold signals elite power and a selective cohort.")
            selectivity_score += 2
        elif stat == "H" and n >= 3000:
            threshold_notes.append("3,000 hits is one of the strongest traditional Hall markers.")
            selectivity_score += 3
        elif stat == "H" and n >= 2500:
            threshold_notes.append("2,500+ hits is a highly selective longevity cohort.")
            selectivity_score += 2
        elif stat == "RBI" and n >= 1500:
            threshold_notes.append("1,500+ RBI filters to established run producers.")
            selectivity_score += 1
    if total <= 15:
        threshold_notes.append("This cohort is selective, so appearing in it is stronger evidence.")
        selectivity_score += 2
    elif total >= 80:
        threshold_notes.append("This cohort is broad, so the HOF rate should be treated with less confidence.")
        selectivity_score -= 1
    if hof_rate >= 70:
        threshold_notes.append("The filtered group has a very high Hall of Fame prevalence.")
    elif hof_rate <= 15 and total >= 10:
        threshold_notes.append("Few players in this cohort are inducted — the case depends on standing out within the group.")
    confidence = "high" if selectivity_score >= 3 else "moderate" if selectivity_score >= 1 else "low"
    return {
        "selectivity": "selective" if selectivity_score >= 2 else "moderate" if selectivity_score >= 0 else "broad",
        "confidence": confidence,
        "threshold_notes": threshold_notes,
        "sort_stat": sort_stat,
        "cohort_size": total,
        "hof_rate_pct": hof_rate,
    }


def _aggregate_position_universe(
    batting_df: pd.DataFrame,
    *,
    player_col: str = "fullName",
) -> pd.DataFrame:
    if batting_df is None or batting_df.empty or "playerID" not in batting_df.columns:
        return pd.DataFrame()
    stat_cols = [c for c in HOF_CASE_STAT_KEYS if c in batting_df.columns and c not in ("BA", "OBP", "SLG", "OPS")]
    group_cols = ["playerID", player_col] if player_col in batting_df.columns else ["playerID"]
    pos_col = None
    for candidate in ("careerPrimaryPos", "primaryPos", "POS"):
        if candidate in batting_df.columns:
            pos_col = candidate
            break
    if pos_col:
        group_cols.append(pos_col)
    grouped = batting_df.groupby(group_cols, as_index=False)[stat_cols].sum()
    if pos_col and pos_col != "careerPrimaryPos":
        grouped = grouped.rename(columns={pos_col: "careerPrimaryPos"})
    elif pos_col is None:
        grouped["careerPrimaryPos"] = "Unknown"
    if all(c in grouped.columns for c in ("H", "AB")):
        grouped["BA"] = grouped["H"] / grouped["AB"].replace(0, pd.NA)
    return grouped


def _build_position_hof_context(
    target: str,
    target_row: dict[str, Any] | None,
    position_universe: pd.DataFrame | None,
    *,
    player_col: str = "fullName",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "primary_position": "Unknown",
        "position_stat_ranks": {},
        "position_percentiles": {},
        "position_rarity_findings": [],
    }
    if not target_row or position_universe is None or position_universe.empty:
        return out
    primary = _resolve_primary_position(target_row)
    out["primary_position"] = primary
    if primary in ("Unknown", ""):
        return out
    pos_col = "careerPrimaryPos" if "careerPrimaryPos" in position_universe.columns else None
    if not pos_col:
        return out
    peers = position_universe[position_universe[pos_col].astype(str).str.strip() == primary].copy()
    if peers.empty:
        return out
    stat_cols = _stat_columns_present(peers)
    ranks: dict[str, Any] = {}
    percentiles: dict[str, Any] = {}
    rarity: list[str] = []
    for stat in stat_cols:
        rank_info = _rank_in_frame(peers, target, stat, player_col=player_col)
        if not rank_info:
            continue
        ranks[stat] = {"rank": rank_info["rank"], "of": rank_info["of"], "value": rank_info["value"]}
        percentiles[stat] = {
            "percentile_top": rank_info["percentile_top"],
            "tier": rank_info["tier"],
        }
        if rank_info["rank"] == 1 and stat in ("HR", "H", "RBI", "SB", "2B", "3B"):
            rarity.append(f"#{rank_info['rank']} all-time among {primary}s in {stat} in this dataset.")
        val = _num(rank_info.get("value"))
        peer_total = int(rank_info.get("of") or 0)
        if val is not None and stat in ("HR", "H", "RBI") and peer_total >= 5:
            above = peers[pd.to_numeric(peers[stat], errors="coerce") >= val]
            count_at_threshold = int(len(above))
            if stat == "HR" and val >= 300 and count_at_threshold <= 5:
                rarity.append(
                    f"One of only {count_at_threshold} {primary}s with {int(val)}+ HR in this dataset."
                )
            elif stat == "H" and val >= 2500 and count_at_threshold <= 5:
                rarity.append(
                    f"One of only {count_at_threshold} {primary}s with {int(val)}+ hits in this dataset."
                )
    out["position_stat_ranks"] = ranks
    out["position_percentiles"] = percentiles
    out["position_rarity_findings"] = rarity[:8]
    return out


def build_hof_case_summary_line(packet: dict[str, Any]) -> str:
    target = str(packet.get("target_player") or "")
    rate = packet.get("hall_of_fame_rate_pct")
    total = packet.get("total_players_returned")
    hof_n = packet.get("hall_of_famers_returned")
    pos = str(packet.get("primary_position") or packet.get("position_context", {}).get("primary_position") or "")
    rank = packet.get("target_rank")
    sort_stat = packet.get("sort_stat") or ""
    parts = [f"Hall of Fame statistical case for {target}"]
    if total is not None:
        parts.append(f"cohort {hof_n}/{total} HOF ({rate}%)")
    if rank and sort_stat:
        parts.append(f"#{rank} in cohort by {sort_stat}")
    if pos and pos != "Unknown":
        parts.append(f"primary position {pos}")
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    if target_awards.get("data_available"):
        try:
            major = int(target_awards.get("major_award_count") or 0)
            total_aw = int(target_awards.get("total_award_count") or 0)
        except (TypeError, ValueError):
            major = total_aw = 0
        if major >= 1:
            parts.append(f"{major} major award(s)")
        elif total_aw >= 1:
            parts.append(f"{total_aw} total award(s)")
    return " · ".join(parts)


def summarize_career_filters(session: dict[str, Any]) -> dict[str, Any]:
    """Capture Career Totals filter state for HOF Case packet."""
    yr = session.get("career_year_range_filter")
    year_range = None
    if isinstance(yr, (list, tuple)) and len(yr) >= 2:
        year_range = [int(yr[0]), int(yr[1])]
    stat_mins: dict[str, Any] = {}
    for key, val in session.items():
        k = str(key)
        if k.startswith("career_") and k.endswith("_min") and val is not None:
            stat_mins[k.replace("career_", "").replace("_min", "")] = val
    summary: dict[str, Any] = {
        "year_range": year_range,
        "sort_stat": session.get("career_sort_stat_filter"),
        "batting_hand": session.get("career_batting_hand_filter"),
        "position_mode": session.get("career_position_filter_mode"),
        "position": session.get("career_position_filter"),
        "team_filter": session.get("career_team_filter"),
        "by_team": bool(session.get("career_by_team_toggle_filter")),
        "stat_minimums": stat_mins,
    }
    if session.get(CAREER_HOF_CASE_MODE_KEY):
        summary["hof_membership_filter"] = normalize_hof_filter_value(
            session.get(CAREER_HOF_FILTER_KEY) or HOF_FILTER_ALL
        )
    return summary


def _export_columns_for_df(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    preferred = [
        "playerID",
        "fullName",
        "displayPosition",
        "displayTeam",
        "primaryHistoricalTeamName",
        "teamHistoricalName",
        "teamName",
        "careerPrimaryPos",
        "primaryPos",
        "bats",
        "isHallOfFamer",
        *HOF_CASE_STAT_KEYS,
        *HOF_OPTIONAL_ADVANCED_STAT_KEYS,
    ]
    cols: list[str] = []
    for col in preferred:
        if col in df.columns and col not in cols:
            cols.append(col)
    return cols


def _row_to_player_record(
    row: pd.Series,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    for col in row.index:
        val = row.get(col)
        if pd.isna(val):
            continue
        if col == player_col:
            entry["player"] = decorate_player_name(val, row.get(hof_col))
            entry["fullName"] = str(val).strip()
        elif col == hof_col:
            entry["hall_of_famer"] = bool(val)
            entry["isHallOfFamer"] = bool(val)
        elif col == "playerID":
            entry["playerID"] = str(val).strip()
        else:
            n = _num(val)
            entry[str(col)] = n if n is not None else _json_safe_value(val)
    return entry


def _build_cohort_table_rows(
    working: pd.DataFrame,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
    sort_stat: str = "HR",
    limit: int = HOF_COHORT_TABLE_ROW_LIMIT,
) -> list[dict[str, Any]]:
    if working is None or working.empty:
        return []
    cols = _export_columns_for_df(working)
    ranked = working.copy()
    if sort_stat in ranked.columns:
        ranked = ranked.sort_values(sort_stat, ascending=False, na_position="last")
    rows: list[dict[str, Any]] = []
    for _, row in ranked.head(limit).iterrows():
        rows.append(_row_to_player_record(row, player_col=player_col, hof_col=hof_col))
    return rows


def _build_cohort_breakdown(
    working: pd.DataFrame,
    *,
    hof_col: str = "isHallOfFamer",
) -> dict[str, Any]:
    total = int(len(working)) if working is not None else 0
    if total == 0 or hof_col not in working.columns:
        return {
            "total_players": total,
            "hall_of_famers": 0,
            "non_hall_of_famers": total,
            "hall_of_fame_rate_pct": 0.0,
        }
    hof_mask = working[hof_col].fillna(False).astype(bool)
    hof_count = int(hof_mask.sum())
    non_hof = total - hof_count
    rate = round(100.0 * hof_count / total, 1) if total else 0.0
    return {
        "total_players": total,
        "hall_of_famers": hof_count,
        "non_hall_of_famers": non_hof,
        "hall_of_fame_rate_pct": rate,
    }


def _build_career_milestones(target_row: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not target_row:
        return []
    hits: list[dict[str, Any]] = []
    for stat, threshold, label in HOF_CAREER_MILESTONES:
        val = _num(target_row.get(stat))
        if val is None:
            continue
        if val >= threshold:
            hits.append(
                {
                    "stat": stat,
                    "threshold": threshold,
                    "value": val,
                    "label": label,
                    "met": True,
                }
            )
    return hits


def _extract_career_stats_block(target_row: dict[str, Any] | None) -> dict[str, Any]:
    if not target_row:
        return {}
    block: dict[str, Any] = {}
    for key in (*HOF_CASE_STAT_KEYS, *HOF_OPTIONAL_ADVANCED_STAT_KEYS):
        if key in target_row:
            block[key] = target_row[key]
    for key in (
        "playerID",
        "fullName",
        "displayPosition",
        "displayTeam",
        "primaryHistoricalTeamName",
        "teamHistoricalName",
        "teamName",
        "careerPrimaryPos",
        "primaryPos",
        "bats",
        "isHallOfFamer",
    ):
        if key in target_row and target_row[key] is not None:
            block[key] = target_row[key]
    return block


def _build_target_identity(
    target: str,
    target_row: dict[str, Any] | None,
    working: pd.DataFrame,
    source_df: pd.DataFrame | None,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "target_player": target,
        "player_id": None,
        "primary_position": _resolve_primary_position(target_row or {}),
        "teams": [],
        "career_span": None,
        "filter_year_range": None,
        "hall_of_fame_member": False,
        "bats": None,
    }
    if target_row:
        pid = target_row.get("playerID")
        if pid is not None and str(pid).strip():
            identity["player_id"] = str(pid).strip()
        identity["hall_of_fame_member"] = bool(target_row.get(hof_col))
        identity["bats"] = target_row.get("bats")
        for team_col in ("displayTeam", "primaryHistoricalTeamName", "teamHistoricalName", "teamName"):
            team = str(target_row.get(team_col) or "").strip()
            if team and team not in identity["teams"]:
                identity["teams"].append(team)

    pid = identity.get("player_id")
    src = source_df if source_df is not None and not source_df.empty else working
    if pid and src is not None and not src.empty and "playerID" in src.columns:
        player_seasons = src[src["playerID"].astype(str).str.strip() == str(pid)]
        if not player_seasons.empty and "yearID" in player_seasons.columns:
            years = pd.to_numeric(player_seasons["yearID"], errors="coerce").dropna()
            if not years.empty:
                identity["career_span"] = {
                    "debut_year": int(years.min()),
                    "final_year": int(years.max()),
                    "seasons": int(years.nunique()),
                }
        if "teamHistoricalName" in player_seasons.columns:
            teams = sorted(
                {
                    str(x).strip()
                    for x in player_seasons["teamHistoricalName"].dropna().unique()
                    if str(x).strip()
                }
            )
            if teams:
                identity["teams"] = teams[:12]
        elif "teamName" in player_seasons.columns:
            teams = sorted({str(x).strip() for x in player_seasons["teamName"].dropna().unique() if str(x).strip()})
            if teams:
                identity["teams"] = teams[:12]
    elif target_row and src is not None and player_col in src.columns:
        player_seasons = src[src[player_col].astype(str).str.strip() == target]
        if not player_seasons.empty and "yearID" in player_seasons.columns:
            years = pd.to_numeric(player_seasons["yearID"], errors="coerce").dropna()
            if not years.empty:
                identity["career_span"] = {
                    "debut_year": int(years.min()),
                    "final_year": int(years.max()),
                    "seasons": int(years.nunique()),
                }
    try:
        from player_photos import get_player_photo_info

        identity["player_photo"] = get_player_photo_info(
            player_id=identity.get("player_id"),
            full_name=target,
            use_api=True,
        )
    except ImportError:
        pass
    return identity


def _comparable_distance(
    target_vec: dict[str, float],
    row: pd.Series,
    stats: list[str],
    scales: dict[str, float],
) -> float | None:
    dist_sq = 0.0
    used = 0
    for stat in stats:
        t_val = target_vec.get(stat)
        r_val = _num(row.get(stat))
        scale = scales.get(stat) or 1.0
        if t_val is None or r_val is None or scale <= 0:
            continue
        diff = (t_val - r_val) / scale
        dist_sq += diff * diff
        used += 1
    if used == 0:
        return None
    return float(dist_sq ** 0.5)


def _find_comparable_players(
    working: pd.DataFrame,
    target: str,
    sort_stat: str,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
    limit: int = HOF_COMPARABLE_PLAYER_LIMIT,
) -> dict[str, list[dict[str, Any]]]:
    empty = {"overall": [], "hall_of_famers": [], "non_hall_of_famers": []}
    if working is None or working.empty or player_col not in working.columns:
        return empty
    stats = _stat_columns_present(working)
    if sort_stat in working.columns and sort_stat not in stats:
        stats = [sort_stat] + stats
    names = working[player_col].astype(str).str.strip()
    target_rows = working[names.eq(target)]
    if target_rows.empty:
        return empty
    target_row = target_rows.iloc[0]
    target_vec = {s: _num(target_row.get(s)) for s in stats}
    target_vec = {k: v for k, v in target_vec.items() if v is not None}
    if not target_vec:
        return empty
    scales: dict[str, float] = {}
    for stat in target_vec:
        series = pd.to_numeric(working[stat], errors="coerce").dropna()
        if series.empty:
            scales[stat] = 1.0
        else:
            scales[stat] = max(float(series.max()), 1.0)

    scored: list[tuple[float, pd.Series]] = []
    for _, row in working.iterrows():
        name = str(row.get(player_col) or "").strip()
        if name == target:
            continue
        dist = _comparable_distance(target_vec, row, list(target_vec.keys()), scales)
        if dist is None:
            continue
        scored.append((dist, row))
    scored.sort(key=lambda item: item[0])

    def _pack(limit_rows: list[tuple[float, pd.Series]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for dist, row in limit_rows[:limit]:
            rec = _row_to_player_record(row, player_col=player_col, hof_col=hof_col)
            rec["comparable_distance"] = round(dist, 4)
            out.append(rec)
        return out

    overall = _pack(scored)
    hof_scored = [(d, r) for d, r in scored if hof_col in r.index and bool(r.get(hof_col))]
    non_scored = [(d, r) for d, r in scored if hof_col not in r.index or not bool(r.get(hof_col))]
    return {
        "overall": overall,
        "hall_of_famers": _pack(hof_scored),
        "non_hall_of_famers": _pack(non_scored),
    }


def build_hof_case_insight_record(
    packet: dict[str, Any],
    *,
    question: str,
    question_id: str = "",
    source_page: str = "Career Totals",
    full_analysis_url: str = "",
    resume_key: str = "",
    ami_prompt: str = "",
) -> dict[str, Any]:
    """Compact Baseball insight card + Command Center publish payload for a HOF case."""
    from applied_math_return_insight import build_submit_fallback_insight, fresh_submit_insight_id
    from hof_case_analysis import resolve_hof_case_analysis

    packet_dict = packet if isinstance(packet, dict) else {}
    analysis = resolve_hof_case_analysis(packet_dict)
    target = str(packet_dict.get("target_player") or "").strip()
    display_q = str(
        question
        or packet_dict.get("hof_case_display_question")
        or build_hof_case_display_question(target, packet_dict)
    ).strip()
    if is_hof_ami_internal_prompt(display_q):
        display_q = build_hof_case_display_question(target, packet_dict)
    insight = build_submit_fallback_insight(
        question=display_q,
        source_app="baseball",
        source_page=str(source_page or "Career Totals").strip() or "Career Totals",
        question_id=str(question_id or "").strip(),
        full_analysis_url=str(full_analysis_url or "").strip(),
        resume_key=str(resume_key or "").strip(),
    )
    thesis = str(analysis.get("thesis") or "").strip()
    summary = str((packet or {}).get("hof_case_summary") or "").strip()
    conclusion = thesis or summary or "Hall of Fame case ready — open full analysis for details."
    data = insight.to_dict()
    data["insight_id"] = fresh_submit_insight_id(
        question_id=str(question_id or "").strip(),
        conclusion=conclusion,
    )
    data["conclusion"] = conclusion
    data["short_answer"] = conclusion
    if display_q:
        data["question"] = display_q
        data["display_question"] = display_q
        data["user_question"] = display_q
    prompt = str(ami_prompt or packet_dict.get("hof_case_ami_prompt") or "").strip()
    if prompt and prompt != display_q:
        data["ami_prompt"] = prompt
    data["method"] = f"{CASE_SCORE_LABEL} — {analysis.get('verdict_bucket', '—')}"
    data["verdict_bucket"] = analysis.get("verdict_bucket")
    data["quant_area"] = "hall_of_fame_case"
    if target:
        data["target_player"] = target
    bullets = list(analysis.get("supporting_points") or [])[:8]
    if bullets:
        data["supporting_points"] = bullets
    if analysis.get("score") is not None:
        data["score"] = analysis.get("score")
    cohort_conf = str(analysis.get("confidence") or "").strip()
    if cohort_conf:
        data["cohort_confidence"] = cohort_conf
        data["confidence_label"] = f"Cohort filter confidence: {cohort_conf}"
        data["confidence"] = cohort_conf
    return data


def build_hof_ami_payload(
    *,
    packet: dict[str, Any],
    question: str,
    question_id: str,
    action_url: str,
    context: dict[str, Any] | None = None,
    insight: dict[str, Any] | None = None,
    workspace_snapshot: dict[str, Any] | None = None,
    source_state: dict[str, Any] | None = None,
    resume_key: str = "",
    ami_prompt: str = "",
) -> dict[str, Any]:
    """Full persisted blob for HOF Case AMI / Open full analysis."""
    ctx = dict(context or {})
    ctx.setdefault("hof_case_packet", copy.deepcopy(packet))
    ctx.setdefault("player", packet.get("target_player"))
    ctx.setdefault("routing_hint", "hof_case_analysis")
    ctx.setdefault("intent", "hof_case_analysis")
    ctx.setdefault("app_context_type", HOF_AMI_CONTEXT_TYPE)
    identity = packet.get("target_identity") if isinstance(packet.get("target_identity"), dict) else {}
    target = str(packet.get("target_player") or identity.get("target_player") or ctx.get("player") or "").strip()
    display_question = str(
        packet.get("hof_case_display_question")
        or build_hof_case_display_question(target, packet)
    ).strip()
    prompt = str(ami_prompt or question or "").strip()
    if prompt and prompt != display_question:
        ctx.setdefault("ami_prompt", prompt)
    if display_question:
        ctx.setdefault("display_question", display_question)
        ctx.setdefault("user_question", display_question)
    payload: dict[str, Any] = {
        "question": display_question or prompt,
        "question_id": str(question_id or "").strip(),
        "source_app": "baseball",
        "source_page": "Career Totals",
        "quant_area": "hall_of_fame_case",
        "context_type": HOF_AMI_CONTEXT_TYPE,
        "app_context_type": HOF_AMI_CONTEXT_TYPE,
        "ami_source_app": HOF_AMI_SOURCE_APP,
        "ami_source_page": HOF_AMI_SOURCE_PAGE,
        "context": ctx,
        "hof_case_packet": copy.deepcopy(packet),
        "action_url": str(action_url or "").strip(),
        "player": target,
        "target_player": target,
    }
    if target:
        payload["target_player_name"] = target
    if prompt:
        payload["ami_prompt"] = prompt
    if display_question:
        payload["display_question"] = display_question
    if identity.get("player_id"):
        payload["player_id"] = identity["player_id"]
    if insight:
        payload["insight"] = copy.deepcopy(insight)
        ctx["insight_summary"] = {
            "conclusion": insight.get("conclusion"),
            "method": insight.get("method"),
            "short_answer": insight.get("short_answer"),
            "supporting_points": insight.get("supporting_points") or insight.get("bullets"),
            "confidence": insight.get("confidence"),
            "score": insight.get("score"),
        }
    try:
        from hof_case_analysis import resolve_hof_case_analysis

        analysis = resolve_hof_case_analysis(packet)
    except ImportError:
        analysis = packet.get("hof_case_analysis") if isinstance(packet.get("hof_case_analysis"), dict) else {}
        if not analysis:
            try:
                from hof_case_analysis import compose_hof_statistical_case

                analysis = compose_hof_statistical_case(packet)
            except ImportError:
                analysis = {}
    verdict: dict[str, Any] = {
        "hof_case_summary": packet.get("hof_case_summary"),
        "score_label": packet.get("score_label"),
        "score_buckets": packet.get("score_buckets"),
        "recommendation": analysis.get("recommendation") or (insight or {}).get("conclusion") or (insight or {}).get("short_answer"),
        "supporting_points": analysis.get("supporting_points") or (insight or {}).get("supporting_points") or (insight or {}).get("bullets"),
        "confidence": analysis.get("confidence") or (insight or {}).get("confidence"),
        "score": analysis.get("score") or (insight or {}).get("score"),
        "verdict_bucket": analysis.get("verdict_bucket"),
        "thesis": analysis.get("thesis"),
        "case_memo": analysis.get("case_memo"),
        "disclaimer": analysis.get("disclaimer"),
    }
    payload["verdict_context"] = {k: v for k, v in verdict.items() if v not in (None, "", [], {})}
    if workspace_snapshot:
        payload["workspace_snapshot"] = copy.deepcopy(workspace_snapshot)
        payload["workspace_snapshot_present"] = True
        if resume_key:
            payload["workspace_snapshot_ref"] = str(resume_key).strip()
    if source_state:
        payload["source_state"] = copy.deepcopy(source_state)
    if resume_key:
        payload["resume_key"] = str(resume_key).strip()
    payload["hof_ami_audit"] = audit_hof_ami_blob(payload)
    return payload


def audit_hof_ami_blob(blob: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize HOF AMI blob completeness for developer diagnostics."""
    if not isinstance(blob, dict):
        return {"valid": False, "blob_keys": [], "counts": {}}
    packet = blob.get("hof_case_packet")
    if not isinstance(packet, dict):
        packet = (blob.get("context") or {}).get("hof_case_packet") if isinstance(blob.get("context"), dict) else {}
    if not isinstance(packet, dict):
        packet = {}
    insight = blob.get("insight") if isinstance(blob.get("insight"), dict) else {}
    ctx = blob.get("context") if isinstance(blob.get("context"), dict) else {}
    cohort_rows = packet.get("cohort_table_rows") or packet.get("result_sample") or []
    comparables = packet.get("comparable_players") if isinstance(packet.get("comparable_players"), dict) else {}
    awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    position_ctx = packet.get("position_context") if isinstance(packet.get("position_context"), dict) else {}
    counts = {
        "cohort_rows": len(cohort_rows) if isinstance(cohort_rows, list) else 0,
        "comparable_overall": len(comparables.get("overall") or []),
        "comparable_hof": len(comparables.get("hall_of_famers") or []),
        "comparable_non_hof": len(comparables.get("non_hall_of_famers") or []),
        "position_rank_stats": len(position_ctx.get("position_stat_ranks") or {}),
        "cohort_rank_stats": len(packet.get("target_cohort_ranks") or {}),
        "milestone_flags": len(packet.get("career_milestones") or []),
        "awards_entries": int(awards.get("total_award_count") or 0) if awards.get("data_available") else 0,
        "insight_fields": len([k for k, v in insight.items() if v not in (None, "", [], {})]),
        "workspace_snapshot_keys": len(blob.get("workspace_snapshot") or {}),
    }
    return {
        "valid": True,
        "blob_keys": sorted(blob.keys()),
        "context_keys": sorted(ctx.keys()) if isinstance(ctx, dict) else [],
        "packet_keys": sorted(packet.keys()) if isinstance(packet, dict) else [],
        "counts": counts,
        "has_target_player_stats": bool(
            packet.get("career_stats_full") or packet.get("target_career_stats") or packet.get("target_player_row")
        ),
        "has_cohort_rows": counts["cohort_rows"] > 0,
        "has_position_ranks": counts["position_rank_stats"] > 0,
        "has_comparable_players": (
            counts["comparable_overall"] > 0
            or counts["comparable_hof"] > 0
            or counts["comparable_non_hof"] > 0
        ),
        "has_awards": awards.get("data_available") is True,
        "has_insight": bool(insight),
        "has_action_url": bool(str(blob.get("action_url") or "").strip()),
        "has_workspace_snapshot": bool(blob.get("workspace_snapshot")),
        "question_id": str(blob.get("question_id") or ""),
        "context_type": str(blob.get("context_type") or blob.get("app_context_type") or ""),
        "target_player": str(blob.get("target_player") or packet.get("target_player") or ""),
        "player_id": (packet.get("target_identity") or {}).get("player_id") if isinstance(packet.get("target_identity"), dict) else None,
    }


def render_hof_ami_blob_diagnostics(
    st: Any,
    blob: dict[str, Any] | None,
    *,
    expanded: bool = False,
    developer_mode: bool = False,
) -> None:
    """Developer panel: HOF AMI blob keys and completeness checks."""
    if not developer_mode:
        return
    audit = audit_hof_ami_blob(blob)
    with st.expander("Developer: HOF AMI blob audit", expanded=expanded):
        st.json(audit)


def build_hof_case_packet(
    target_player: str,
    results_df: pd.DataFrame,
    *,
    filters_summary: dict[str, Any],
    sort_stat: str,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
    awards_df: pd.DataFrame | None = None,
    awards_fallback_df: pd.DataFrame | None = None,
    position_universe_df: pd.DataFrame | None = None,
    source_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build cohort packet for Baseball AMI Hall of Fame Case Mode."""
    target = str(target_player or "").strip()
    working = results_df.copy() if results_df is not None else pd.DataFrame()
    total = int(len(working))
    if hof_col in working.columns:
        hof_mask = working[hof_col].fillna(False).astype(bool)
        hof_count = int(hof_mask.sum())
    else:
        hof_count = 0
    hof_rate = round(100.0 * hof_count / total, 1) if total else 0.0

    rank: int | None = None
    target_row: dict[str, Any] | None = None
    if total and player_col in working.columns and sort_stat in working.columns:
        ranked = working.sort_values(sort_stat, ascending=False, na_position="last").reset_index(drop=True)
        names = ranked[player_col].astype(str).str.strip()
        match = names.eq(target)
        if match.any():
            idx = int(match.idxmax())
            rank = idx + 1
            row = ranked.iloc[idx]
            target_row = _json_safe_row(row)

    sample_cols = [
        c
        for c in (
            player_col,
            sort_stat,
            hof_col,
            "displayPosition",
            "Primary Position",
            "G",
            "HR",
            "H",
            "RBI",
            "R",
            "2B",
            "OPS",
        )
        if c in working.columns
    ]
    sample: list[dict[str, Any]] = []
    if sample_cols and total:
        top = working.sort_values(sort_stat, ascending=False, na_position="last").head(12)
        for _, row in top.iterrows():
            entry: dict[str, Any] = {}
            for col in sample_cols:
                val = row.get(col)
                if col == player_col:
                    entry["player"] = decorate_player_name(val, row.get(hof_col))
                elif col == hof_col:
                    entry["hall_of_famer"] = bool(val)
                else:
                    n = _num(val)
                    entry[col] = n if n is not None else val
            sample.append(entry)

    awards_context: dict[str, Any] = {
        "target_awards_summary": {"data_available": False, "message": "Awards data unavailable."},
        "cohort_awards_summary": {"data_available": False, "message": "Awards data unavailable."},
        "target_award_rank": {"data_available": False},
        "cohort_award_comparison": {"data_available": False, "message": "Awards data unavailable."},
    }
    try:
        from awards_players_data import build_hof_case_awards_context

        awards_context = build_hof_case_awards_context(
            target, working, awards_df, fallback_df=awards_fallback_df
        )
    except ImportError:
        pass

    cohort_stats = _build_cohort_stat_context(working, target, player_col=player_col)
    cohort_selectivity = _assess_cohort_selectivity(
        filters_summary,
        total=total,
        hof_rate=hof_rate,
        sort_stat=str(sort_stat or ""),
    )
    position_universe = position_universe_df
    if position_universe is None and awards_fallback_df is not None:
        position_universe = _aggregate_position_universe(awards_fallback_df, player_col=player_col)
    position_context = _build_position_hof_context(
        target,
        target_row,
        position_universe,
        player_col=player_col,
    )
    primary_position = position_context.get("primary_position") or _resolve_primary_position(target_row or {})
    career_stats_full = _extract_career_stats_block(target_row)
    career_milestones = _build_career_milestones(target_row)
    cohort_table_rows = _build_cohort_table_rows(
        working,
        player_col=player_col,
        hof_col=hof_col,
        sort_stat=str(sort_stat or "HR"),
    )
    cohort_breakdown = _build_cohort_breakdown(working, hof_col=hof_col)
    comparable_players = _find_comparable_players(
        working,
        target,
        str(sort_stat or "HR"),
        player_col=player_col,
        hof_col=hof_col,
    )
    target_identity = _build_target_identity(
        target,
        target_row,
        working,
        source_df,
        player_col=player_col,
        hof_col=hof_col,
    )

    packet = {
        "mode": "hall_of_fame_case",
        "score_label": CASE_SCORE_LABEL,
        "score_buckets": list(CASE_SCORE_BUCKETS),
        "disclaimer": hof_case_disclaimer_text(),
        "target_player": target,
        "target_identity": target_identity,
        "primary_position": primary_position,
        "target_in_results": rank is not None,
        "target_rank": rank,
        "total_players_returned": total,
        "hall_of_famers_returned": hof_count,
        "hall_of_fame_rate_pct": hof_rate,
        "cohort_breakdown": cohort_breakdown,
        "sort_stat": str(sort_stat or ""),
        "filters_used": filters_summary,
        "target_player_row": target_row,
        "target_career_stats": target_row,
        "career_stats_full": career_stats_full,
        "career_milestones": career_milestones,
        "result_sample": sample,
        "cohort_table_rows": cohort_table_rows,
        "comparable_players": comparable_players,
        "cohort_stat_summaries": cohort_stats.get("cohort_stat_summaries"),
        "target_cohort_ranks": cohort_stats.get("target_cohort_ranks"),
        "cohort_strength_stats": cohort_stats.get("cohort_strength_stats"),
        "cohort_weakness_stats": cohort_stats.get("cohort_weakness_stats"),
        "cohort_selectivity": cohort_selectivity,
        "position_context": position_context,
        "position_stat_ranks": position_context.get("position_stat_ranks"),
        "position_percentiles": position_context.get("position_percentiles"),
        "position_rarity_findings": position_context.get("position_rarity_findings"),
        "target_awards_summary": awards_context.get("target_awards_summary"),
        "cohort_awards_summary": awards_context.get("cohort_awards_summary"),
        "target_award_rank": awards_context.get("target_award_rank"),
        "cohort_award_comparison": awards_context.get("cohort_award_comparison"),
    }
    packet["hof_case_summary"] = build_hof_case_summary_line(packet)
    packet["hof_case_display_question"] = build_hof_case_display_question(target, packet)
    packet["hof_case_ami_prompt"] = build_hof_case_ami_prompt(target, packet)
    packet["disclaimer"] = hof_case_disclaimer_text(packet)
    try:
        from hof_case_analysis import compose_hof_statistical_case

        packet["hof_case_analysis"] = compose_hof_statistical_case(packet)
        if isinstance(packet.get("hof_case_analysis"), dict):
            packet["hof_case_analysis"]["disclaimer"] = packet["disclaimer"]
    except ImportError:
        pass
    return packet


def build_hof_case_display_question(target_player: str, packet: dict[str, Any] | None = None) -> str:
    """User-facing question for insight cards and Applied Math UI."""
    target = str(target_player or (packet or {}).get("target_player") or "").strip()
    if not target:
        return "How strong is this player's Hall of Fame case?"
    return f"How strong is {target}'s Hall of Fame case?"


def build_hof_case_ami_prompt(target_player: str, packet: dict[str, Any]) -> str:
    """Internal AMI instruction prompt — not shown as the user Question field."""
    target = str(target_player or packet.get("target_player") or "").strip()
    total = packet.get("total_players_returned", 0)
    hof_n = packet.get("hall_of_famers_returned", 0)
    rate = packet.get("hall_of_fame_rate_pct", 0)
    rank = packet.get("target_rank")
    rank_line = f" Target ranks #{rank} in this cohort by {packet.get('sort_stat', 'sort stat')}." if rank else ""
    awards_line = ""
    comparison = packet.get("cohort_award_comparison") if isinstance(packet.get("cohort_award_comparison"), dict) else {}
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    if comparison.get("data_available") and target_awards.get("data_available"):
        awards_line = (
            f" Target has {comparison.get('target_total_awards', 0)} total awards "
            f"({comparison.get('target_major_awards', 0)} major); "
            f"{comparison.get('players_with_more_total_awards', 0)} cohort players have more total awards."
        )
    return (
        f"Hall of Fame Case Mode — assign a {CASE_SCORE_LABEL} for {target}. "
        f"Build a full statistical argument from hof_case_packet: career totals, best and weak categories, "
        f"position-relative ranks, era/career span, awards (analyze target_awards_summary and cohort_award_comparison), "
        f"milestones, comparables, and cohort selectivity. "
        f"The Career Totals search returned {total} players with {hof_n} Hall of Famers ({rate}% HOF rate).{rank_line}{awards_line} "
        f"Interpret filters — do not judge the case by the filtered sort stat alone if other categories are stronger. "
        f"Distinguish evidence (milestones, awards, position excellence, high cohort HOF rate) from cohort context "
        f"(handedness, switch hitters, year windows, narrow demographic filters). "
        f"Respond with one of: {', '.join(CASE_SCORE_BUCKETS)}. "
        f"Do NOT present this as true Hall of Fame induction odds."
    )


def build_hof_case_question(target_player: str, packet: dict[str, Any] | None = None) -> str:
    """Alias for the user-facing display question."""
    return build_hof_case_display_question(target_player, packet)


def hof_case_ami_guidance() -> str:
    return (
        "Hall of Fame Case Mode: read hof_case_packet only. "
        f"Assign a {CASE_SCORE_LABEL} using labels {', '.join(CASE_SCORE_BUCKETS)}. "
        "This is a statistical case — not true induction odds or a guaranteed probability.\n\n"
        "Required output sections (use these headings):\n"
        "1. Summary Judgment — one paragraph on the statistical case.\n"
        "2. Statistical Cohort Strength — interpret cohort_breakdown, hall_of_fame_rate_pct, "
        "cohort_selectivity, filters_used thresholds (e.g., 500+ HR, 3,000 hits), and cohort_table_rows.\n"
        "3. Target Player's Standing in the Cohort — use target_identity, career_stats_full, "
        "target_player_row, target_cohort_ranks, cohort_strength_stats, cohort_weakness_stats, "
        "and career_milestones. Explain where the target ranks on HR, hits, RBI, OPS, etc.\n"
        "4. Comparable Players — use comparable_players (overall, hall_of_famers, non_hall_of_famers) "
        "to contrast the target with statistically similar peers.\n"
        "5. Position-Based Hall of Fame Case — use primary_position, position_context, "
        "position_stat_ranks, position_percentiles, and position_rarity_findings. "
        "Explain whether the totals are exceptional for that position.\n"
        "6. Awards / Accolades Analysis — explicitly analyze target_awards_summary, cohort_awards_summary, "
        "target_award_rank, and cohort_award_comparison. Weave awards into the Hall of Fame argument: "
        "explain how MVP/Cy Young/Gold Glove hardware supports or limits the case versus cohort peers. "
        "Do not merely list awards — interpret their weight for this candidate as supporting evidence.\n"
        "7. Reasons the Case Is Strong — bullet points grounded in stats, milestones, and cohort position.\n"
        "8. Reasons for Caution — limitations, broad cohorts, below-average awards, position norms.\n"
        f"9. {CASE_SCORE_LABEL} — final bucket with brief justification.\n\n"
        "Also use insight / verdict_context when present for page-generated summary and recommendation bullets. "
        "Interpret the baseball statistics themselves — not just the cohort HOF percentage. "
        "Distinguish signal from coincidence: HR ≥ 400, 3,000 hits, MVP-level awards, and position-relative "
        "excellence are meaningful evidence; left/right/switch handedness, arbitrary year ranges, and narrow "
        "demographic filters define the comparison group but are not Hall quality evidence by themselves. "
        "Separate 'evidence that strengthens the case' from 'context that merely defines the cohort'. "
        "Never say '90% chance of making the Hall of Fame', 'true induction odds', or 'guaranteed probability'. "
        "Use terms like 'statistical case', 'cohort strength', and 'supporting awards evidence'."
    )


def player_in_results(target_player: str, results_df: pd.DataFrame, *, player_col: str = "fullName") -> bool:
    target = str(target_player or "").strip()
    if not target or results_df is None or results_df.empty or player_col not in results_df.columns:
        return False
    names = results_df[player_col].astype(str).str.strip()
    return bool(names.eq(target).any())
