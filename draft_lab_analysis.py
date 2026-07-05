"""Draft Simulation Test Mode post-draft analysis (live handoff + simulated drafts)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

POSITION_ROWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("C", ("C",)),
    ("1B", ("1B",)),
    ("2B", ("2B",)),
    ("3B", ("3B",)),
    ("SS", ("SS",)),
    ("OF", ("OF",)),
    ("UTIL", ("DH", "UTIL")),
    ("Bench", ("BN", "Bench")),
)

FANTASY_EDGE_HELP = (
    "Fantasy Edge measures how much the model likes a player compared with the market/ADP. "
    "Higher means better draft value."
)

DRAFT_LAB_TEAM_SCORE_HELP = (
    "**Draft Lab Team Score** summarizes projected roster strength for each simulated team. "
    "It is the **sum of each drafted player's projected value** using the active projection window, "
    "format, and style. Higher scores mean a stronger projected roster — teams are ranked by this total."
)

DRAFT_LAB_TABLE_README = """
**Projection Confidence** measures projection stability and reliability.

Higher values mean larger sample sizes, more stable performance, and lower volatility.  
Lower values mean injury uncertainty, role uncertainty, smaller samples, or higher volatility.

Examples: **0.95** = Very High Confidence · **0.80** = High Confidence · **0.60** = Moderate Confidence · **0.40** = Low Confidence

---

**Scarcity Score** measures how difficult it is to replace this player's production later.

Higher scores mean fewer comparable players remain, the position is drying up, or there is a larger talent drop-off.  
Lower scores mean many alternatives remain.

Examples: **0.90** = Highly Scarce · **0.50** = Moderate Scarcity · **0.10** = Easily Replaceable
"""


def draft_lab_table_readme_markdown() -> str:
    return DRAFT_LAB_TABLE_README.strip()


def _num(val: Any) -> float:
    return float(pd.to_numeric(val, errors="coerce"))


def _num_or_nan(val: Any) -> float:
    n = pd.to_numeric(val, errors="coerce")
    return float(n) if pd.notna(n) else np.nan


def _fmt_int(val: Any) -> str:
    n = pd.to_numeric(val, errors="coerce")
    return str(int(n)) if pd.notna(n) else "—"


def _fmt_score(val: Any) -> str:
    n = pd.to_numeric(val, errors="coerce")
    return f"{n:.2f}" if pd.notna(n) else "—"


def _fmt_pick_score_display(val: Any) -> str:
    try:
        from draft_score_display import fmt_pick_score

        return fmt_pick_score(val)
    except ImportError:
        return _fmt_score(val)


def analysis_context_from_session(session: dict[str, Any] | None, lab_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = session or {}
    lab_state = lab_state if isinstance(lab_state, dict) else {}
    handoff = lab_state.get("handoff") if isinstance(lab_state.get("handoff"), dict) else {}
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    cfg = dict(room.get("config") or {})
    teams = list(handoff.get("team_names") or room.get("teams") or [])
    if not teams and isinstance(lab_state.get("draft"), pd.DataFrame):
        teams = sorted(lab_state["draft"]["Fantasy Team"].dropna().astype(str).unique().tolist())
    return {
        "config": cfg,
        "teams": teams,
        "handoff": handoff,
        "source": str(lab_state.get("source") or ""),
    }


def apply_pick_time_snapshots(draft_df: pd.DataFrame) -> pd.DataFrame:
    """Prefer draft-time frozen scores over recomputed values in post-draft review."""
    if draft_df is None or draft_df.empty:
        return draft_df
    out = draft_df.copy()
    mapping = {
        "decision_score_at_pick": "Decision Score",
        "roster_fit_score_at_pick": "Draft Fit Score",
        "scarcity_score_at_pick": "Scarcity Score",
    }
    for src, dst in mapping.items():
        if src not in out.columns:
            continue
        snap = pd.to_numeric(out[src], errors="coerce")
        if dst not in out.columns:
            out[dst] = snap
        else:
            cur = pd.to_numeric(out[dst], errors="coerce")
            out[dst] = cur.where(cur.notna(), snap)
    return out


def roster_position_targets(config: dict[str, Any] | None) -> dict[str, int]:
    cfg = dict(config or {})
    slots = dict(cfg.get("slots") or {})
    bench = int(slots.get("BN", slots.get("Bench", 5)) or 0)
    return {
        "C": int(slots.get("C", 1) or 0),
        "1B": int(slots.get("1B", 1) or 0),
        "2B": int(slots.get("2B", 1) or 0),
        "3B": int(slots.get("3B", 1) or 0),
        "SS": int(slots.get("SS", 1) or 0),
        "OF": int(slots.get("OF", 3) or 0),
        "UTIL": int(slots.get("DH", slots.get("UTIL", 1)) or 0),
        "Bench": bench,
    }


def _position_bucket(primary: str) -> str:
    pos = str(primary or "").strip().upper()
    if pos in ("DH", "UTIL"):
        return "UTIL"
    if pos in ("BN", "BENCH"):
        return "Bench"
    for label, codes in POSITION_ROWS:
        if pos in codes:
            return label
    if pos == "OF":
        return "OF"
    return pos if pos in dict(roster_position_targets({})) else "Bench"


def count_team_position_haves(roster_df: pd.DataFrame) -> dict[str, int]:
    counts = {label: 0 for label, _ in POSITION_ROWS}
    if roster_df is None or roster_df.empty:
        return counts
    col = "Primary Position" if "Primary Position" in roster_df.columns else None
    if not col:
        counts["Bench"] = len(roster_df)
        return counts
    for raw in roster_df[col].fillna("Bench").astype(str):
        bucket = _position_bucket(raw)
        if bucket in counts:
            counts[bucket] += 1
        else:
            counts["Bench"] += 1
    return counts


def build_team_roster_needs_rows(team: str, roster_df: pd.DataFrame, targets: dict[str, int]) -> list[dict[str, Any]]:
    haves = count_team_position_haves(roster_df)
    rows: list[dict[str, Any]] = []
    for label, _codes in POSITION_ROWS:
        target = int(targets.get(label, 0) or 0)
        if target <= 0:
            continue
        have = int(haves.get(label, 0) or 0)
        rows.append(
            {
                "Fantasy Team": team,
                "Position": label if label != "UTIL" else "UTIL",
                "Have": have,
                "Target": target,
                "Gap": max(target - have, 0),
            }
        )
    return rows


def format_snake_draft_caption(teams: list[str]) -> str:
    names = [str(t).strip() for t in teams if str(t).strip()]
    if len(names) < 2:
        return "Snake draft order follows the configured teams."
    odd = " → ".join(names)
    even = " → ".join(reversed(names))
    return f"Snake draft: odd rounds {odd}; even rounds {even}."


def draft_lab_roster_team_options(teams: list[str]) -> list[str]:
    out = ["All Teams"]
    for t in teams:
        name = str(t).strip()
        if name and name not in out:
            out.append(name)
    return out


def draft_lab_board_display_columns() -> list[str]:
    """Primary columns shown by default in the post-draft audit board."""
    return [
        "Round",
        "Pick",
        "Fantasy Team",
        "fullName",
        "Primary Position",
        "Fantasy Edge",
        "Expected Fantasy Value",
        "Draft Fit Score",
        "Decision Score",
        "Pick Verdict",
        "Why This Pick",
    ]


def draft_lab_board_advanced_columns() -> list[str]:
    """Advanced audit columns — shown in expander."""
    return [
        "Team",
        "Model Rank",
        "Market Rank",
        "Projection Confidence",
        "Scarcity Score",
        "Roster Need At Pick",
        "Projection Warning",
    ]


def enrich_draft_board_pick_verdicts(
    draft_df: pd.DataFrame,
    *,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Backfill short Pick Verdict prose for post-draft audit rows."""
    if draft_df is None or draft_df.empty:
        return draft_df
    try:
        from live_draft_pick_engine import build_pick_verdict
    except ImportError:
        return draft_df
    out = draft_df.copy()
    targets = roster_position_targets(config)
    verdicts: list[str] = []
    for _, row in out.sort_values("Pick").iterrows():
        pick_no = int(_num(row.get("Pick")))
        team = str(row.get("Fantasy Team") or "")
        gaps_before = _gaps_before_pick(team, pick_no, out, targets)
        verdicts.append(build_pick_verdict(row, gaps=gaps_before, pick_no=pick_no))
    out["Pick Verdict"] = verdicts
    return out


def _rank_value_delta(row: pd.Series) -> float:
    model = _num_or_nan(row.get("Model Rank"))
    market = _num_or_nan(row.get("Market Rank"))
    if pd.isna(market):
        market = _num_or_nan(row.get("ADP Rank"))
    if pd.notna(model) and pd.notna(market):
        return float(market - model)
    return np.nan


def _reach_vs_market(row: pd.Series) -> float:
    pick_no = _num_or_nan(row.get("Pick"))
    market = _num_or_nan(row.get("Market Rank"))
    if pd.isna(market):
        market = _num_or_nan(row.get("ADP Rank"))
    if pd.notna(pick_no) and pd.notna(market):
        return float(pick_no - market)
    return np.nan


def _best_pick_composite(row: pd.Series) -> float:
    score = 0.0
    weight = 0.0
    dec = _num_or_nan(row.get("Decision Score"))
    if pd.notna(dec):
        score += dec * 0.35
        weight += 0.35
    edge = _num_or_nan(row.get("Fantasy Edge"))
    if pd.notna(edge):
        score += (np.clip(edge / 25.0, -0.5, 1.0) + 0.5) * 0.25
        weight += 0.25
    fit = _num_or_nan(row.get("Draft Fit Score"))
    if pd.notna(fit):
        score += fit * 0.15
        weight += 0.15
    pos_fit = _num_or_nan(row.get("Positional Fit"))
    if pd.notna(pos_fit):
        score += pos_fit * 0.10
        weight += 0.10
    scarcity = _num_or_nan(row.get("Scarcity Score"))
    if pd.notna(scarcity):
        score += scarcity * 0.05
        weight += 0.05
    delta = _rank_value_delta(row)
    if pd.notna(delta):
        score += np.clip(delta / 80.0, -0.2, 0.3) * 0.10
        weight += 0.10
    return float(score / weight) if weight > 0 else 0.0


def _gaps_before_pick(team: str, pick_no: int, draft_df: pd.DataFrame, targets: dict[str, int]) -> list[str]:
    prior = draft_df[(draft_df["Fantasy Team"] == team) & (pd.to_numeric(draft_df["Pick"], errors="coerce") < pick_no)]
    rows = build_team_roster_needs_rows(team, prior, targets)
    return [r["Position"] for r in rows if int(r["Gap"]) > 0]


def _explain_best_pick(row: pd.Series, gaps_before: list[str]) -> str:
    parts: list[str] = []
    delta = _rank_value_delta(row)
    if pd.notna(delta) and delta >= 15:
        parts.append(f"selected {_fmt_int(delta)} spots after model rank")
    pos = str(row.get("Primary Position") or "")
    if gaps_before and pos:
        bucket = _position_bucket(pos)
        if bucket in gaps_before or pos in gaps_before:
            parts.append(f"filled a {bucket} need")
    edge = _num_or_nan(row.get("Fantasy Edge"))
    if pd.notna(edge) and edge >= 5:
        parts.append(f"Fantasy Edge +{_fmt_int(edge)}")
    dec = _num_or_nan(row.get("Decision Score"))
    if pd.notna(dec):
        parts.append(f"Decision Score {_fmt_pick_score_display(dec)} led this roster")
    fit = _num_or_nan(row.get("Draft Fit Score"))
    if pd.notna(fit) and fit >= 0.6:
        parts.append("strong roster fit")
    if not parts:
        parts.append("highest composite value score on this roster")
    text = ", ".join(parts[:4])
    return text[0].upper() + text[1:] + "."


def _questionable_reasons(
    row: pd.Series,
    *,
    gaps_before: list[str],
    team_median_decision: float,
    better_alternatives: int,
) -> list[str]:
    reasons: list[str] = []
    reach = _reach_vs_market(row)
    if pd.notna(reach) and reach >= 35:
        reasons.append(f"Selected {_fmt_int(reach)} picks ahead of market rank")
    edge = _num_or_nan(row.get("Fantasy Edge"))
    if pd.notna(edge) and edge < 0:
        reasons.append(f"Negative Fantasy Edge ({_fmt_int(edge)})")
    dec = _num_or_nan(row.get("Decision Score"))
    if pd.notna(dec) and pd.notna(team_median_decision) and dec < team_median_decision - 0.10:
        reasons.append(
            f"Decision Score {_fmt_pick_score_display(dec)} trailed team median "
            f"{_fmt_pick_score_display(team_median_decision)}"
        )
    pos = str(row.get("Primary Position") or "")
    bucket = _position_bucket(pos)
    if gaps_before and bucket not in gaps_before and pos not in gaps_before and len(gaps_before) >= 2:
        reasons.append(
            f"Drafted {pos} while needs remained at {', '.join(gaps_before[:3])}"
        )
    if better_alternatives >= 3:
        reasons.append(f"{better_alternatives} higher-rated players were still available at this pick")
    fit = _num_or_nan(row.get("Draft Fit Score"))
    if pd.notna(fit) and fit < 0.35 and gaps_before:
        reasons.append("Low Roster Fit Score relative to open roster needs")
    return reasons


def _explain_good_pick(row: pd.Series, gaps_before: list[str]) -> str:
    parts: list[str] = []
    reach = _reach_vs_market(row)
    if pd.notna(reach) and abs(reach) <= 20:
        parts.append("drafted near market value")
    elif pd.notna(reach) and reach < 0:
        parts.append(f"value vs market rank ({_fmt_int(abs(reach))} spots later than ADP)")
    pos = str(row.get("Primary Position") or "")
    bucket = _position_bucket(pos)
    if gaps_before and (bucket in gaps_before or pos in gaps_before):
        parts.append(f"helped fill {bucket} need")
    edge = _num_or_nan(row.get("Fantasy Edge"))
    if pd.notna(edge) and edge >= 2:
        parts.append(f"positive Fantasy Edge (+{_fmt_int(edge)})")
    dec = _num_or_nan(row.get("Decision Score"))
    if pd.notna(dec):
        parts.append(f"Decision Score {_fmt_pick_score_display(dec)}")
    if not parts:
        parts.append("solid contribution without major reach or roster-fit concerns")
    text = ", ".join(parts[:3])
    return text[0].upper() + text[1:] + "."


def _count_better_available_at_pick(row: pd.Series, draft_df: pd.DataFrame, pool_df: pd.DataFrame | None) -> int:
    if pool_df is None or pool_df.empty:
        return 0
    pick_no = int(_num(row.get("Pick")))
    drafted_ids = set(draft_df[pd.to_numeric(draft_df["Pick"], errors="coerce") < pick_no]["playerID"].astype(str))
    avail = pool_df[~pool_df["playerID"].astype(str).isin(drafted_ids)].copy()
    if avail.empty or "Decision Score" not in avail.columns:
        return 0
    player_dec = _num_or_nan(row.get("Decision Score"))
    if pd.isna(player_dec):
        return 0
    better = pd.to_numeric(avail["Decision Score"], errors="coerce") > player_dec + 0.05
    return int(better.sum())


def classify_team_picks(
    team: str,
    team_df: pd.DataFrame,
    draft_df: pd.DataFrame,
    *,
    targets: dict[str, int],
    pool_df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    if team_df is None or team_df.empty:
        return []
    working = team_df.copy()
    working["_best_score"] = working.apply(_best_pick_composite, axis=1)
    best_idx = working["_best_score"].idxmax()
    best_row = working.loc[best_idx]
    best_name = str(best_row.get("fullName") or "")

    team_dec = _numeric_series(working, "Decision Score")
    team_median = float(team_dec.median()) if team_dec.notna().any() else np.nan

    pick_rows: list[dict[str, Any]] = []
    questionable_names: set[str] = set()

    for _, row in working.iterrows():
        if str(row.get("fullName") or "") == best_name:
            continue
        pick_no = int(_num(row.get("Pick")))
        gaps_before = _gaps_before_pick(team, pick_no, draft_df, targets)
        better = _count_better_available_at_pick(row, draft_df, pool_df)
        reasons = _questionable_reasons(
            row,
            gaps_before=gaps_before,
            team_median_decision=team_median,
            better_alternatives=better,
        )
        if reasons:
            questionable_names.add(str(row.get("fullName") or ""))
            pick_rows.append(
                {
                    "Fantasy Team": team,
                    "Pick Type": "Questionable Pick",
                    "Player": row.get("fullName"),
                    "Reason": "; ".join(reasons) + ".",
                }
            )

    gaps_before_best = _gaps_before_pick(team, int(_num(best_row.get("Pick"))), draft_df, targets)
    pick_rows.insert(
        0,
        {
            "Fantasy Team": team,
            "Pick Type": "Best Pick",
            "Player": best_row.get("fullName"),
            "Reason": _explain_best_pick(best_row, gaps_before_best),
        },
    )

    for _, row in working.iterrows():
        name = str(row.get("fullName") or "")
        if name == best_name or name in questionable_names:
            continue
        pick_no = int(_num(row.get("Pick")))
        gaps_before = _gaps_before_pick(team, pick_no, draft_df, targets)
        pick_rows.append(
            {
                "Fantasy Team": team,
                "Pick Type": "Good Pick",
                "Player": row.get("fullName"),
                "Reason": _explain_good_pick(row, gaps_before),
            }
        )
    return pick_rows


def enrich_lab_draft_metrics(
    draft_df: pd.DataFrame,
    pool_df: pd.DataFrame | None,
    config: dict[str, Any] | None,
) -> pd.DataFrame:
    """Backfill Decision Score and fit metrics using the shared draft scoring engine."""
    if draft_df is None or draft_df.empty:
        return draft_df
    out = apply_pick_time_snapshots(draft_df)
    if pool_df is None or getattr(pool_df, "empty", True):
        return out
    try:
        from live_draft_pick_scoring import apply_draft_pick_scoring
    except ImportError:
        return out

    cfg = dict(config or {})
    targets = roster_position_targets(cfg)
    fantasy_format = str(cfg.get("fantasy_format") or cfg.get("scoring_type") or "5x5 Roto")
    if "Roto" in fantasy_format:
        fantasy_format = "5x5 Roto"
    pool = pool_df.copy()
    if "playerID" not in pool.columns:
        return out

    for idx, row in out.sort_values("Pick").iterrows():
        if pd.notna(pd.to_numeric(row.get("decision_score_at_pick"), errors="coerce")):
            continue
        pick_no = int(_num(row.get("Pick")))
        team = str(row.get("Fantasy Team") or "")
        pid = str(row.get("playerID") or "")
        drafted_ids = set(out[pd.to_numeric(out["Pick"], errors="coerce") < pick_no]["playerID"].astype(str))
        available = pool[~pool["playerID"].astype(str).isin(drafted_ids)].copy()
        if available.empty:
            continue
        roster_before = out[(out["Fantasy Team"] == team) & (pd.to_numeric(out["Pick"], errors="coerce") < pick_no)]
        scored, _ = apply_draft_pick_scoring(
            available,
            roster_before,
            fantasy_format=fantasy_format,
            target_counts=targets,
            current_pick=pick_no,
        )
        if pid and "playerID" in scored.columns:
            hit = scored[scored["playerID"].astype(str) == pid]
        elif "fullName" in scored.columns:
            hit = scored[scored["fullName"].astype(str) == str(row.get("fullName") or "")]
        else:
            hit = pd.DataFrame()
        if hit.empty:
            continue
        src = hit.iloc[0]
        for col in (
            "Decision Score",
            "Draft Fit Score",
            "Positional Fit",
            "Scarcity Score",
            "Fantasy Edge",
            "Expected Fantasy Value",
            "Projection Confidence",
        ):
            if col in src.index and (col not in out.columns or pd.isna(out.at[idx, col])):
                out.at[idx, col] = src[col]
    if "Decision Score" in out.columns:
        out["Decision Score"] = pd.to_numeric(out["Decision Score"], errors="coerce")
    return out


def decision_score_debug_row(row: pd.Series) -> dict[str, Any]:
    return {
        "Fantasy Edge": row.get("Fantasy Edge"),
        "Scarcity Score": row.get("Scarcity Score"),
        "Draft Fit Score": row.get("Draft Fit Score"),
        "Projection Confidence": row.get("Projection Confidence"),
        "Decision Score": row.get("Decision Score"),
        "Positional Fit": row.get("Positional Fit"),
    }


def _col_sum(frame: pd.DataFrame, col: str) -> float:
    if col not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[col], errors="coerce").fillna(0).sum())


def _col_mean(frame: pd.DataFrame, col: str) -> float:
    if col not in frame.columns:
        return float("nan")
    vals = pd.to_numeric(frame[col], errors="coerce")
    return float(vals.mean()) if vals.notna().any() else float("nan")


def _numeric_series(frame: pd.DataFrame, col: str, *, fillna: float | None = None) -> pd.Series:
    """Safe numeric column read — missing columns never crash optional analysis paths."""
    if col not in frame.columns:
        if fillna is not None:
            return pd.Series(fillna, index=frame.index, dtype=float)
        return pd.Series(dtype=float)
    vals = pd.to_numeric(frame[col], errors="coerce")
    if fillna is not None:
        vals = vals.fillna(fillna)
    return vals


def _ab_weights(frame: pd.DataFrame) -> pd.Series:
    """AB weights for rate stats; uniform weights when proj_AB is absent."""
    return _numeric_series(frame, "proj_AB", fillna=1.0)


def analyze_draft_lab_results(
    draft_df: pd.DataFrame,
    yearly_source: pd.DataFrame,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if draft_df is None or draft_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    ctx = dict(context or {})
    config = dict(ctx.get("config") or {})
    targets = roster_position_targets(config)
    pool_df = ctx.get("pool") if isinstance(ctx.get("pool"), pd.DataFrame) else None

    team_rows: list[dict[str, Any]] = []
    strengths_rows: list[dict[str, Any]] = []
    pick_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []

    for team, g in draft_df.groupby("Fantasy Team"):
        totals = {
            "Fantasy Team": team,
            "Players": len(g),
            "Total Projected Fantasy Value": _col_sum(g, "Expected Fantasy Value"),
            "Projected HR": _col_sum(g, "proj_HR"),
            "Projected RBI": _col_sum(g, "proj_RBI"),
            "Projected R": _col_sum(g, "proj_R"),
            "Projected SB": _col_sum(g, "proj_SB"),
        }
        if "proj_BA" in g.columns:
            weights = _ab_weights(g)
            ba = pd.to_numeric(g["proj_BA"], errors="coerce")
            totals["Projected AVG"] = float(np.average(ba.dropna(), weights=weights.loc[ba.notna()])) if ba.notna().any() else np.nan
        else:
            totals["Projected AVG"] = np.nan
        if "proj_OPS" in g.columns:
            weights = _ab_weights(g)
            ops = pd.to_numeric(g["proj_OPS"], errors="coerce")
            totals["Projected OPS"] = float(np.average(ops.dropna(), weights=weights.loc[ops.notna()])) if ops.notna().any() else np.nan
        else:
            totals["Projected OPS"] = np.nan
        totals["Average Expected Fantasy Value"] = _col_mean(g, "Expected Fantasy Value")
        totals["Average Fantasy Edge"] = _col_mean(g, "Fantasy Edge")
        totals["Average Scarcity Score"] = _col_mean(g, "Scarcity Score")

        need_rows = build_team_roster_needs_rows(str(team), g, targets)
        gap_rows.extend(need_rows)
        open_gaps = [r["Position"] for r in need_rows if int(r["Gap"]) > 0]
        totals["Position Gaps"] = ", ".join(open_gaps) if open_gaps else "None"
        team_rows.append(totals)
        pick_rows.extend(classify_team_picks(str(team), g, draft_df, targets=targets, pool_df=pool_df))

    team_summary = pd.DataFrame(team_rows)
    if not team_summary.empty:
        team_summary["Projected Team Rank"] = team_summary["Total Projected Fantasy Value"].rank(ascending=False, method="min")
        cat_cols = ["Projected HR", "Projected RBI", "Projected R", "Projected SB", "Projected AVG", "Projected OPS"]
        for _, row in team_summary.iterrows():
            vals = row[[c for c in cat_cols if c in row.index]].astype(float)
            top = vals.sort_values(ascending=False).head(2).index.tolist()
            low = vals.sort_values().head(2).index.tolist()
            strengths_rows.append(
                {
                    "Fantasy Team": row["Fantasy Team"],
                    "Team Strengths": ", ".join([c.replace("Projected ", "") for c in top]),
                    "Team Weaknesses": ", ".join([c.replace("Projected ", "") for c in low]),
                }
            )
        team_summary = team_summary.sort_values("Projected Team Rank")

    actual_summary = pd.DataFrame()
    return team_summary, pd.DataFrame(strengths_rows), pd.DataFrame(pick_rows), pd.DataFrame(gap_rows), actual_summary
