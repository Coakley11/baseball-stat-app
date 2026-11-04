"""Draft Assistant ranking: roster fit vs model value.

Weights are intentional and tested. They are not a second projection model.
Base quality still comes from the existing player grade / expected fantasy value
and, when present, Decision Score and scarcity columns produced by
``apply_draft_pick_scoring``.

Roster Fit (team benefit):
    0.16 base quality
    0.52 positional need (required open slots, any eligibility)
    0.20 category improvement (priority-weighted marginal contribution)
    0.08 scarcity
    0.04 replacement-level surplus
    Players who cannot fill a required starter are multiplied by 0.12 so the
    top of the list is the open positions, not a generic value board.

Model Value (player quality, league-aware):
    0.70 base quality
    0.08 positional relevance
    0.08 category relevance
    0.10 scarcity
    0.04 replacement-level surplus
    Ineligible players take a 0.92 haircut. A clearly better player can still
    rank above a replacement-level need, which is the difference from Roster Fit.

Category priority weights: High 1.00, Medium 0.45, Low 0.12, Off 0.00.
Lower-is-better categories (ERA, WHIP) are inverted before weighting.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

import pandas as pd

PRIORITY_LEVELS: tuple[str, ...] = ("High", "Medium", "Low", "Off")
PRIORITY_WEIGHTS: dict[str, float] = {
    "High": 1.0,
    "Medium": 0.45,
    "Low": 0.12,
    "Off": 0.0,
}

ROSTER_FIT_WEIGHTS: dict[str, float] = {
    "base": 0.16,
    "position": 0.52,
    "category": 0.20,
    "scarcity": 0.08,
    "replacement": 0.04,
}
MODEL_VALUE_WEIGHTS: dict[str, float] = {
    "base": 0.70,
    "position": 0.08,
    "category": 0.08,
    "scarcity": 0.10,
    "replacement": 0.04,
}
ROSTER_FIT_INELIGIBLE_FACTOR = 0.12
MODEL_VALUE_INELIGIBLE_FACTOR = 0.92

MODE_ROSTER_FIT = "roster_fit"
MODE_MODEL_VALUE = "model_value"

SORT_ROSTER_FIT = "Roster Fit"
SORT_MODEL_VALUE = "Model Value"
DA_SORT_LABELS: tuple[str, ...] = (
    "Roster Fit",
    "Model Value",
    "Decision Score",
    "Player Grade",
    "Model Rank",
    "Market Rank",
    "Positional Scarcity",
    "Primary Position",
)

STANDARD_HITTER_SLOTS: dict[str, int] = {
    "C": 1,
    "1B": 1,
    "2B": 1,
    "3B": 1,
    "SS": 1,
    "OF": 3,
    "DH": 1,
}
FLEX_CODES = frozenset({"DH", "UTIL", "DH/UTIL"})
BENCH_CODES = frozenset({"BN", "BENCH"})
OF_ALIASES = frozenset({"OF", "LF", "CF", "RF"})
LOWER_IS_BETTER = frozenset({"ERA", "WHIP", "BB", "K/9-"})

_CATEGORY_COLUMNS: dict[str, tuple[str, ...]] = {
    "R": ("proj_R", "R"),
    "HR": ("proj_HR", "HR"),
    "RBI": ("proj_RBI", "RBI"),
    "SB": ("proj_SB", "SB"),
    "AVG": ("proj_BA", "proj_AVG", "BA", "AVG"),
    "BA": ("proj_BA", "proj_AVG", "BA", "AVG"),
    "OBP": ("proj_OBP", "OBP"),
    "SLG": ("proj_SLG", "SLG"),
    "OPS": ("proj_OPS", "OPS"),
    "W": ("proj_W", "W"),
    "K": ("proj_K", "proj_SO", "K", "SO"),
    "SO": ("proj_SO", "proj_K", "SO", "K"),
    "ERA": ("proj_ERA", "ERA"),
    "WHIP": ("proj_WHIP", "WHIP"),
    "SV": ("proj_SV", "SV"),
    "QS": ("proj_QS", "QS"),
    "Power": ("proj_HR", "HR"),
    "Run Production": ("proj_RBI", "RBI"),
    "Speed": ("proj_SB", "SB"),
    "Walks/OPS": ("proj_OPS", "OPS"),
}

_DEFAULT_HITTER_CATS = ("R", "HR", "RBI", "SB", "AVG")
_DEFAULT_PITCHER_CATS = ("W", "K", "ERA", "WHIP", "SV")


def normalize_priority(value: Any) -> str:
    text = str(value or "").strip().title()
    if text in {"Critical"}:
        return "High"
    if text in {"Moderate"}:
        return "Medium"
    if text in PRIORITY_LEVELS:
        return text
    return "Medium"


def priority_weight(value: Any) -> float:
    return float(PRIORITY_WEIGHTS.get(normalize_priority(value), 0.45))


def merge_category_priorities(
    automatic: Mapping[str, str] | None,
    overrides: Mapping[str, str] | None,
) -> dict[str, str]:
    """User overrides win. Missing categories stay at the automatic level."""
    merged = {str(k): normalize_priority(v) for k, v in (automatic or {}).items()}
    for key, value in (overrides or {}).items():
        label = str(key or "").strip()
        if not label:
            continue
        merged[label] = normalize_priority(value)
    return merged


def categories_at_or_above(priorities: Mapping[str, str], minimum: str = "Medium") -> list[str]:
    floor = priority_weight(minimum)
    return [label for label, level in priorities.items() if priority_weight(level) >= floor and priority_weight(level) > 0]


def league_category_labels(
    fantasy_format: str = "5x5 Roto",
    league_categories: list[str] | tuple[str, ...] | None = None,
    *,
    include_pitching: bool = False,
) -> list[str]:
    if league_categories:
        labels = [str(c).strip() for c in league_categories if str(c).strip()]
        if labels:
            if include_pitching:
                labels.extend(cat for cat in _DEFAULT_PITCHER_CATS if cat not in labels)
            return list(dict.fromkeys(labels))
    labels = list(_DEFAULT_HITTER_CATS)
    fmt = str(fantasy_format or "")
    if fmt != "5x5 Roto" and "point" in fmt.lower():
        labels = ["HR", "RBI", "SB", "OPS", "R"]
    if include_pitching:
        labels.extend(_DEFAULT_PITCHER_CATS)
    return list(dict.fromkeys(labels))


def category_column(frame: pd.DataFrame, label: str) -> str | None:
    if frame is None or not hasattr(frame, "columns"):
        return None
    for col in _CATEGORY_COLUMNS.get(str(label), (f"proj_{label}", label)):
        if col in frame.columns:
            return col
    return None


def category_is_lower_better(label: str) -> bool:
    return str(label or "").strip().upper() in LOWER_IS_BETTER


def _filled_counts(roster_df: pd.DataFrame | None) -> dict[str, int]:
    if roster_df is None or roster_df.empty:
        return {}
    col = "Primary Position" if "Primary Position" in roster_df.columns else None
    if col is None:
        for candidate in ("Position", "position"):
            if candidate in roster_df.columns:
                col = candidate
                break
    if col is None:
        return {}
    counts: dict[str, int] = {}
    for raw in roster_df[col].fillna("").astype(str):
        token = _canon_pos(raw)
        if not token or token in BENCH_CODES:
            continue
        counts[token] = counts.get(token, 0) + 1
    return counts


def open_positions_from_roster(
    roster_df: pd.DataFrame | None,
    target_counts: Mapping[str, int] | None,
    *,
    include_pitching: bool = False,
    draft_complete: bool = False,
) -> list[str]:
    """Required starter slots still open. Bench is never a recommendation need."""
    if draft_complete:
        return []
    counts = {str(k): int(v or 0) for k, v in (target_counts or {}).items() if int(v or 0) > 0}
    if not counts:
        counts = dict(STANDARD_HITTER_SLOTS)
        if include_pitching:
            counts["P"] = 5
    filled = _filled_counts(roster_df)
    open_codes: list[str] = []
    for code, required in counts.items():
        token = _canon_pos(code)
        if token in BENCH_CODES or token in FLEX_CODES:
            continue
        have = int(filled.get(token, 0))
        if token == "OF":
            have = sum(int(filled.get(p, 0)) for p in ("OF", "LF", "CF", "RF"))
        missing = max(0, int(required) - have)
        open_codes.extend([token] * missing)
    return open_codes


def required_need_codes(open_positions: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in open_positions or []:
        token = _canon_pos(raw)
        if token and token not in BENCH_CODES and token not in FLEX_CODES:
            out.append(token)
    return out


def _canon_pos(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text in {"DH/UTIL", "UTIL"}:
        return "DH"
    if text in OF_ALIASES and text != "OF":
        return text
    return text


def player_position_tokens(row: Mapping[str, Any] | pd.Series) -> set[str]:
    tokens: set[str] = set()
    getter = row.get if hasattr(row, "get") else (lambda k, d=None: d)
    primary = _canon_pos(getter("Primary Position") or getter("Position") or "")
    if primary:
        tokens.add(primary)
    elig = str(getter("Eligible Positions") or getter("Eligibility") or getter("Positions") or "")
    for part in re.split(r"[,/|+]", elig.upper()):
        token = _canon_pos(part)
        if token:
            tokens.add(token)
    if tokens & OF_ALIASES:
        tokens.add("OF")
    if "DH" in tokens or "UTIL" in tokens:
        tokens.add("DH")
    return tokens


def _unit(series: pd.Series, *, as_grade: bool = False) -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce")
    if vals.notna().sum() == 0:
        return pd.Series(0.0, index=series.index)
    finite = vals.dropna()
    hi = float(finite.max())
    lo = float(finite.min())
    if as_grade and hi <= 1.5 and lo >= -0.05:
        return vals.fillna(0.0).clip(0.0, 1.0)
    if as_grade and hi <= 100.0 and lo >= 0.0:
        return (vals.fillna(0.0) / 100.0).clip(0.0, 1.0)
    span = hi - lo
    if span <= 1e-9:
        return pd.Series(0.5, index=series.index)
    return ((vals - lo) / span).fillna(0.0).clip(0.0, 1.0)


def _base_quality(frame: pd.DataFrame) -> pd.Series:
    for col in ("Expected Fantasy Value", "Player Grade", "Decision Score"):
        if col in frame.columns:
            return _unit(frame[col], as_grade=True)
    return pd.Series(0.5, index=frame.index)


def _scarcity(frame: pd.DataFrame) -> pd.Series:
    for col in ("Position Scarcity Score", "Scarcity Score", "Position Scarcity Bonus"):
        if col in frame.columns:
            return _unit(frame[col])
    return pd.Series(0.0, index=frame.index)


def auto_category_priorities(
    roster_df: pd.DataFrame | None,
    pool_df: pd.DataFrame | None,
    labels: list[str],
    *,
    unfilled_hitter_slots: int = 0,
    draft_complete: bool = False,
) -> dict[str, str]:
    """Relative category weakness. Missing roster spots are projected at replacement, not zero."""
    if draft_complete or not labels:
        return {label: "Off" for label in labels}
    roster = roster_df if roster_df is not None else pd.DataFrame()
    pool = pool_df if pool_df is not None else pd.DataFrame()
    if roster.empty or pool.empty:
        return {label: "Medium" for label in labels}
    unfilled = max(0, int(unfilled_hitter_slots))
    filled = max(1, len(roster))
    out: dict[str, str] = {}
    for label in labels:
        col = category_column(roster, label) or category_column(pool, label)
        if col is None or col not in pool.columns or col not in roster.columns:
            out[label] = "Medium"
            continue
        pool_vals = pd.to_numeric(pool[col], errors="coerce")
        roster_vals = pd.to_numeric(roster[col], errors="coerce")
        pool_med = float(pool_vals.median()) if pool_vals.notna().any() else 0.0
        if pool_med == 0.0 and not category_is_lower_better(label):
            out[label] = "Low"
            continue
        if category_is_lower_better(label):
            roster_rate = float(roster_vals.mean()) if roster_vals.notna().any() else pool_med
            blended = (roster_rate * filled + pool_med * unfilled) / (filled + unfilled)
            baseline = pool_med if pool_med else blended or 1.0
            ratio = blended / baseline if baseline else 1.0
            if ratio >= 1.12:
                out[label] = "High"
            elif ratio >= 1.04:
                out[label] = "Medium"
            else:
                out[label] = "Low"
            continue
        if _looks_like_rate(label, pool_med):
            roster_rate = float(roster_vals.mean()) if roster_vals.notna().any() else pool_med
            blended = (roster_rate * filled + pool_med * unfilled) / (filled + unfilled)
            baseline = pool_med if pool_med else 1.0
            ratio = blended / baseline if baseline else 1.0
        else:
            roster_sum = float(roster_vals.fillna(0).sum())
            projected = roster_sum + (pool_med * 0.90 * unfilled)
            baseline = pool_med * (filled + unfilled)
            ratio = projected / baseline if baseline else 1.0
        if ratio < 0.82:
            out[label] = "High"
        elif ratio < 0.94:
            out[label] = "Medium"
        else:
            out[label] = "Low"
    return out


def _looks_like_rate(label: str, pool_med: float) -> bool:
    if str(label).upper() in {"AVG", "BA", "OBP", "SLG", "OPS", "ERA", "WHIP"}:
        return True
    return 0 < abs(pool_med) < 1.5 and str(label).upper() in {"AVG", "BA", "OBP", "SLG", "OPS"}


def _position_scores(
    frame: pd.DataFrame,
    required: list[str],
) -> tuple[pd.Series, pd.Series, pd.Series]:
    required_unique = list(dict.fromkeys(required))
    need_set = set(required_unique)
    eligible = []
    matched = []
    for _, row in frame.iterrows():
        tokens = player_position_tokens(row)
        hit = sorted(need_set & tokens)
        if not hit and "OF" in need_set and tokens & OF_ALIASES:
            hit = ["OF"]
        eligible.append(1.0 if hit else 0.0)
        matched.append(", ".join(hit[:3]))
    eligible_s = pd.Series(eligible, index=frame.index, dtype=float)
    matched_s = pd.Series(matched, index=frame.index)
    if not required_unique:
        return pd.Series(0.35, index=frame.index), eligible_s, matched_s
    scarcity = {}
    for code in required_unique:
        n = 0
        for _, row in frame.iterrows():
            tokens = player_position_tokens(row)
            if code in tokens or (code == "OF" and tokens & OF_ALIASES):
                n += 1
        scarcity[code] = 1.0 / (n + 1.0)
    max_scarce = max(scarcity.values()) if scarcity else 1.0
    scores = []
    for _, row in frame.iterrows():
        tokens = player_position_tokens(row)
        best = 0.0
        for code in required_unique:
            if code in tokens or (code == "OF" and tokens & OF_ALIASES):
                scarce_boost = 0.15 * (scarcity[code] / max_scarce)
                best = max(best, 1.0 + scarce_boost)
        if best == 0.0 and tokens & FLEX_CODES:
            best = 0.15
        scores.append(min(best, 1.15))
    return pd.Series(scores, index=frame.index), eligible_s, matched_s


def _category_scores(
    frame: pd.DataFrame,
    priorities: Mapping[str, str],
) -> tuple[pd.Series, pd.Series]:
    if frame.empty or not priorities:
        return pd.Series(0.0, index=frame.index), pd.Series("", index=frame.index)
    weighted = pd.Series(0.0, index=frame.index)
    weight_sum = 0.0
    best_label = pd.Series("", index=frame.index)
    best_value = pd.Series(-1.0, index=frame.index)
    for label, level in priorities.items():
        weight = priority_weight(level)
        if weight <= 0:
            continue
        col = category_column(frame, label)
        if col is None:
            continue
        unit = _unit(frame[col])
        if category_is_lower_better(label):
            unit = 1.0 - unit
        weighted = weighted + unit * weight
        weight_sum += weight
        better = unit > best_value
        best_value = best_value.where(~better, unit)
        best_label = best_label.where(~better, label)
    if weight_sum <= 0:
        return pd.Series(0.0, index=frame.index), pd.Series("", index=frame.index)
    return (weighted / weight_sum).clip(0.0, 1.0), best_label


def recommendation_reason(row: Mapping[str, Any], mode: str) -> str:
    fills = str(row.get("Matched Need") or "").strip()
    cat = str(row.get("Category Boost") or "").strip()
    cat_score = float(row.get("Category Improvement Score") or 0)
    pos_score = float(row.get("Position Need Score") or 0)
    base = float(row.get("Base Quality Score") or 0)
    bits: list[str] = []
    if fills and pos_score >= 0.8:
        bits.append(f"fills {fills}")
    elif fills and pos_score >= 0.15:
        bits.append(f"optional {fills}")
    if cat and cat_score >= 0.45:
        bits.append(f"improves {cat}")
    if base >= 0.55:
        bits.append("projected above replacement")
    if not bits:
        bits.append("available and roster-legal")
    prefix = "Strong roster fit" if mode == MODE_ROSTER_FIT else "Model value"
    return f"{prefix} — " + ", ".join(bits) + "."


def apply_draft_assistant_ranking(
    available: pd.DataFrame,
    *,
    mode: str = MODE_ROSTER_FIT,
    needed_positions: list[str] | None = None,
    category_priorities: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Add distinct Roster Fit and Model Value scores. Does not drop rows."""
    if available is None or not isinstance(available, pd.DataFrame) or available.empty:
        return available.copy() if isinstance(available, pd.DataFrame) else pd.DataFrame()
    frame = available.copy()
    required = required_need_codes(list(needed_positions or []))
    base = _base_quality(frame)
    scarce = _scarcity(frame)
    pos, eligible, matched = _position_scores(frame, required)
    pos_unit = (pos / pos.max()).clip(0, 1) if float(pos.max() or 0) > 0 else pos
    cat, cat_label = _category_scores(frame, category_priorities or {})
    replacement = (base - 0.45).clip(0, 1)
    frame["Base Quality Score"] = base
    frame["Position Need Score"] = pos_unit
    frame["Fills Required Position"] = eligible
    frame["Matched Need"] = matched
    frame["Category Improvement Score"] = cat
    frame["Category Boost"] = cat_label
    frame["Scarcity Adjustment"] = scarce
    frame["Replacement Surplus"] = replacement

    def _blend(weights: Mapping[str, float], ineligible_factor: float) -> pd.Series:
        score = (
            base * weights["base"]
            + pos_unit * weights["position"]
            + cat * weights["category"]
            + scarce * weights["scarcity"]
            + replacement * weights["replacement"]
        )
        if required:
            score = score.where(eligible >= 1.0, score * ineligible_factor)
        return score.clip(lower=0)

    frame["Roster Fit Rank Score"] = _blend(ROSTER_FIT_WEIGHTS, ROSTER_FIT_INELIGIBLE_FACTOR)
    frame["Model Value Score"] = _blend(MODEL_VALUE_WEIGHTS, MODEL_VALUE_INELIGIBLE_FACTOR)
    rank_mode = MODE_ROSTER_FIT if mode in {MODE_ROSTER_FIT, SORT_ROSTER_FIT} else MODE_MODEL_VALUE
    if mode not in {MODE_ROSTER_FIT, MODE_MODEL_VALUE, SORT_ROSTER_FIT, SORT_MODEL_VALUE}:
        rank_mode = MODE_ROSTER_FIT if "fit" in str(mode).lower() else MODE_MODEL_VALUE
    chosen = frame["Roster Fit Rank Score"] if rank_mode == MODE_ROSTER_FIT else frame["Model Value Score"]
    frame["Assistant Rank Score"] = chosen
    frame["Why this pick"] = [
        recommendation_reason(row, rank_mode) for _, row in frame.iterrows()
    ]
    return frame


def _ensure_sort_column(frame: pd.DataFrame, sort_label: str) -> tuple[str, bool]:
    """Return a real column and direction for every dropdown label.

    Missing engine columns are derived so an option cannot silently keep the
    previous card order.
    """
    label = str(sort_label or SORT_ROSTER_FIT)
    if label == SORT_ROSTER_FIT:
        return "Roster Fit Rank Score", False
    if label == SORT_MODEL_VALUE:
        return "Model Value Score", False
    if label == "Decision Score":
        if "Decision Score" not in frame.columns:
            frame["Decision Score"] = frame.get("Base Quality Score", pd.Series(0.0, index=frame.index))
        return "Decision Score", False
    if label == "Player Grade":
        if "Player Grade" not in frame.columns:
            source = "Expected Fantasy Value" if "Expected Fantasy Value" in frame.columns else "Base Quality Score"
            frame["Player Grade"] = pd.to_numeric(frame[source], errors="coerce") if source in frame.columns else 0.0
        return "Player Grade", False
    if label == "Model Rank":
        if "Model Rank" not in frame.columns:
            base = pd.to_numeric(frame.get("Expected Fantasy Value", frame.get("Base Quality Score")), errors="coerce")
            frame["Model Rank"] = base.rank(ascending=False, method="min")
        return "Model Rank", True
    if label == "Market Rank":
        if "Market Rank" not in frame.columns:
            frame["Market Rank"] = pd.Series(range(1, len(frame) + 1), index=frame.index)
        return "Market Rank", True
    if label == "Positional Scarcity":
        for col in ("Position Scarcity Score", "Scarcity Score", "Scarcity Adjustment"):
            if col in frame.columns:
                if col != "Positional Scarcity Sort":
                    frame["Positional Scarcity Sort"] = pd.to_numeric(frame[col], errors="coerce")
                return "Positional Scarcity Sort", False
        frame["Positional Scarcity Sort"] = pd.to_numeric(frame.get("Position Need Score"), errors="coerce")
        return "Positional Scarcity Sort", False
    if label == "Primary Position":
        if "Primary Position" not in frame.columns:
            frame["Primary Position"] = ""
        return "Primary Position", True
    col, ascending = ranking_sort_column(label)
    if col not in frame.columns:
        frame[col] = pd.to_numeric(frame.get("Assistant Rank Score"), errors="coerce")
    return col, ascending


def order_recommendation_cards(frame: pd.DataFrame, sort_label: str) -> pd.DataFrame:
    """Reorder the full pool for one dropdown option and stamp Card Rank 1..n.

    The returned row order is the card order. Rank numbers match that order.
    """
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    work = frame.copy()
    col, ascending = _ensure_sort_column(work, sort_label)
    name_col = "fullName" if "fullName" in work.columns else ("Player" if "Player" in work.columns else None)
    sort_cols = [col]
    sort_asc = [ascending]
    if name_col and name_col != col:
        sort_cols.append(name_col)
        sort_asc.append(True)
    ordered = work.sort_values(sort_cols, ascending=sort_asc, kind="mergesort", na_position="last")
    ordered = ordered.reset_index(drop=True)
    ordered["Card Rank"] = range(1, len(ordered) + 1)
    ordered["Sort Option"] = str(sort_label or SORT_ROSTER_FIT)
    return ordered


def ranking_sort_column(sort_label: str) -> tuple[str, bool]:
    """Column and ascending flag for a Draft Assistant sort label."""
    label = str(sort_label or SORT_ROSTER_FIT)
    if label == SORT_ROSTER_FIT:
        return "Roster Fit Rank Score", False
    if label == SORT_MODEL_VALUE:
        return "Model Value Score", False
    if label in {"Model Rank", "Market Rank"}:
        return label, True
    if label == "Primary Position":
        return "Primary Position", True
    mapping = {
        "Decision Score": "Decision Score",
        "Player Grade": "Player Grade",
        "Positional Scarcity": "Position Scarcity Score",
        "Roster Fit Score": "Roster Fit Rank Score",
    }
    return mapping.get(label, label), False


def fold_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace(".", " ")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def resolve_action_player_name(player: str, label_map: Mapping[str, Any] | None) -> str | None:
    """Map a waiver/display name onto a comparison or trend label, if one match exists."""
    raw = " ".join(str(player or "").split())
    if not raw or not label_map:
        return None
    if raw in label_map:
        return raw
    folded = fold_name(raw)
    hits: list[str] = []
    for label in label_map.keys():
        label_s = str(label)
        if fold_name(label_s) == folded or fold_name(label_s.split("(")[0]) == folded:
            hits.append(label_s)
    unique = list(dict.fromkeys(hits))
    if len(unique) == 1:
        return unique[0]
    return None
