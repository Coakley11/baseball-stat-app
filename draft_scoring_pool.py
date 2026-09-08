"""Live Draft player pool columns — compact shared-room serialization + scoring safety."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Columns used by live_draft_recommendations, apply_draft_pick_scoring, manual draft
# sorting, scarcity/positional fit, sleeper/value, and availability-at-next-pick logic.
LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS: tuple[str, ...] = (
    # Identity / eligibility
    "playerID",
    "fullName",
    "Primary Position",
    "Team",
    "Age",
    "Eligible Positions",
    # Core ranks / value
    "Expected Fantasy Value",
    "Model Rank",
    "Market Rank",
    "Fantasy Edge",
    # Market / pick cost / availability inputs
    "ADP",
    "ADP Rank",
    "FantasyPros Rank",
    "Expert Avg Rank",
    "Expert Std Dev",
    # Sleeper / value / confidence signals
    "Sleeper Score",
    "Scarcity Score",
    "Projection Confidence Score",
    "ML Adjustment",
    "ML Projection Score",
    "App Ranking Score",
    "Market vs Model Score",
    "Trend Signal",
    "Capped Fantasy Edge",
    "Best Player Available Score",
    "Best Value Sleeper Score",
    # Category-need projections (roto / points)
    "proj_HR",
    "proj_RBI",
    "proj_R",
    "proj_SB",
    "proj_BA",
    "proj_OPS",
    "proj_BB",
    "AB",
    "G",
)

# Backward-compatible alias used by shared-room compact serialization.
SHARED_DRAFT_POOL_COLUMNS = LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS

_RANK_DEFAULT = 9999.0
_SCORING_FALLBACK_DEFAULTS: dict[str, float | str] = {
    "Expected Fantasy Value": 0.0,
    "Fantasy Edge": 0.0,
    "Model Rank": _RANK_DEFAULT,
    "Market Rank": _RANK_DEFAULT,
    "Expert Std Dev": 0.0,
    "Sleeper Score": 0.0,
    "Scarcity Score": 0.0,
    "ML Adjustment": 0.0,
    "Projection Confidence Score": 0.5,
    "Primary Position": "",
    "Trend Signal": 0.0,
    "App Ranking Score": 0.0,
    "Market vs Model Score": 0.0,
}

# Pool value-signal classification for fast Solo vs full projection pools.
POOL_KIND_VALID_PROJECTION = "VALID_PROJECTION_POOL"
POOL_KIND_FAST_MARKET_FALLBACK = "FAST_MARKET_FALLBACK_POOL"
POOL_VALUE_KIND_KEY = "_draft_pool_value_kind"


SCORING_TRACE_COLUMNS: tuple[str, ...] = (
    "Expected Fantasy Value",
    "Model Rank",
    "Market Rank",
    "Fantasy Edge",
    "ADP Rank",
    "ADP",
    "Sleeper Score",
)

DEFAULT_SCORING_TRACE_PLAYERS: tuple[str, ...] = (
    "Aaron Judge",
    "Shohei Ohtani",
    "Juan Soto",
)


def trace_player_scoring(
    pool: pd.DataFrame | None,
    player_names: tuple[str, ...] | list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Snapshot scoring fields for acceptance players (dev / stabilization)."""
    names = tuple(player_names or DEFAULT_SCORING_TRACE_PLAYERS)
    out: dict[str, dict[str, Any]] = {}
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty or "fullName" not in pool.columns:
        return {name: {"found": False} for name in names}
    work = pool.copy()
    work["_trace_name"] = work["fullName"].astype(str).str.strip()
    for name in names:
        rows = work[work["_trace_name"].str.casefold() == str(name).strip().casefold()]
        if rows.empty:
            out[name] = {"found": False}
            continue
        row = rows.iloc[0]
        fields: dict[str, Any] = {"found": True, "playerID": str(row.get("playerID") or "")}
        for col in SCORING_TRACE_COLUMNS:
            if col in row.index:
                val = row.get(col)
                try:
                    if pd.isna(val):
                        fields[col] = None
                    elif isinstance(val, (int, float)):
                        fields[col] = float(val)
                    else:
                        fields[col] = val
                except Exception:
                    fields[col] = val
        out[name] = fields
    return out


def _series_is_default(col: pd.Series, default: float | str) -> pd.Series:
    numeric = pd.to_numeric(col, errors="coerce")
    if col.dtype == object and not numeric.notna().any():
        return col.fillna("").astype(str).eq(str(default))
    if isinstance(default, float):
        return numeric.isna() | numeric.eq(float(default))
    return numeric.isna() | col.fillna("").astype(str).eq(str(default))


def _bad_rank_mask(series: pd.Series) -> pd.Series:
    nums = pd.to_numeric(series, errors="coerce")
    return nums.isna() | nums.ge(_RANK_DEFAULT)


def _efv_series_is_unusable(series: pd.Series | None) -> bool:
    """True when EFV is missing, all-zero, constant, or otherwise non-informative."""
    if series is None:
        return True
    nums = pd.to_numeric(series, errors="coerce")
    if not nums.notna().any():
        return True
    filled = nums.dropna()
    if filled.empty:
        return True
    if float(filled.max()) == 0.0 and float(filled.min()) == 0.0:
        return True
    # Constant across a multi-row pool cannot drive ranking. A single-row
    # constant is fine (fixtures / one-player restores).
    if len(filled) > 1 and int(filled.nunique(dropna=True)) <= 1:
        return True
    return False


def _model_rank_series_is_degenerate(series: pd.Series | None) -> bool:
    """True when Model Rank is sentinel, missing, or collapsed to one value."""
    if series is None:
        return True
    nums = pd.to_numeric(series, errors="coerce")
    if not nums.notna().any():
        return True
    if bool(_bad_rank_mask(nums).all()):
        return True
    usable = nums[~_bad_rank_mask(nums)]
    if usable.empty:
        return True
    # All players sharing one Model Rank (e.g. every row = 1) is non-informative.
    if len(usable) > 1 and int(usable.nunique(dropna=True)) <= 1:
        return True
    return False


def _market_rank_proxy_efv(market_rank: pd.Series, *, n_rows: int) -> pd.Series:
    """Historical fast-pool EFV proxy: higher value for better (lower) market ranks."""
    rank = pd.to_numeric(market_rank, errors="coerce").fillna(float(n_rows))
    # Use the larger of pool size vs max observed market rank so absolute ADP
    # ranks (e.g. 350 in a short fixture) still produce an informative spread.
    observed = float(rank.max()) if rank.notna().any() else float(n_rows)
    ceiling = max(float(n_rows), observed)
    return (ceiling + 1.0 - rank).clip(lower=1.0)


def _fill_bad_rows(
    out: pd.DataFrame,
    col: str,
    values: pd.Series,
    *,
    bad: pd.Series,
    report: dict[str, Any],
    derived_name: str | None = None,
) -> None:
    if not bad.any():
        return
    out.loc[bad, col] = values.loc[bad]
    if derived_name:
        derived = report.setdefault("derived_columns", [])
        if derived_name not in derived:
            derived.append(derived_name)


def count_scoring_value_quality(pool: pd.DataFrame | None) -> dict[str, dict[str, int]]:
    """Count real vs default-filled values for rank/edge columns."""
    out: dict[str, dict[str, int]] = {}
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty:
        return out
    checks: tuple[tuple[str, float | str], ...] = (
        ("Model Rank", _RANK_DEFAULT),
        ("Market Rank", _RANK_DEFAULT),
        ("Fantasy Edge", 0.0),
    )
    n = len(pool)
    for col, default in checks:
        if col not in pool.columns:
            out[col] = {"real": 0, "default": n, "missing_column": n}
            continue
        default_mask = _series_is_default(pool[col], default)
        default_n = int(default_mask.sum())
        out[col] = {"real": n - default_n, "default": default_n}
    return out


def prepare_pool_for_compact_serialization(
    pool: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Ensure scoring columns exist before compact shared-room serialization."""
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty:
        return pd.DataFrame(), {"source_columns": [], "compact_columns": []}
    source_columns = [str(c) for c in pool.columns]
    prepared, report = _ensure_draft_scoring_pool_columns(pool, mutate=True)
    compact_columns = select_live_draft_compact_columns(prepared)
    report["source_columns"] = source_columns
    report["source_column_count"] = len(source_columns)
    report["compact_columns"] = compact_columns
    report["compact_column_count"] = len(compact_columns)
    report["scoring_quality"] = count_scoring_value_quality(prepared)
    return prepared, report


def select_live_draft_compact_columns(frame: pd.DataFrame) -> list[str]:
    """Columns to keep for compact shared-room pool — required scoring cols present in frame."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    present = [str(c) for c in frame.columns]
    keep = [c for c in LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS if c in present]
    # Preserve column order from the source frame for any extra required hits.
    ordered = [c for c in present if c in keep]
    return ordered


def analyze_compact_pool(
    pool: pd.DataFrame | None,
    *,
    source_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Diagnostics for compact pool column coverage and default-filled scoring fields."""
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty:
        return {
            "pool_count": 0,
            "compact_columns": [],
            "missing_required": list(LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS),
            "default_filled_counts": {},
            "derived_columns": [],
        }

    src_cols = source_columns if source_columns is not None else [str(c) for c in pool.columns]
    prepared, prep_report = prepare_pool_for_compact_serialization(pool)
    compact_cols = prep_report.get("compact_columns") or select_live_draft_compact_columns(prepared)
    missing = [c for c in LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS if c not in src_cols]
    _, report = _ensure_draft_scoring_pool_columns(prepared, mutate=False)
    return {
        "pool_count": len(pool),
        "source_columns": src_cols,
        "source_column_count": len(src_cols),
        "compact_columns": compact_cols,
        "compact_column_count": len(compact_cols),
        "missing_required": missing,
        "default_filled_counts": report.get("default_filled_counts") or {},
        "derived_columns": report.get("derived_columns") or prep_report.get("derived_columns") or [],
        "scoring_quality": prep_report.get("scoring_quality") or count_scoring_value_quality(prepared),
    }


def ensure_draft_scoring_pool_columns(pool: pd.DataFrame | None) -> pd.DataFrame:
    """Fill missing draft-scoring columns only when truly absent; never overwrite real values."""
    df, _report = _ensure_draft_scoring_pool_columns(pool, mutate=True)
    return df


def ensure_draft_scoring_pool_columns_with_report(
    pool: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df, report = _ensure_draft_scoring_pool_columns(pool, mutate=True)
    return df, report


def _ensure_draft_scoring_pool_columns(
    pool: pd.DataFrame | None,
    *,
    mutate: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    report: dict[str, Any] = {
        "default_filled_counts": {},
        "derived_columns": [],
    }
    if pool is None:
        return pd.DataFrame(), report
    if not isinstance(pool, pd.DataFrame) or pool.empty:
        return pool.copy() if isinstance(pool, pd.DataFrame) else pd.DataFrame(), report

    out = pool if mutate else pool.copy()
    report["pool_value_kind"] = POOL_KIND_VALID_PROJECTION

    if "Market Rank" not in out.columns:
        out["Market Rank"] = pd.NA
    market_bad = _bad_rank_mask(out["Market Rank"])
    if market_bad.any():
        if "ADP Rank" in out.columns:
            _fill_bad_rows(
                out,
                "Market Rank",
                pd.to_numeric(out["ADP Rank"], errors="coerce"),
                bad=market_bad,
                report=report,
                derived_name="Market Rank",
            )
            market_bad = _bad_rank_mask(out["Market Rank"])
        if market_bad.any() and "ADP" in out.columns:
            _fill_bad_rows(
                out,
                "Market Rank",
                pd.to_numeric(out["ADP"], errors="coerce"),
                bad=market_bad,
                report=report,
                derived_name="Market Rank",
            )
            market_bad = _bad_rank_mask(out["Market Rank"])
        if market_bad.any() and "FantasyPros Rank" in out.columns:
            _fill_bad_rows(
                out,
                "Market Rank",
                pd.to_numeric(out["FantasyPros Rank"], errors="coerce"),
                bad=market_bad,
                report=report,
                derived_name="Market Rank",
            )

    # --- Expected Fantasy Value hygiene ---
    # An all-zero / constant EFV column is not "present projections" — rebuild from
    # Market Rank (historical fast Solo intent) so Decision Score retains a value signal.
    if "Expected Fantasy Value" not in out.columns:
        out["Expected Fantasy Value"] = pd.NA
    efv_unusable = _efv_series_is_unusable(out["Expected Fantasy Value"])
    used_market_proxy_efv = False
    if efv_unusable:
        market = pd.to_numeric(out["Market Rank"], errors="coerce")
        if market.notna().any() and not bool(_bad_rank_mask(market).all()):
            proxy = _market_rank_proxy_efv(market, n_rows=len(out))
            out["Expected Fantasy Value"] = proxy
            report["derived_columns"].append("Expected Fantasy Value")
            report["default_filled_counts"]["Expected Fantasy Value"] = int(len(out))
            report["pool_value_kind"] = POOL_KIND_FAST_MARKET_FALLBACK
            report["efv_repair"] = "market_rank_proxy"
            used_market_proxy_efv = True
        else:
            report["efv_repair"] = "unavailable"
            report["pool_value_kind"] = POOL_KIND_FAST_MARKET_FALLBACK

    # --- Model Rank hygiene ---
    if "Model Rank" not in out.columns:
        out["Model Rank"] = pd.NA
    model_bad = _bad_rank_mask(out["Model Rank"])
    if model_bad.any() and "App Rank" in out.columns:
        _fill_bad_rows(
            out,
            "Model Rank",
            pd.to_numeric(out["App Rank"], errors="coerce"),
            bad=model_bad,
            report=report,
            derived_name="Model Rank",
        )
        model_bad = _bad_rank_mask(out["Model Rank"])

    efv_now = pd.to_numeric(out["Expected Fantasy Value"], errors="coerce")
    efv_usable_now = not _efv_series_is_unusable(efv_now)
    market_now = pd.to_numeric(out["Market Rank"], errors="coerce")
    market_usable = market_now.notna().any() and not bool(_bad_rank_mask(market_now).all())

    # Fast market fallback: keep Model Rank on the same absolute scale as Market Rank.
    # Dense-ranking proxy EFV to 1..n while Market Rank stays at ADP scale (e.g. 359)
    # recreates Market−1-style Fantasy Edge artifacts for deep-ADP players.
    if used_market_proxy_efv and market_usable:
        out["Model Rank"] = market_now
        if "Model Rank" not in report.get("derived_columns", []):
            report.setdefault("derived_columns", []).append("Model Rank")
        report["model_rank_repair"] = "aligned_to_market_rank"
        report["pool_value_kind"] = POOL_KIND_FAST_MARKET_FALLBACK
    else:
        if model_bad.any() and efv_usable_now:
            model_rank = efv_now.rank(ascending=False, method="min")
            _fill_bad_rows(
                out,
                "Model Rank",
                model_rank,
                bad=model_bad,
                report=report,
                derived_name="Model Rank",
            )
            model_bad = _bad_rank_mask(out["Model Rank"])

        # Collapsed Model Rank (e.g. all 1 from ranking all-zero EFV) is not meaningful.
        if _model_rank_series_is_degenerate(out["Model Rank"]):
            if efv_usable_now:
                out["Model Rank"] = efv_now.rank(ascending=False, method="min")
                if "Model Rank" not in report.get("derived_columns", []):
                    report.setdefault("derived_columns", []).append("Model Rank")
                report["model_rank_repair"] = "efv_rank"
            elif market_usable:
                out["Model Rank"] = market_now
                if "Model Rank" not in report.get("derived_columns", []):
                    report.setdefault("derived_columns", []).append("Model Rank")
                report["model_rank_repair"] = "aligned_to_market_rank"
                report["pool_value_kind"] = POOL_KIND_FAST_MARKET_FALLBACK
            else:
                report["model_rank_repair"] = "unresolved_degenerate"

    # --- Fantasy Edge ---
    # Only Market−Model when Model Rank is meaningful and on a comparable scale.
    # Fast market-proxy pools intentionally neutralize Edge (Model aligned to Market).
    model_meaningful = not _model_rank_series_is_degenerate(
        out["Model Rank"] if "Model Rank" in out.columns else None
    )
    if used_market_proxy_efv or report.get("pool_value_kind") == POOL_KIND_FAST_MARKET_FALLBACK:
        out["Fantasy Edge"] = 0.0
        report["fantasy_edge_repair"] = "neutral_fast_market_fallback"
        if "Fantasy Edge" not in report.get("derived_columns", []):
            report.setdefault("derived_columns", []).append("Fantasy Edge")
    elif (
        model_meaningful
        and "Market Rank" in out.columns
        and "Model Rank" in out.columns
    ):
        market = pd.to_numeric(out["Market Rank"], errors="coerce")
        model = pd.to_numeric(out["Model Rank"], errors="coerce")
        computed_edge = (market - model).fillna(0.0)
        # Always align Edge to ranks so prior Market−1 artifacts cannot persist
        # after Model Rank repair.
        out["Fantasy Edge"] = computed_edge
        if "Fantasy Edge" not in report.get("derived_columns", []):
            report.setdefault("derived_columns", []).append("Fantasy Edge")
        report["fantasy_edge_repair"] = "from_market_minus_model"
    else:
        out["Fantasy Edge"] = 0.0
        report["fantasy_edge_repair"] = "neutralized_invalid_model"
        if "Fantasy Edge" not in report.get("derived_columns", []):
            report.setdefault("derived_columns", []).append("Fantasy Edge")

    if "Primary Position" not in out.columns:
        out["Primary Position"] = ""
    _pos = out["Primary Position"].fillna("").astype(str).str.strip()
    _pos_bad = _pos.eq("") | _pos.str.upper().isin({"UTIL", "NA", "NAN", "NONE", "NULL", "-"})
    if _pos_bad.any():
        derived = pd.Series("", index=out.index, dtype=object)
        for src_col in ("ADP Position", "FantasyPros Position", "Position", "Eligible Positions"):
            if src_col not in out.columns:
                continue
            still = derived.eq("") & _pos_bad
            if not still.any():
                break
            try:
                from live_draft_roster_slots import _split_position_tokens

                for ix in out.index[still]:
                    toks = [
                        t
                        for t in _split_position_tokens(out.at[ix, src_col])
                        if t and t != "UTIL"
                    ]
                    if toks:
                        derived.at[ix] = toks[0]
            except ImportError:
                raw = out.loc[still, src_col].fillna("").astype(str)
                derived.loc[still] = raw.str.replace(r"\d+$", "", regex=True).str.split(
                    r"[,/\+]", regex=True
                ).str[0].str.strip().str.upper()
        fill_mask = _pos_bad & derived.astype(str).str.strip().ne("")
        if fill_mask.any():
            out.loc[fill_mask, "Primary Position"] = derived.loc[fill_mask].astype(str)
            report["derived_columns"].append("Primary Position")
            report["default_filled_counts"]["Primary Position"] = int(fill_mask.sum())

    for col, default in _SCORING_FALLBACK_DEFAULTS.items():
        if col not in out.columns:
            out[col] = default
            report["default_filled_counts"][col] = len(out)
            continue
        if col in ("Model Rank", "Market Rank"):
            bad = _bad_rank_mask(out[col])
        elif col == "Fantasy Edge":
            bad = pd.to_numeric(out[col], errors="coerce").isna()
        elif col == "Expected Fantasy Value":
            # Never re-default repaired/proxy EFV to 0; only fill true NaNs.
            bad = pd.to_numeric(out[col], errors="coerce").isna()
        elif col == "Primary Position":
            s = out[col].fillna("").astype(str).str.strip()
            bad = s.eq("")  # UTIL may remain when no richer source exists
        else:
            bad = pd.to_numeric(out[col], errors="coerce").isna()
        if bad.any():
            out.loc[bad, col] = default
            report["default_filled_counts"][col] = int(bad.sum())

    # Final classification for callers / diagnostics.
    if report.get("pool_value_kind") != POOL_KIND_FAST_MARKET_FALLBACK:
        if _efv_series_is_unusable(out.get("Expected Fantasy Value")):
            report["pool_value_kind"] = POOL_KIND_FAST_MARKET_FALLBACK
        else:
            report["pool_value_kind"] = POOL_KIND_VALID_PROJECTION
    try:
        out.attrs[POOL_VALUE_KIND_KEY] = report["pool_value_kind"]
    except Exception:
        pass

    return out, report
