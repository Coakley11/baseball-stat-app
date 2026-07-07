"""Canonical host-configured roster slots for Live Draft and post-draft analysis."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

# Host slot order when expanding counts into separate slot instances.
_SLOT_EXPAND_ORDER: tuple[tuple[str, str], ...] = (
    ("C", "C"),
    ("1B", "1B"),
    ("2B", "2B"),
    ("3B", "3B"),
    ("SS", "SS"),
    ("OF", "OF"),
    ("DH", "UTIL"),
    ("P", "P"),
    ("BN", "BN"),
)

_POSITION_CODES = ("C", "1B", "2B", "3B", "SS", "OF", "DH", "P", "BN")

LIVE_SLOT_WIDGET_KEYS: dict[str, str] = {
    "C": "live_slot_c",
    "1B": "live_slot_1b",
    "2B": "live_slot_2b",
    "3B": "live_slot_3b",
    "SS": "live_slot_ss",
    "OF": "live_slot_of",
    "DH": "live_slot_dh",
    "P": "live_slot_p",
    "BN": "live_slot_bench",
}


def session_slot_count(session: dict[str, Any] | None, widget_key: str, default: int = 0) -> int:
    """Read a roster slot widget value; 0 is valid and must not fall back to defaults."""
    session = session or {}
    if widget_key not in session:
        return int(default)
    try:
        return int(session[widget_key])
    except (TypeError, ValueError):
        return int(default)


def slots_dict_from_session_widgets(session: dict[str, Any] | None) -> dict[str, int]:
    """Build host slot counts from live draft setup widgets."""
    return {
        pos: session_slot_count(session, widget_key, 0)
        for pos, widget_key in LIVE_SLOT_WIDGET_KEYS.items()
    }


def sync_live_slot_widgets_from_config(session: dict[str, Any] | None, config: dict[str, Any] | None) -> None:
    """Mirror persisted room slot config into setup widgets after restore."""
    slots = get_required_position_counts(config)
    if not any(int(n or 0) > 0 for n in slots.values()):
        return
    session = session or {}
    for pos, widget_key in LIVE_SLOT_WIDGET_KEYS.items():
        session[widget_key] = int(slots.get(pos, 0) or 0)


def _slot_instances_match_slots(config: dict[str, Any] | None) -> bool:
    cfg = dict(config or {})
    slots = _slots_dict(cfg)
    instances = cfg.get("slot_instances")
    if not isinstance(instances, list) or not instances:
        return False
    if len(instances) != sum(int(slots.get(code, 0) or 0) for code in _POSITION_CODES):
        return False
    inst_counts: dict[str, int] = {}
    for slot in instances:
        if not isinstance(slot, dict):
            return False
        pos = str(slot.get("position") or "").strip()
        if not pos:
            return False
        inst_counts[pos] = int(inst_counts.get(pos, 0) or 0) + 1
    return all(inst_counts.get(code, 0) == int(slots.get(code, 0) or 0) for code in _POSITION_CODES)


def normalize_draft_slot_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Slots dict is authoritative; regenerate slot_instances when stale or missing."""
    cfg = dict(config or {})
    raw_slots = cfg.get("slots")
    if not isinstance(raw_slots, dict) or not raw_slots:
        return cfg
    cfg["slots"] = _slots_dict(cfg)
    if not _slot_instances_match_slots(cfg):
        cfg = freeze_slot_instances_on_config(cfg)
    return cfg


def coerce_room_config(raw: Any) -> dict[str, Any]:
    """Normalize room config from dict, legacy list/tuple, or empty."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (list, tuple)):
        if raw and all(isinstance(x, str) for x in raw):
            return {"slots": {}}
        instances = [
            dict(item)
            for item in raw
            if isinstance(item, dict) and str(item.get("position") or item.get("position_code") or "").strip()
        ]
        if instances:
            return {"slot_instances": instances}
        return {"slots": {}}
    return {}


def ensure_room_slot_config(room: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize host slot config on an in-memory live draft room."""
    if not isinstance(room, dict):
        return room
    cfg = coerce_room_config(room.get("config"))
    if cfg.get("slot_instances") and not cfg.get("slots"):
        counts: dict[str, int] = {}
        for inst in cfg["slot_instances"]:
            if isinstance(inst, dict):
                pos = str(inst.get("position") or inst.get("position_code") or "").strip()
                if pos:
                    counts[pos] = counts.get(pos, 0) + 1
        if counts:
            cfg["slots"] = counts
    if not cfg.get("slots") and not cfg.get("slot_instances"):
        room["config"] = cfg
        return room
    room["config"] = normalize_draft_slot_config(cfg)
    return room


def _slots_dict(config: dict[str, Any] | None) -> dict[str, int]:
    cfg = dict(config or {})
    raw = dict(cfg.get("slots") or {})
    return {code: int(raw.get(code, 0) or 0) for code in _POSITION_CODES}


def get_required_position_counts(config: dict[str, Any] | None) -> dict[str, int]:
    """Per-position targets from host-created draft configuration."""
    return _slots_dict(config)


def get_active_position_codes(config: dict[str, Any] | None, *, include_bench: bool = False) -> set[str]:
    """Position codes with target > 0 (active in this draft)."""
    counts = get_required_position_counts(config)
    codes = {pos for pos, n in counts.items() if n > 0 and (include_bench or pos != "BN")}
    return codes


def _expand_slot_instances_from_counts(counts: dict[str, int]) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    of_counter = 0
    for pos_key, display_base in _SLOT_EXPAND_ORDER:
        target = int(counts.get(pos_key, 0) or 0)
        for i in range(target):
            if pos_key == "OF" and target > 1:
                of_counter += 1
                label = f"OF {of_counter}"
            elif pos_key == "DH":
                label = "UTIL" if target == 1 else f"UTIL {i + 1}"
            elif target > 1:
                label = f"{display_base} {i + 1}"
            else:
                label = display_base
            instances.append(
                {
                    "position": pos_key,
                    "label": label,
                    "slot_index": len(instances),
                }
            )
    return instances


def get_active_draft_roster_slots(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Ordered slot instances — duplicate positions are separate entries (e.g. three OF slots)."""
    cfg = dict(config or {})
    counts = _slots_dict(cfg)
    if isinstance(cfg.get("slot_instances"), list) and cfg["slot_instances"] and _slot_instances_match_slots(cfg):
        out: list[dict[str, Any]] = []
        for i, slot in enumerate(cfg["slot_instances"]):
            if not isinstance(slot, dict):
                continue
            pos = str(slot.get("position") or "").strip()
            if not pos:
                continue
            out.append(
                {
                    "position": pos,
                    "label": str(slot.get("label") or pos),
                    "slot_index": int(slot.get("slot_index", i)),
                }
            )
        if out:
            return out
    return _expand_slot_instances_from_counts(counts)


def freeze_slot_instances_on_config(config: dict[str, Any]) -> dict[str, Any]:
    """Persist ordered slot instances on room config at draft start."""
    cfg = dict(config or {})
    counts = _slots_dict(cfg)
    cfg["slots"] = counts
    cfg["slot_instances"] = _expand_slot_instances_from_counts(counts)
    return cfg


def _normalize_pos_token(token: str) -> str:
    t = str(token or "").upper().strip()
    if t in ("LF", "CF", "RF"):
        return "OF"
    if t in ("SP", "RP"):
        return "P"
    return t


def _split_position_tokens(primary_val: Any) -> list[str]:
    if primary_val is None or (isinstance(primary_val, float) and pd.isna(primary_val)):
        return []
    s = str(primary_val).upper().replace(" ", "")
    parts = re.split(r"[,/\+]", s)
    out = [_normalize_pos_token(p.strip()) for p in parts if p.strip()]
    if not out:
        out = [_normalize_pos_token(str(primary_val))]
    return list(dict.fromkeys(out))


def _player_position_tokens(row: pd.Series) -> list[str]:
    tokens: list[str] = []
    for col in ("Primary Position", "Position", "Eligibility", "Positions"):
        if col in row.index:
            tokens.extend(_split_position_tokens(row.get(col)))
    if isinstance(row.get("_position_tokens"), list):
        tokens.extend(_normalize_pos_token(str(t)) for t in row.get("_position_tokens") if str(t).strip())
    tokens = list(dict.fromkeys(tokens))
    return tokens or ["DH"]


def _eligible_for_draft_slot(pos_tokens: list[str], position_code: str) -> bool:
    slot = "UTIL" if position_code == "DH" else position_code
    if slot == "BN":
        return True
    if slot == "P":
        return any(p in ("P", "SP", "RP") for p in pos_tokens)
    if slot == "UTIL":
        return not any(p in ("P", "SP", "RP") for p in pos_tokens)
    if slot == "OF":
        return any(p == "OF" for p in pos_tokens)
    if slot in ("C", "1B", "2B", "3B", "SS"):
        if pos_tokens == ["DH"]:
            return False
        if slot in pos_tokens:
            return True
        if slot == "1B" and "3B" in pos_tokens:
            return True
        if slot == "3B" and "1B" in pos_tokens:
            return True
        if slot == "2B" and "SS" in pos_tokens:
            return True
        if slot == "SS" and "2B" in pos_tokens:
            return True
    return False


def assign_roster_to_slot_instances(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assign drafted players to host slot instances in canonical order."""
    slots = get_active_draft_roster_slots(config)
    if not slots:
        return {"lines": [], "filled": 0, "target": 0, "gaps": [], "open_positions": []}

    df = roster_df.copy() if roster_df is not None and not roster_df.empty else pd.DataFrame()
    if not df.empty:
        df = df.reset_index(drop=True)
        df["_pos_tokens"] = df.apply(_player_position_tokens, axis=1)
        if "Expected Fantasy Value" in df.columns:
            df["_slot_score"] = pd.to_numeric(df["Expected Fantasy Value"], errors="coerce").fillna(0.0)
        else:
            df["_slot_score"] = 0.0
    assigned: set[int] = set()
    lines: list[dict[str, Any]] = []
    gaps: list[str] = []

    for slot in slots:
        pos = str(slot.get("position") or "")
        label = str(slot.get("label") or pos)
        best_ix: int | None = None
        best_score = -1.0
        if not df.empty:
            for ix in df.index:
                if ix in assigned:
                    continue
                toks = df.at[ix, "_pos_tokens"]
                if not isinstance(toks, list):
                    toks = []
                if not _eligible_for_draft_slot(toks, pos):
                    continue
                score = float(df.at[ix, "_slot_score"] or 0.0)
                if score > best_score:
                    best_score = score
                    best_ix = int(ix)
        is_filled = best_ix is not None
        if is_filled:
            assigned.add(best_ix)
        else:
            gaps.append(pos)
        lines.append({"label": label, "position": pos, "filled": is_filled})

    open_labels = sorted({ln["label"] for ln in lines if not ln["filled"]})
    filled_total = sum(1 for ln in lines if ln["filled"])
    return {
        "lines": lines,
        "filled": filled_total,
        "target": len(slots),
        "gaps": gaps,
        "open_positions": open_labels,
    }


def get_filled_position_counts(roster_df: pd.DataFrame | None) -> dict[str, int]:
    """How many drafted players per Primary Position on one team."""
    if roster_df is None or roster_df.empty or "Primary Position" not in roster_df.columns:
        return {}
    return {
        str(k): int(v)
        for k, v in roster_df["Primary Position"].fillna("DH").astype(str).value_counts().items()
    }


def get_remaining_position_needs(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any] | None,
) -> list[str]:
    """Open slot position codes — excludes bench; duplicates preserved (e.g. three OF)."""
    gaps = list(assign_roster_to_slot_instances(roster_df, config).get("gaps") or [])
    return [g for g in gaps if str(g or "").strip().upper() not in ("BN", "BENCH")]


def get_league_remaining_demand(room: dict[str, Any] | None, config: dict[str, Any] | None) -> dict[str, int]:
    """League-wide open roster slots per position code."""
    cfg = dict(config or {})
    if room and not cfg.get("slots"):
        cfg = dict(room.get("config") or {})
    counts = get_required_position_counts(cfg)
    demand = {pos: 0 for pos in counts}
    teams = list((room or {}).get("teams") or [])
    if not teams:
        teams = [""]
    for team in teams:
        roster_df = pd.DataFrame()
        if room and team:
            roster_df = pd.DataFrame((room.get("rosters") or {}).get(str(team), []) or [])
        needs = get_remaining_position_needs(roster_df, cfg)
        for pos in needs:
            if pos in demand:
                demand[pos] = int(demand.get(pos, 0) or 0) + 1
    return demand


def live_draft_target_counts(config: dict[str, Any] | None) -> dict[str, int]:
    """Backward-compatible alias used by scoring and tracker modules."""
    return get_required_position_counts(config)


def _config_with_slots_from_mapping(data: dict[str, Any] | None) -> dict[str, Any]:
    """Extract host slot config from a room dict or persisted blob."""
    if not isinstance(data, dict):
        return {}
    cfg = dict(data.get("config") or {})
    if cfg.get("slots"):
        if data.get("slot_instances") and not cfg.get("slot_instances"):
            cfg = {**cfg, "slot_instances": data["slot_instances"]}
        return cfg
    return {}


def resolve_draft_slot_config_from_session(session: dict[str, Any] | None) -> dict[str, Any]:
    """Host slot config from live draft room, canonical blob, or draft-lab handoff."""
    session = session or {}
    try:
        from live_draft_state import LIVE_DRAFT_PAGE_BLOCK, LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state

        prepare_live_draft_state(session)
    except ImportError:
        LIVE_DRAFT_PAGE_BLOCK = "Live Draft Room"
        LIVE_DRAFT_ROOM_KEY = "live_draft_room"

    room = session.get("live_draft_room")
    cfg = _config_with_slots_from_mapping(room if isinstance(room, dict) else None)
    if cfg.get("slots"):
        return normalize_draft_slot_config(cfg)

    blob = session.get("live_draft_state")
    cfg = _config_with_slots_from_mapping(blob if isinstance(blob, dict) else None)
    if cfg.get("slots"):
        return normalize_draft_slot_config(cfg)

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK) or pf.get("live_draft")
        if isinstance(block, dict):
            legacy = block.get(LIVE_DRAFT_ROOM_KEY) or block.get("live_draft_room")
            cfg = _config_with_slots_from_mapping(legacy if isinstance(legacy, dict) else None)
            if cfg.get("slots"):
                return normalize_draft_slot_config(cfg)

    lab = session.get("draft_lab_results")
    if isinstance(lab, dict):
        handoff = lab.get("handoff")
        if isinstance(handoff, dict) and handoff.get("slots"):
            out = {"slots": dict(handoff["slots"])}
            if handoff.get("slot_instances"):
                out["slot_instances"] = handoff["slot_instances"]
            return normalize_draft_slot_config(out)
    return {}


def position_codes_in_slot_order(config: dict[str, Any] | None) -> list[str]:
    """Active position codes in host slot display order (excludes bench)."""
    active = get_active_position_codes(config, include_bench=False)
    return [code for code, _ in _SLOT_EXPAND_ORDER if code in active]


def format_open_position_needs(gaps: list[str] | None) -> str:
    """Deduped open-need label for summary banners."""
    _flex = frozenset({"DH", "UTIL", "BN", "BENCH"})
    filtered = [g for g in (gaps or []) if str(g or "").strip().upper() not in ("BN", "BENCH")]
    if not filtered:
        return "All Positions"
    if all(str(g or "").strip().upper() in _flex for g in filtered):
        return "All Positions"
    seen: list[str] = []
    for g in filtered:
        s = str(g or "").strip()
        if s.upper() == "DH":
            s = "UTIL"
        if s and s not in seen:
            seen.append(s)
    return ", ".join(seen) if seen else "All Positions"


def config_includes_pitcher_slots(config: dict[str, Any] | None) -> bool:
    """True when the host draft config includes at least one pitcher slot."""
    return int(get_required_position_counts(config).get("P") or 0) > 0


def session_includes_pitcher_slots(session: dict[str, Any] | None) -> bool:
    """True when live setup or resolved config includes pitcher slots."""
    cfg = resolve_draft_slot_config_from_session(session)
    if cfg.get("slots"):
        return config_includes_pitcher_slots(cfg)
    return session_slot_count(session, "live_slot_p", 0) > 0


def _resolve_format_includes_pitching(
    *,
    context: dict[str, Any] | None = None,
    fantasy_format: str | None = None,
) -> bool:
    fmt = str(fantasy_format or "").strip()
    if not fmt and context:
        fmt = str(context.get("fantasy_format") or "5x5 Roto").strip()
    if not fmt:
        fmt = "5x5 Roto"
    try:
        from fantasy_waiver_wire import fantasy_format_includes_pitching

        return fantasy_format_includes_pitching(fmt, context)
    except ImportError:
        return False


def _resolve_has_pitcher_slots(
    *,
    config: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    if config is not None and dict(config or {}).get("slots"):
        return config_includes_pitcher_slots(config)
    if context is not None:
        try:
            from fantasy_league_context import resolve_context_draft_slot_config

            ctx_cfg = resolve_context_draft_slot_config(context)
            if ctx_cfg.get("slots"):
                return config_includes_pitcher_slots(ctx_cfg)
        except Exception:
            pass
    if session is not None:
        return session_includes_pitcher_slots(session)
    return False


def league_allows_pitcher_recommendations(
    *,
    config: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    fantasy_format: str | None = None,
) -> bool:
    """Pitchers belong in recommendation pools only when P slots exist and format includes pitching."""
    return bool(
        _resolve_has_pitcher_slots(config=config, session=session, context=context)
        and _resolve_format_includes_pitching(context=context, fantasy_format=fantasy_format)
    )


def _player_has_hitter_eligibility(row: pd.Series) -> bool:
    """True when a row can fill a non-pitcher fantasy slot (keeps two-way hitters like Ohtani)."""
    primary = str(row.get("Primary Position") or row.get("Position") or "").upper().strip()
    if primary and primary not in ("P", "SP", "RP"):
        return True
    elig = str(row.get("Eligible Positions") or row.get("Eligibility") or row.get("Positions") or "")
    for tok in re.split(r"[,/\+]", elig.upper()):
        token = tok.strip()
        if token and token not in ("P", "SP", "RP"):
            return True
    ab = pd.to_numeric(row.get("AB"), errors="coerce")
    if pd.notna(ab) and float(ab) > 0:
        return True
    for col in ("HR", "RBI", "R", "H", "proj_HR", "proj_RBI", "proj_R"):
        if col in row.index:
            val = pd.to_numeric(row.get(col), errors="coerce")
            if pd.notna(val) and float(val) > 0:
                return True
    return False


def _is_pitcher_only_player_row(row: pd.Series) -> bool:
    """True for SP/RP/P-only rows that should be hard-excluded from hitter-only pools."""
    if _player_has_hitter_eligibility(row):
        return False
    pos = str(row.get("Primary Position") or row.get("Position") or "").upper().strip()
    if pos in ("P", "SP", "RP"):
        return True
    for col in ("W", "SV", "ERA", "WHIP"):
        if col in row.index and pd.notna(row.get(col)):
            if col in ("ERA", "WHIP") or float(pd.to_numeric(row.get(col), errors="coerce") or 0) > 0:
                return True
    return False


def _is_pitcher_player_row(row: pd.Series) -> bool:
    """Backward-compatible alias — prefer _is_pitcher_only_player_row."""
    return _is_pitcher_only_player_row(row)


def exclude_pitchers_when_no_pitcher_slots(
    df: pd.DataFrame | None,
    *,
    config: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    fantasy_format: str | None = None,
) -> pd.DataFrame:
    """Hard-drop SP/RP/P-only rows when includes_pitching is false or pitcher slots are zero."""
    if df is None or getattr(df, "empty", True):
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if league_allows_pitcher_recommendations(
        config=config,
        session=session,
        context=context,
        fantasy_format=fantasy_format,
    ):
        return df.copy()
    mask = ~df.apply(_is_pitcher_only_player_row, axis=1)
    return df.loc[mask].copy()
