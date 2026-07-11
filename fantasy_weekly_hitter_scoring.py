"""Hitter-only weekly fantasy scoring — category-driven baselines, deltas, and finalization."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fantasy_league_context import normalize_player_key, upsert_league_context

WORKFLOW_KEY_WEEKLY_HITTER_SCORING = "weekly_hitter_scoring"
WORKFLOW_KEY_HITTER_STANDINGS_CUMULATIVE = "hitter_weekly_standings_cumulative"

WEEK_SCORING_LOCKED = "locked"
WEEK_SCORING_FINALIZED = "finalized"

STANDARD_ROTO_5X5: tuple[str, ...] = ("R", "HR", "RBI", "SB", "AVG")
COUNTING_CATEGORIES = frozenset({"R", "HR", "RBI", "SB", "H", "BB"})
RATE_CATEGORIES = frozenset({"AVG", "OBP", "OPS"})

# Hidden cumulative fields used for rate calculations (never standings categories by default).
HIDDEN_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "H": ("H",),
    "AB": ("AB",),
    "BB": ("BB",),
    "HBP": ("HBP",),
    "SF": ("SF",),
    "2B": ("2B",),
    "3B": ("3B",),
    "HR": ("HR",),
    "R": ("R",),
    "RBI": ("RBI",),
    "SB": ("SB",),
}

DISPLAY_STAT_ALIASES: dict[str, tuple[str, ...]] = {
    **HIDDEN_FIELD_ALIASES,
    "AVG": ("BA", "AVG"),
    "OBP": ("OBP",),
    "OPS": ("OPS",),
    "SLG": ("SLG",),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _player_name_col(df: pd.DataFrame) -> str:
    for col in ("Player", "fullName", "player_name"):
        if col in df.columns:
            return col
    return "Player"


def _read_field(row: pd.Series | dict[str, Any], field_name: str) -> float | None:
    aliases = DISPLAY_STAT_ALIASES.get(field_name, (field_name,))
    getter = row.get if hasattr(row, "get") else lambda _k, _d=None: None
    for col in aliases:
        if isinstance(row, pd.Series):
            if col not in row.index:
                continue
            val = row.get(col)
        else:
            val = getter(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None


def _player_id_from_row(row: pd.Series | dict[str, Any]) -> str:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": ""
    for key in ("player_id", "playerID", "playerId", "mlbam_id", "MLBAM ID", "ID"):
        val = str(getter(key) or "").strip()
        if val:
            return val
    return ""


def _resolve_format_mode(context: dict[str, Any]) -> tuple[str, str]:
    """Return (mode, format_label). mode is 'roto' or 'points' or ''."""
    settings = context.get("scoring_settings") if isinstance(context.get("scoring_settings"), dict) else {}
    fmt = str(context.get("fantasy_format") or settings.get("scoring_type") or "").strip()
    fmt_l = fmt.lower()
    if "point" in fmt_l:
        return "points", fmt or "Points League"
    if "roto" in fmt_l or "5x5" in fmt_l:
        return "roto", fmt or "5x5 Roto"
    if settings.get("points_weights") or settings.get("point_weights"):
        return "points", fmt or "Points League"
    if settings.get("hitter_categories"):
        return "roto", fmt or "Category League"
    return "", fmt


def _normalize_category_list(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[str] = []
    for item in raw:
        token = str(item or "").strip().upper()
        if token in ("BA",):
            token = "AVG"
        if token and token not in out:
            out.append(token)
    return tuple(out)


def _hidden_fields_for_categories(display: tuple[str, ...]) -> frozenset[str]:
    hidden: set[str] = set()
    if "AVG" in display:
        hidden.update({"H", "AB"})
    if "OBP" in display:
        hidden.update({"H", "AB", "BB", "HBP", "SF"})
    if "OPS" in display:
        hidden.update({"H", "AB", "BB", "HBP", "SF", "2B", "3B", "HR"})
    if "BB" in display:
        hidden.add("BB")
    return frozenset(hidden)


def _points_weights_from_settings(settings: dict[str, Any]) -> dict[str, float]:
    raw = settings.get("points_weights") or settings.get("point_weights") or settings.get("points_values") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, val in raw.items():
        token = str(key or "").strip().upper()
        if token in ("BA",):
            token = "AVG"
        try:
            weight = float(val)
        except (TypeError, ValueError):
            continue
        out[token] = weight
    return out


@dataclass(frozen=True)
class HitterScoringProfile:
    scoring_mode: str
    format_label: str
    display_categories: tuple[str, ...]
    hidden_fields: frozenset[str]
    points_weights: dict[str, float]
    blocked: bool
    block_message: str
    config_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoring_mode": self.scoring_mode,
            "format_label": self.format_label,
            "display_categories": list(self.display_categories),
            "hidden_fields": sorted(self.hidden_fields),
            "points_weights": dict(self.points_weights),
            "blocked": self.blocked,
            "block_message": self.block_message,
            "config_source": self.config_source,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> HitterScoringProfile | None:
        if not isinstance(raw, dict):
            return None
        return cls(
            scoring_mode=str(raw.get("scoring_mode") or ""),
            format_label=str(raw.get("format_label") or ""),
            display_categories=tuple(str(c) for c in (raw.get("display_categories") or [])),
            hidden_fields=frozenset(str(f) for f in (raw.get("hidden_fields") or [])),
            points_weights={
                str(k): float(v)
                for k, v in (raw.get("points_weights") or {}).items()
                if str(k).strip()
            },
            blocked=bool(raw.get("blocked")),
            block_message=str(raw.get("block_message") or ""),
            config_source=str(raw.get("config_source") or ""),
        )


def resolve_hitter_scoring_profile(
    context: dict[str, Any] | None,
    *,
    session: dict[str, Any] | None = None,
) -> HitterScoringProfile:
    """League saved scoring configuration is authoritative."""
    if session is not None:
        cache = session.get("_weekly_scoring_profile_cache")
        ctx_id = str((context or {}).get("league_context_id") or "")
        if isinstance(cache, dict) and cache.get("context_id") == ctx_id and cache.get("profile"):
            cached = HitterScoringProfile.from_dict(cache.get("profile"))
            if cached is not None:
                return cached

    if not isinstance(context, dict):
        profile = HitterScoringProfile(
            scoring_mode="",
            format_label="",
            display_categories=(),
            hidden_fields=frozenset(),
            points_weights={},
            blocked=True,
            block_message="No active league context for weekly scoring.",
            config_source="none",
        )
        _store_profile_cache(session, context, profile)
        return profile

    settings = context.get("scoring_settings") if isinstance(context.get("scoring_settings"), dict) else {}
    explicit_cats = _normalize_category_list(settings.get("hitter_categories"))
    mode, fmt_label = _resolve_format_mode(context)
    source = "context.scoring_settings"

    if explicit_cats:
        display = explicit_cats
        if not mode:
            mode = "roto" if "POINTS" not in fmt_label.upper() else "points"
        source = "context.scoring_settings.hitter_categories"
    elif mode == "roto":
        display = STANDARD_ROTO_5X5
        source = "context.fantasy_format.roto_default"
    elif mode == "points":
        weights = _points_weights_from_settings(settings)
        display = tuple(sorted(weights.keys()))
        if not display:
            profile = HitterScoringProfile(
                scoring_mode="points",
                format_label=fmt_label,
                display_categories=(),
                hidden_fields=frozenset(),
                points_weights={},
                blocked=True,
                block_message=(
                    "This points league has no saved scoring weights. "
                    "Configure hitter point values in league scoring settings before weekly scoring."
                ),
                config_source="context.scoring_settings.points_weights",
            )
            _store_profile_cache(session, context, profile)
            return profile
        source = "context.scoring_settings.points_weights"
    else:
        display = STANDARD_ROTO_5X5
        mode = "roto"
        fmt_label = fmt_label or "5x5 Roto"
        source = "default.roto_fallback"
        hidden = _hidden_fields_for_categories(display)
        weights = {}
        profile = HitterScoringProfile(
            scoring_mode=mode,
            format_label=fmt_label,
            display_categories=display,
            hidden_fields=hidden,
            points_weights=weights,
            blocked=False,
            block_message="",
            config_source=source,
        )
        _store_profile_cache(session, context, profile)
        return profile

    hidden = _hidden_fields_for_categories(display)
    weights = _points_weights_from_settings(settings) if mode == "points" else {}

    if mode == "points":
        missing = [c for c in display if c not in weights]
        if missing:
            profile = HitterScoringProfile(
                scoring_mode="points",
                format_label=fmt_label,
                display_categories=display,
                hidden_fields=hidden,
                points_weights=weights,
                blocked=True,
                block_message=f"Missing point weights for: {', '.join(missing)}",
                config_source=source,
            )
            _store_profile_cache(session, context, profile)
            return profile

    profile = HitterScoringProfile(
        scoring_mode=mode,
        format_label=fmt_label,
        display_categories=display,
        hidden_fields=hidden,
        points_weights=weights,
        blocked=False,
        block_message="",
        config_source=source,
    )
    _store_profile_cache(session, context, profile)
    return profile


def _store_profile_cache(
    session: dict[str, Any] | None,
    context: dict[str, Any] | None,
    profile: HitterScoringProfile,
) -> None:
    if session is None:
        return
    session["_weekly_scoring_profile_cache"] = {
        "context_id": str((context or {}).get("league_context_id") or ""),
        "profile": profile.to_dict(),
    }


def resolve_canonical_league_id(context: dict[str, Any]) -> str:
    try:
        from fantasy_league_identity import resolve_canonical_league_id as _resolve

        return str(_resolve(context) or "").strip()
    except ImportError:
        return str(context.get("league_id") or context.get("metadata", {}).get("league_id") or "").strip()


def canonical_team_identity(context: dict[str, Any], team_name: str) -> str:
    try:
        from fantasy_league_team_ownership import owned_team_for_user

        owned = owned_team_for_user(context)
        if owned:
            return owned
    except ImportError:
        pass
    return str(team_name or context.get("my_team_name") or "").strip()


def weekly_team_record_key(league_id: str, team_identity: str, week: int) -> str:
    return f"{league_id}|{team_identity}|week_{int(week)}"


def weekly_finalize_id(league_id: str, week: int) -> str:
    return f"{league_id}|week_{int(week)}"


def _scoring_root(context: dict[str, Any]) -> dict[str, Any]:
    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    root = workflow.get(WORKFLOW_KEY_WEEKLY_HITTER_SCORING)
    if not isinstance(root, dict):
        root = {"weeks": {}}
        workflow[WORKFLOW_KEY_WEEKLY_HITTER_SCORING] = root
    weeks = root.get("weeks")
    if not isinstance(weeks, dict):
        weeks = {}
        root["weeks"] = weeks
    return root


def get_weekly_scoring_record(
    context: dict[str, Any] | None,
    *,
    week: int,
    team: str = "",
    league_id: str = "",
) -> dict[str, Any] | None:
    if not isinstance(context, dict):
        return None
    league_id = league_id or resolve_canonical_league_id(context)
    team_id = canonical_team_identity(context, team)
    if not league_id or not team_id:
        return None
    key = weekly_team_record_key(league_id, team_id, week)
    record = (_scoring_root(context).get("weeks") or {}).get(key)
    return copy.deepcopy(record) if isinstance(record, dict) else None


def _put_weekly_scoring_record(context: dict[str, Any], record: dict[str, Any]) -> None:
    key = str(record.get("record_key") or "")
    if not key:
        return
    _scoring_root(context)["weeks"][key] = copy.deepcopy(record)


def extract_cumulative_snapshot(
    row: pd.Series | dict[str, Any],
    profile: HitterScoringProfile,
) -> dict[str, Any]:
    """Configured counting + hidden fields from a roster stats row."""
    fields: set[str] = set(profile.display_categories) | set(profile.hidden_fields)
    fields.discard("AVG")
    fields.discard("OBP")
    fields.discard("OPS")
    out: dict[str, Any] = {}
    for field_name in sorted(fields):
        val = _read_field(row, field_name)
        if val is not None:
            out[field_name] = val
    return out


def _compute_total_bases(snapshot: dict[str, Any]) -> float | None:
    if "TB" in snapshot:
        return float(snapshot["TB"])
    h = snapshot.get("H")
    b2 = snapshot.get("2B")
    b3 = snapshot.get("3B")
    hr = snapshot.get("HR")
    if h is None:
        return None
    try:
        h_f = float(h)
        b2_f = float(b2 or 0)
        b3_f = float(b3 or 0)
        hr_f = float(hr or 0)
        singles = h_f - b2_f - b3_f - hr_f
        if singles < 0:
            return None
        return singles + 2 * b2_f + 3 * b3_f + 4 * hr_f
    except (TypeError, ValueError):
        return None


def _rate_availability(
    category: str,
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if category == "AVG":
        for f in ("H", "AB"):
            if baseline.get(f) is None or current.get(f) is None:
                missing.append(f)
    elif category == "OBP":
        for f in ("H", "AB", "BB", "HBP", "SF"):
            if baseline.get(f) is None or current.get(f) is None:
                missing.append(f)
    elif category == "OPS":
        for f in ("H", "AB", "BB", "HBP", "SF"):
            if baseline.get(f) is None or current.get(f) is None:
                missing.append(f)
        if _compute_total_bases(baseline) is None or _compute_total_bases(current) is None:
            missing.append("TB")
    return (not missing, list(dict.fromkeys(missing)))


def _weekly_obp(components: dict[str, float]) -> float | None:
    num = components.get("H", 0) + components.get("BB", 0) + components.get("HBP", 0)
    denom = (
        components.get("AB", 0)
        + components.get("BB", 0)
        + components.get("HBP", 0)
        + components.get("SF", 0)
    )
    if denom <= 0:
        return None
    return num / denom


def _weekly_slg(components: dict[str, float]) -> float | None:
    ab = components.get("AB", 0)
    if ab <= 0:
        return None
    tb = _compute_total_bases(components)
    if tb is None:
        return None
    return tb / ab


def _delta_components(baseline: dict[str, Any], current: dict[str, Any], fields: set[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in fields:
        if f in RATE_CATEGORIES:
            continue
        b = baseline.get(f)
        c = current.get(f)
        if b is None or c is None:
            continue
        out[f] = float(c) - float(b)
    return out


def compute_player_weekly_results(
    *,
    baseline: dict[str, Any],
    current: dict[str, Any],
    profile: HitterScoringProfile,
    is_starter: bool,
) -> dict[str, Any]:
    fields = set(profile.display_categories) | set(profile.hidden_fields)
    fields -= RATE_CATEGORIES
    deltas = _delta_components(baseline, current, fields)
    display: dict[str, Any] = {}
    unavailable: dict[str, list[str]] = {}

    for cat in profile.display_categories:
        if cat in COUNTING_CATEGORIES or cat == "BB":
            if cat in deltas:
                display[cat] = deltas[cat]
            elif cat in profile.points_weights:
                display[cat] = deltas.get(cat, 0.0)
        elif cat == "AVG":
            ok, missing = _rate_availability("AVG", baseline, current)
            if not ok:
                unavailable["AVG"] = missing
                display["AVG"] = None
            else:
                h = deltas.get("H", 0.0)
                ab = deltas.get("AB", 0.0)
                display["AVG"] = (h / ab) if ab > 0 else None
        elif cat == "OBP":
            ok, missing = _rate_availability("OBP", baseline, current)
            if not ok:
                unavailable["OBP"] = missing
                display["OBP"] = None
            else:
                display["OBP"] = _weekly_obp(deltas)
        elif cat == "OPS":
            ok, missing = _rate_availability("OPS", baseline, current)
            if not ok:
                unavailable["OPS"] = missing
                display["OPS"] = None
            else:
                obp = _weekly_obp(deltas)
                slg = _weekly_slg(deltas)
                display["OPS"] = (obp + slg) if obp is not None and slg is not None else None

    points_total = None
    if profile.scoring_mode == "points":
        points_total = 0.0
        for cat, weight in profile.points_weights.items():
            if cat in RATE_CATEGORIES:
                val = display.get(cat)
                if val is None:
                    points_total = None
                    break
                points_total += float(val) * float(weight)
            else:
                points_total += float(deltas.get(cat, 0.0)) * float(weight)

    return {
        "display": display,
        "deltas": deltas,
        "unavailable": unavailable,
        "points_total": points_total,
        "counts_toward_score": bool(is_starter),
    }


def compute_team_weekly_totals(
    player_results: dict[str, dict[str, Any]],
    profile: HitterScoringProfile,
) -> dict[str, Any]:
    starters = {k: v for k, v in player_results.items() if v.get("counts_toward_score")}
    totals: dict[str, Any] = {}
    unavailable: dict[str, list[str]] = {}

    if profile.scoring_mode == "points":
        pts = 0.0
        blocked = False
        for result in starters.values():
            p = result.get("points_total")
            if p is None:
                blocked = True
                break
            pts += float(p)
        totals["POINTS"] = None if blocked else pts
        return {"totals": totals, "unavailable": unavailable, "starter_count": len(starters)}

    combined: dict[str, float] = {}
    for cat in profile.display_categories:
        if cat in COUNTING_CATEGORIES or cat == "BB":
            combined[cat] = sum(
                float((result.get("display") or {}).get(cat) or 0)
                for result in starters.values()
                if (result.get("display") or {}).get(cat) is not None
            )
            totals[cat] = combined[cat]
        elif cat == "AVG":
            if any("AVG" in (result.get("unavailable") or {}) for result in starters.values()):
                totals["AVG"] = None
                unavailable["AVG"] = ["H", "AB"]
            else:
                h = sum(float(r.get("deltas", {}).get("H", 0)) for r in starters.values())
                ab = sum(float(r.get("deltas", {}).get("AB", 0)) for r in starters.values())
                totals["AVG"] = (h / ab) if ab > 0 else None
        elif cat == "OBP":
            comps = {f: 0.0 for f in ("H", "AB", "BB", "HBP", "SF")}
            for result in starters.values():
                for f in comps:
                    comps[f] += float(result.get("deltas", {}).get(f, 0))
            if any(
                any(f in (result.get("unavailable") or {}) for f in ("OBP",))
                for result in starters.values()
            ):
                totals["OBP"] = None
                unavailable["OBP"] = ["H", "AB", "BB", "HBP", "SF"]
            else:
                totals["OBP"] = _weekly_obp(comps)
        elif cat == "OPS":
            comps = {f: 0.0 for f in ("H", "AB", "BB", "HBP", "SF", "2B", "3B", "HR")}
            for result in starters.values():
                for f in comps:
                    comps[f] += float(result.get("deltas", {}).get(f, 0))
            obp = _weekly_obp(comps)
            slg = _weekly_slg(comps)
            totals["OPS"] = (obp + slg) if obp is not None and slg is not None else None
            if totals["OPS"] is None:
                unavailable["OPS"] = ["OBP", "SLG", "components"]

    return {"totals": totals, "unavailable": unavailable, "starter_count": len(starters)}


def roster_data_fingerprint(roster_df: pd.DataFrame | None) -> str:
    if roster_df is None or roster_df.empty:
        return "empty"
    cols = sorted(str(c) for c in roster_df.columns)
    name_col = _player_name_col(roster_df)
    sample = roster_df[[name_col] + [c for c in ["R", "HR", "H", "AB"] if c in roster_df.columns]].head(20).to_csv(index=False)
    raw = f"{cols}|{len(roster_df)}|{sample}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def build_player_snapshots(
    roster_df: pd.DataFrame,
    assignments: dict[str, str],
    profile: HitterScoringProfile,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (starters, bench, baselines) keyed by player_key."""
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(name_col) or "").strip()
    }
    starter_names = {str(v).strip() for v in assignments.values() if str(v).strip()}
    starters: dict[str, Any] = {}
    bench: dict[str, Any] = {}
    baselines: dict[str, Any] = {}

    for name, row in lookup.items():
        pid = _player_id_from_row(row)
        pkey = pid or normalize_player_key(name)
        if not pkey:
            continue
        snap = extract_cumulative_snapshot(row, profile)
        entry = {
            "player_key": pkey,
            "player_id": pid,
            "player_name": name,
            "is_starter": name in starter_names,
            "slot": next((k for k, v in assignments.items() if str(v).strip() == name), ""),
        }
        baselines[pkey] = snap
        if name in starter_names:
            starters[pkey] = entry
        else:
            bench[pkey] = entry
    return starters, bench, baselines


def create_weekly_baseline_on_lock(
    context: dict[str, Any],
    *,
    week: int,
    team: str,
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
    profile: HitterScoringProfile,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create baseline exactly once for a locked week."""
    try:
        from page_perf_phases import session_perf_phase

        phase_ctx = session_perf_phase(session or {}, "weekly_hitter_baseline")
    except ImportError:
        from contextlib import nullcontext

        phase_ctx = nullcontext()

    with phase_ctx:
        return _create_weekly_baseline_on_lock_inner(
            context,
            week=week,
            team=team,
            assignments=assignments,
            roster_df=roster_df,
            profile=profile,
        )


def _create_weekly_baseline_on_lock_inner(
    context: dict[str, Any],
    *,
    week: int,
    team: str,
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
    profile: HitterScoringProfile,
) -> dict[str, Any]:
    """Create baseline exactly once for a locked week."""
    result: dict[str, Any] = {"ok": False, "errors": [], "record": None}
    if profile.blocked:
        result["errors"].append(profile.block_message or "Weekly scoring is blocked.")
        return result

    league_id = resolve_canonical_league_id(context)
    team_id = canonical_team_identity(context, team)
    if not league_id or not team_id:
        result["errors"].append("Missing canonical league or team identity.")
        return result

    key = weekly_team_record_key(league_id, team_id, week)
    existing = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
    if isinstance(existing, dict):
        if existing.get("legacy") and not existing.get("baseline_created_at"):
            result["errors"].append(
                "Legacy locked week — baseline was not captured and cannot be created retroactively."
            )
            return result
        if existing.get("baseline_created_at"):
            result["ok"] = True
            result["record"] = existing
            result["skipped"] = True
            return result

    starters, bench, baselines = build_player_snapshots(roster_df, assignments, profile)
    record = {
        "record_key": key,
        "canonical_league_id": league_id,
        "canonical_team_identity": team_id,
        "week": int(week),
        "scoring_mode": profile.scoring_mode,
        "scoring_profile": profile.to_dict(),
        "assignments": dict(assignments),
        "starters": starters,
        "bench": bench,
        "baselines": baselines,
        "baseline_created_at": _utc_now_iso(),
        "locked_at": _utc_now_iso(),
        "status": WEEK_SCORING_LOCKED,
        "finalized_at": "",
        "final_result_id": "",
        "standings_write_id": "",
        "stats_fingerprint": roster_data_fingerprint(roster_df),
        "stats_updated_at": _utc_now_iso(),
        "player_results": {},
        "team_totals": {},
        "legacy": False,
    }
    _put_weekly_scoring_record(context, record)
    result["ok"] = True
    result["record"] = record
    return result


def refresh_weekly_scoring(
    context: dict[str, Any],
    *,
    week: int,
    team: str,
    roster_df: pd.DataFrame,
    profile: HitterScoringProfile | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh current cumulative stats and compute weekly deltas without changing baseline."""
    try:
        from page_perf_phases import session_perf_phase

        phase_ctx = session_perf_phase(session or {}, "weekly_hitter_deltas")
    except ImportError:
        from contextlib import nullcontext

        phase_ctx = nullcontext()

    with phase_ctx:
        return _refresh_weekly_scoring_inner(
            context,
            week=week,
            team=team,
            roster_df=roster_df,
            profile=profile,
            session=session,
        )


def _refresh_weekly_scoring_inner(
    context: dict[str, Any],
    *,
    week: int,
    team: str,
    roster_df: pd.DataFrame,
    profile: HitterScoringProfile | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh current cumulative stats and compute weekly deltas without changing baseline."""
    result: dict[str, Any] = {"ok": False, "errors": [], "record": None}
    profile = profile or resolve_hitter_scoring_profile(context)
    if profile.blocked:
        result["errors"].append(profile.block_message)
        return result

    league_id = resolve_canonical_league_id(context)
    record = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
    if not isinstance(record, dict) or not record.get("baseline_created_at"):
        result["errors"].append("No weekly scoring baseline for this team/week.")
        return result
    if str(record.get("status") or "") == WEEK_SCORING_FINALIZED:
        result["ok"] = True
        result["record"] = record
        result["skipped"] = True
        return result

    frozen_profile = HitterScoringProfile.from_dict(record.get("scoring_profile")) or profile
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(name_col) or "").strip()
    }

    player_results: dict[str, Any] = {}
    for pkey, meta in {**record.get("starters", {}), **record.get("bench", {})}.items():
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("player_name") or "")
        row = lookup.get(name)
        if row is None:
            continue
        baseline = (record.get("baselines") or {}).get(pkey) or {}
        current = extract_cumulative_snapshot(row, frozen_profile)
        player_results[pkey] = compute_player_weekly_results(
            baseline=baseline,
            current=current,
            profile=frozen_profile,
            is_starter=bool(meta.get("is_starter")),
        )

    team_totals = compute_team_weekly_totals(player_results, frozen_profile)
    new_fingerprint = roster_data_fingerprint(roster_df)
    results_fingerprint = hashlib.sha1(
        repr((player_results, team_totals)).encode("utf-8", errors="ignore")
    ).hexdigest()[:16]
    prior_fp = str(record.get("results_fingerprint") or "")
    if (
        prior_fp
        and prior_fp == results_fingerprint
        and str(record.get("stats_fingerprint") or "") == new_fingerprint
    ):
        result["ok"] = True
        result["record"] = record
        result["skipped"] = True
        return result

    record["player_results"] = player_results
    record["team_totals"] = team_totals
    record["stats_fingerprint"] = new_fingerprint
    record["results_fingerprint"] = results_fingerprint
    record["stats_updated_at"] = _utc_now_iso()
    _put_weekly_scoring_record(context, record)
    result["ok"] = True
    result["record"] = record
    return result


def is_week_finalized_for_league(context: dict[str, Any], week: int) -> bool:
    league_id = resolve_canonical_league_id(context)
    if not league_id:
        return False
    fin_id = weekly_finalize_id(league_id, week)
    meta = (_scoring_root(context).get("finalized_weeks") or {})
    return isinstance(meta, dict) and fin_id in meta


def list_teams_in_league(context: dict[str, Any]) -> list[str]:
    rosters = context.get("league_rosters") or {}
    if isinstance(rosters, dict):
        return sorted(str(k) for k in rosters.keys() if str(k).strip())
    return []


def preview_finalize_week(
    context: dict[str, Any],
    *,
    week: int,
    roster_by_team: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Preview all teams before commissioner finalizes."""
    league_id = resolve_canonical_league_id(context)
    fin_id = weekly_finalize_id(league_id, week)
    if (_scoring_root(context).get("finalized_weeks") or {}).get(fin_id):
        return {"ok": False, "already_finalized": True, "errors": ["Week already finalized."]}

    profile = resolve_hitter_scoring_profile(context)
    if profile.blocked:
        return {"ok": False, "errors": [profile.block_message]}

    teams_preview: list[dict[str, Any]] = []
    unlocked: list[str] = []
    missing_data: list[str] = []

    for team in list_teams_in_league(context):
        record = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
        if not isinstance(record, dict) or not record.get("baseline_created_at"):
            unlocked.append(team)
            continue
        roster_df = roster_by_team.get(team)
        if roster_df is None or getattr(roster_df, "empty", True):
            missing_data.append(team)
            continue
        refresh = refresh_weekly_scoring(context, week=week, team=team, roster_df=roster_df, profile=profile)
        rec = refresh.get("record") or record
        unavailable = (rec.get("team_totals") or {}).get("unavailable") or {}
        for cat in profile.display_categories:
            if cat in unavailable:
                missing_data.append(f"{team}:{cat}")
        teams_preview.append(
            {
                "team": team,
                "totals": (rec.get("team_totals") or {}).get("totals") or {},
                "starter_count": (rec.get("team_totals") or {}).get("starter_count", 0),
            }
        )

    return {
        "ok": not unlocked and not missing_data,
        "teams_preview": teams_preview,
        "unlocked_teams": unlocked,
        "missing_data": missing_data,
        "finalize_id": fin_id,
    }


def finalize_week_for_league(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    week: int,
    roster_by_team: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Commissioner finalizes week — idempotent."""
    try:
        from page_perf_phases import session_perf_phase

        phase_ctx = session_perf_phase(session, "weekly_finalize")
    except ImportError:
        from contextlib import nullcontext

        phase_ctx = nullcontext()

    with phase_ctx:
        return _finalize_week_for_league_inner(
            session,
            context,
            week=week,
            roster_by_team=roster_by_team,
        )


def _finalize_week_for_league_inner(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    week: int,
    roster_by_team: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "errors": []}
    preview = preview_finalize_week(context, week=week, roster_by_team=roster_by_team)
    if preview.get("already_finalized"):
        result["ok"] = True
        result["skipped"] = True
        return result
    if preview.get("unlocked_teams"):
        result["errors"].append(f"Unlocked teams: {', '.join(preview['unlocked_teams'])}")
    if preview.get("missing_data"):
        result["errors"].append(f"Missing data: {', '.join(preview['missing_data'])}")
    if result["errors"]:
        return result

    league_id = resolve_canonical_league_id(context)
    fin_id = str(preview.get("finalize_id") or weekly_finalize_id(league_id, week))
    root = _scoring_root(context)
    finalized = root.setdefault("finalized_weeks", {})
    if fin_id in finalized:
        result["ok"] = True
        result["skipped"] = True
        return result

    standings_write_id = fin_id
    for team in list_teams_in_league(context):
        record = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
        if not isinstance(record, dict):
            continue
        record["status"] = WEEK_SCORING_FINALIZED
        record["finalized_at"] = _utc_now_iso()
        record["final_result_id"] = fin_id
        record["standings_write_id"] = standings_write_id
        _put_weekly_scoring_record(context, record)

    finalized[fin_id] = {
        "week": int(week),
        "finalized_at": _utc_now_iso(),
        "standings_write_id": standings_write_id,
        "teams": preview.get("teams_preview") or [],
    }
    apply_finalized_week_to_standings(context, week=week, finalize_id=fin_id)
    upsert_league_context(session, context)
    result["ok"] = True
    result["finalize_id"] = fin_id
    result["standings_write_id"] = standings_write_id
    return result


def apply_finalized_week_to_standings(
    context: dict[str, Any],
    *,
    week: int,
    finalize_id: str,
) -> None:
    """Merge finalized weekly team totals into cumulative hitter standings."""
    league_id = resolve_canonical_league_id(context)
    workflow = context.setdefault("workflow", {})
    cum = workflow.get(WORKFLOW_KEY_HITTER_STANDINGS_CUMULATIVE)
    if not isinstance(cum, dict):
        cum = {"teams": {}, "weeks": [], "profile": {}}
        workflow[WORKFLOW_KEY_HITTER_STANDINGS_CUMULATIVE] = cum

    if any(str(w.get("finalize_id") or "") == finalize_id for w in cum.get("weeks") or []):
        return

    profile = resolve_hitter_scoring_profile(context)
    teams_block = cum.setdefault("teams", {})
    week_entry = {"week": int(week), "finalize_id": finalize_id, "teams": {}}

    for team in list_teams_in_league(context):
        record = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
        if not isinstance(record, dict):
            continue
        totals = (record.get("team_totals") or {}).get("totals") or {}
        week_entry["teams"][team] = copy.deepcopy(totals)
        bucket = teams_block.setdefault(team, {"counting": {}, "components": {}})
        counting = bucket.setdefault("counting", {})
        components = bucket.setdefault("components", {})
        for cat, val in totals.items():
            if cat in RATE_CATEGORIES:
                continue
            if cat == "POINTS":
                counting["POINTS"] = float(counting.get("POINTS") or 0) + float(val or 0)
            elif cat in COUNTING_CATEGORIES or cat == "BB":
                counting[cat] = float(counting.get(cat) or 0) + float(val or 0)
        # Preserve rate components from player deltas for cumulative recalculation
        for pkey, pres in (record.get("player_results") or {}).items():
            if not isinstance(pres, dict) or not pres.get("counts_toward_score"):
                continue
            for f, v in (pres.get("deltas") or {}).items():
                if f in ("H", "AB", "BB", "HBP", "SF", "2B", "3B", "HR"):
                    components[f] = float(components.get(f) or 0) + float(v or 0)

    cum.setdefault("weeks", []).append(week_entry)
    cum["profile"] = profile.to_dict()
    cum["updated_at"] = _utc_now_iso()


def cumulative_standings_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Build display rows from cumulative hitter standings."""
    workflow = context.get("workflow") or {}
    cum = workflow.get(WORKFLOW_KEY_HITTER_STANDINGS_CUMULATIVE) or {}
    profile = HitterScoringProfile.from_dict(cum.get("profile")) or resolve_hitter_scoring_profile(context)
    rows: list[dict[str, Any]] = []
    for team, bucket in sorted((cum.get("teams") or {}).items()):
        counting = bucket.get("counting") or {}
        components = bucket.get("components") or {}
        row: dict[str, Any] = {"Fantasy Team": team}
        for cat in profile.display_categories:
            if cat in COUNTING_CATEGORIES or cat == "BB":
                row[cat] = counting.get(cat, 0)
            elif cat == "AVG":
                h = float(components.get("H") or 0)
                ab = float(components.get("AB") or 0)
                row["AVG"] = (h / ab) if ab > 0 else None
            elif cat == "OBP":
                row["OBP"] = _weekly_obp({k: float(components.get(k) or 0) for k in ("H", "AB", "BB", "HBP", "SF")})
            elif cat == "OPS":
                comps = {k: float(components.get(k) or 0) for k in ("H", "AB", "BB", "HBP", "SF", "2B", "3B", "HR")}
                obp = _weekly_obp(comps)
                slg = _weekly_slg(comps)
                row["OPS"] = (obp + slg) if obp is not None and slg is not None else None
        if profile.scoring_mode == "points":
            row["POINTS"] = counting.get("POINTS", 0)
        rows.append(row)
    return rows


def should_start_week_empty(context: dict[str, Any], week: int) -> bool:
    """True when prior week finalized — new week starts with empty circles."""
    if int(week) <= 1:
        return False
    return is_week_finalized_for_league(context, int(week) - 1)


def is_legacy_locked_lineup(saved_lineup: dict[str, Any] | None, scoring_record: dict[str, Any] | None) -> bool:
    if not isinstance(saved_lineup, dict):
        return False
    if str(saved_lineup.get("status") or "") != "locked":
        return False
    if scoring_record is None:
        return True
    if scoring_record.get("legacy"):
        return True
    return not bool(scoring_record.get("baseline_created_at"))


def diagnose_weekly_scoring_record(
    context: dict[str, Any] | None,
    *,
    week: int,
    team: str,
    saved_lineup: dict[str, Any] | None = None,
    roster_df: pd.DataFrame | None = None,
    profile: HitterScoringProfile | None = None,
) -> dict[str, Any]:
    """Structured diagnostics for weekly scoring visibility issues."""
    league_id = resolve_canonical_league_id(context or {})
    team_id = canonical_team_identity(context or {}, team)
    record = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
    starters = (record or {}).get("starters") or {}
    bench = (record or {}).get("bench") or {}
    player_results = (record or {}).get("player_results") or {}
    baselines = (record or {}).get("baselines") or {}
    prof = profile or resolve_hitter_scoring_profile(context)
    roster_cols = sorted(str(c) for c in (roster_df.columns if isinstance(roster_df, pd.DataFrame) else []))
    return {
        "canonical_league_id": league_id or None,
        "canonical_team_identity": team_id or None,
        "week": int(week),
        "record_key": weekly_team_record_key(league_id, team_id, week) if league_id and team_id else None,
        "lineup_status": str((saved_lineup or {}).get("status") or ""),
        "lineup_weekly_scoring_record_key": str((saved_lineup or {}).get("weekly_scoring_record_key") or "") or None,
        "baseline_created_at": (record or {}).get("baseline_created_at"),
        "legacy": bool((record or {}).get("legacy")),
        "starter_count": len(starters),
        "bench_count": len(bench),
        "baseline_player_count": len(baselines),
        "player_result_count": len(player_results),
        "scoring_profile": prof.to_dict() if prof else None,
        "stats_fingerprint": (record or {}).get("stats_fingerprint"),
        "stats_updated_at": (record or {}).get("stats_updated_at"),
        "roster_row_count": len(roster_df) if isinstance(roster_df, pd.DataFrame) else 0,
        "roster_has_hr": "HR" in roster_cols,
        "roster_has_ab": "AB" in roster_cols or "H" in roster_cols,
    }


def ensure_weekly_scoring_populated(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    week: int,
    team: str,
    roster_df: pd.DataFrame,
    profile: HitterScoringProfile | None = None,
) -> dict[str, Any] | None:
    """Refresh weekly deltas when baseline exists but player cards are empty."""
    record = get_weekly_scoring_record(context, week=week, team=team)
    if not isinstance(record, dict) or not record.get("baseline_created_at"):
        return record
    if record.get("player_results"):
        return record
    if roster_df is None or roster_df.empty:
        return record
    refresh = refresh_weekly_scoring(
        context,
        week=week,
        team=team,
        roster_df=roster_df,
        profile=profile,
        session=session,
    )
    if refresh.get("ok"):
        try:
            from fantasy_league_context import upsert_league_context

            upsert_league_context(session, context)
        except ImportError:
            pass
        return refresh.get("record") or get_weekly_scoring_record(context, week=week, team=team)
    return record


def start_weekly_tracking_from_now(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    week: int,
    team: str,
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
    profile: HitterScoringProfile | None = None,
) -> dict[str, Any]:
    """
    Commissioner-only: establish a new baseline from the current moment for a legacy locked week.
    Does not pretend to represent the beginning of the calendar week.
    """
    result: dict[str, Any] = {"ok": False, "errors": [], "record": None}
    profile = profile or resolve_hitter_scoring_profile(context, session=session)
    if profile.blocked:
        result["errors"].append(profile.block_message or "Weekly scoring blocked.")
        return result

    league_id = resolve_canonical_league_id(context)
    team_id = canonical_team_identity(context, team)
    key = weekly_team_record_key(league_id, team_id, week)
    existing = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
    if isinstance(existing, dict) and existing.get("baseline_created_at") and not existing.get("legacy"):
        result["ok"] = True
        result["record"] = existing
        result["skipped"] = True
        return result

    starters, bench, baselines = build_player_snapshots(roster_df, assignments, profile)
    now = _utc_now_iso()
    record = {
        "record_key": key,
        "canonical_league_id": league_id,
        "canonical_team_identity": team_id,
        "week": int(week),
        "scoring_mode": profile.scoring_mode,
        "scoring_profile": profile.to_dict(),
        "assignments": dict(assignments),
        "starters": starters,
        "bench": bench,
        "baselines": baselines,
        "baseline_created_at": now,
        "baseline_note": "Tracking started from current stats (not original week start).",
        "locked_at": now,
        "status": WEEK_SCORING_LOCKED,
        "finalized_at": "",
        "final_result_id": "",
        "standings_write_id": "",
        "stats_fingerprint": roster_data_fingerprint(roster_df),
        "stats_updated_at": now,
        "player_results": {},
        "team_totals": {},
        "legacy": False,
        "tracking_started_midweek": True,
    }
    _put_weekly_scoring_record(context, record)
    refresh_weekly_scoring(
        context,
        week=week,
        team=team,
        roster_df=roster_df,
        profile=profile,
        session=session,
    )
    try:
        from fantasy_league_context import upsert_league_context

        upsert_league_context(session, context)
        from fantasy_lineup_perf import invalidate_lineup_page_caches

        invalidate_lineup_page_caches(session)
    except ImportError:
        pass
    result["ok"] = True
    result["record"] = get_weekly_scoring_record(context, week=week, team=team)
    return result


def maybe_mark_legacy_lineup_scoring(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    week: int,
    team: str,
    saved_lineup: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Mark pre-scoring locked lineups as legacy only when the saved lineup predates weekly scoring.
    """
    if not isinstance(saved_lineup, dict) or str(saved_lineup.get("status") or "") != "locked":
        return context
    if str(saved_lineup.get("weekly_scoring_record_key") or "").strip():
        return context
    if get_weekly_scoring_record(context, week=week, team=team):
        return context
    mark_legacy_lineup_scoring(context, week=week, team=team)
    try:
        from fantasy_league_context import upsert_league_context

        return upsert_league_context(session, context)
    except ImportError:
        return context


def mark_legacy_lineup_scoring(
    context: dict[str, Any],
    *,
    week: int,
    team: str,
) -> None:
    """Label old locked lineups without baselines as legacy — never retro-baseline."""
    league_id = resolve_canonical_league_id(context)
    key = weekly_team_record_key(league_id, canonical_team_identity(context, team), week)
    record = get_weekly_scoring_record(context, week=week, team=team, league_id=league_id)
    if isinstance(record, dict):
        return
    _put_weekly_scoring_record(
        context,
        {
            "record_key": key,
            "canonical_league_id": league_id,
            "canonical_team_identity": canonical_team_identity(context, team),
            "week": int(week),
            "status": WEEK_SCORING_LOCKED,
            "legacy": True,
            "baseline_created_at": "",
        },
    )
