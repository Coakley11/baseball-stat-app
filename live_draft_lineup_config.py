"""Live Draft lineup configuration — persist, repair, and guard setup workflow."""

from __future__ import annotations

import copy
from typing import Any

from fantasy_league_context import (
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_REAL_LEAGUE,
    context_has_roster_slots,
    get_league_context,
    upsert_league_context,
)

# Standard 10-player hitter league (9 starters + 1 bench) — migration fallback only.
STANDARD_10_HITTER_SLOTS: dict[str, int] = {
    "C": 1,
    "1B": 1,
    "2B": 1,
    "3B": 1,
    "SS": 1,
    "OF": 3,
    "DH": 1,
    "P": 0,
    "BN": 1,
}

KNOWN_ROBINS_DRAFT_ID = "c6810611c73e"
KNOWN_ROBINS_CONTEXT_ID = "archive:c6810611c73e"
KNOWN_ROBINS_LEAGUE_ID = "league:c4eefe793c8abac4764346d6"

REPAIR_SESSION_KEY = "_live_draft_lineup_config_repair_done"


def _creation_origin(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    meta = dict(context.get("metadata") or {})
    return str(
        meta.get("creation_origin") or context.get("creation_origin") or ""
    ).strip()


def is_live_draft_league_context(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    ctx_type = str(context.get("context_type") or "").strip()
    origin = _creation_origin(context)
    if origin == CREATION_ORIGIN_LIVE_DRAFT_ROOM:
        return True
    if ctx_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT:
        return True
    return False


def build_live_draft_slot_config(
    *,
    roster_size: int = 10,
    slots: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build normalized slot config for a completed Live Draft league."""
    slot_map = dict(slots or STANDARD_10_HITTER_SLOTS)
    if roster_size > 0:
        starters = sum(int(v or 0) for k, v in slot_map.items() if k != "BN")
        bench = max(0, roster_size - starters)
        slot_map["BN"] = bench
    raw = {"slots": slot_map}
    try:
        from live_draft_roster_slots import freeze_slot_instances_on_config, normalize_draft_slot_config

        return normalize_draft_slot_config(freeze_slot_instances_on_config(raw))
    except ImportError:
        return raw


def persist_live_draft_lineup_metadata(
    context: dict[str, Any],
    slot_config: dict[str, Any],
    *,
    roster_size: int = 0,
    draft_rounds: int = 0,
    team_count: int = 0,
) -> dict[str, Any]:
    """Attach lineup metadata to a league context (all schema copies aligned)."""
    ctx = copy.deepcopy(context)
    roster_settings = dict(ctx.get("roster_settings") or {})
    slots = dict(slot_config.get("slots") or {})
    instances = list(slot_config.get("slot_instances") or [])
    roster_settings["roster_slots"] = slots
    roster_settings["slot_instances"] = instances
    starter_count = sum(int(v or 0) for k, v in slots.items() if k != "BN")
    bench_count = int(slots.get("BN") or 0)
    if roster_size <= 0:
        roster_size = starter_count + bench_count
    roster_settings["live_draft_lineup_config"] = {
        "lineup_slots": _starter_slot_tokens(instances, slots),
        "starter_count": starter_count,
        "bench_count": bench_count,
        "roster_size": roster_size,
        "draft_rounds": int(draft_rounds or roster_size),
        "team_count": int(team_count or 0),
        "configuration_source": "live_draft_setup",
    }
    ctx["roster_settings"] = roster_settings
    return ctx


def _starter_slot_tokens(instances: list[Any], slots: dict[str, int]) -> list[str]:
    tokens: list[str] = []
    if instances:
        for inst in instances:
            if not isinstance(inst, dict):
                continue
            pos = str(inst.get("position") or "").strip()
            if pos and pos not in ("BN", "P"):
                tokens.append("UTIL" if pos == "DH" else pos)
        return tokens
    try:
        from live_draft_roster_slots import freeze_slot_instances_on_config

        frozen = freeze_slot_instances_on_config({"slots": slots})
        for inst in frozen.get("slot_instances") or []:
            if not isinstance(inst, dict):
                continue
            pos = str(inst.get("position") or "").strip()
            if pos and pos not in ("BN", "P"):
                tokens.append("UTIL" if pos == "DH" else pos)
    except ImportError:
        pass
    return tokens


def _slot_config_from_archive(archive: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(archive, dict):
        return None
    slots = archive.get("roster_slots")
    instances = archive.get("slot_instances")
    if isinstance(slots, dict) and any(int(v or 0) > 0 for v in slots.values()):
        raw = {"slots": dict(slots), "slot_instances": list(instances or [])}
        try:
            from live_draft_roster_slots import normalize_draft_slot_config

            return normalize_draft_slot_config(raw)
        except ImportError:
            return raw
    return None


def _slot_config_from_shared(session: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from fantasy_league_identity import resolve_canonical_league_id
        from fantasy_shared_league_store import load_shared_league

        league_id = resolve_canonical_league_id(context)
        if not league_id:
            return None
        shared = load_shared_league(league_id)
        if not isinstance(shared, dict):
            return None
        rs = shared.get("roster_settings")
        if not isinstance(rs, dict):
            return None
        slots = rs.get("roster_slots")
        if isinstance(slots, dict) and any(int(v or 0) > 0 for v in slots.values()):
            raw = {"slots": dict(slots), "slot_instances": list(rs.get("slot_instances") or [])}
            from live_draft_roster_slots import normalize_draft_slot_config

            return normalize_draft_slot_config(raw)
    except ImportError:
        pass
    return None


def resolve_live_draft_lineup_slot_config(
    session: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    archive: dict[str, Any] | None = None,
    roster_size_hint: int = 0,
) -> dict[str, Any] | None:
    """Best-effort slot config for a Live Draft league — never returns simulator setup state."""
    if not is_live_draft_league_context(context):
        return None
    if context_has_roster_slots(context):
        try:
            from fantasy_league_context import resolve_context_draft_slot_config

            cfg = resolve_context_draft_slot_config(context)
            if cfg.get("slots") or cfg.get("slot_instances"):
                return cfg
        except ImportError:
            pass
    for candidate in (
        _slot_config_from_archive(archive),
        _slot_config_from_shared(session, context) if isinstance(context, dict) else None,
    ):
        if candidate:
            return candidate
    if roster_size_hint == 10 or _context_roster_size(context) == 10:
        return build_live_draft_slot_config(roster_size=10)
    return None


def _context_roster_size(context: dict[str, Any] | None) -> int:
    if not isinstance(context, dict):
        return 0
    rosters = context.get("league_rosters")
    if isinstance(rosters, dict) and rosters:
        first = next(iter(rosters.values()))
        if isinstance(first, list):
            return len(first)
    meta = dict(context.get("metadata") or {})
    try:
        return int(meta.get("roster_size") or meta.get("draft_rounds") or 0)
    except (TypeError, ValueError):
        return 0


def repair_live_draft_lineup_config_for_context(
    session: dict[str, Any],
    *,
    draft_id: str,
    context_id: str = "",
    league_id: str = "",
    allow_standard_fallback: bool = False,
) -> dict[str, Any]:
    """In-place repair — populate roster_slots from archive/shared/fallback."""
    from draft_archive_state import get_draft_archive
    from fantasy_league_context import context_id_for_archive

    draft_id = str(draft_id or "").strip()
    trace: dict[str, Any] = {
        "draft_id": draft_id,
        "repaired": False,
        "source": "",
    }
    if not draft_id:
        trace["skipped"] = "missing_draft_id"
        return trace

    ctx_id = str(context_id or context_id_for_archive(draft_id)).strip()
    ctx = get_league_context(session, ctx_id)
    if not isinstance(ctx, dict):
        trace["skipped"] = "missing_context"
        return trace
    if not is_live_draft_league_context(ctx):
        trace["skipped"] = "not_live_draft"
        return trace
    if context_has_roster_slots(ctx):
        trace["skipped"] = "already_has_slots"
        return trace

    archive = get_draft_archive(session, draft_id)
    slot_cfg = resolve_live_draft_lineup_slot_config(
        session,
        ctx,
        archive=archive,
        roster_size_hint=_context_roster_size(ctx),
    )
    if not slot_cfg and allow_standard_fallback and _context_roster_size(ctx) == 10:
        slot_cfg = build_live_draft_slot_config(roster_size=10)
        trace["source"] = "standard_10_hitter_fallback"
    elif slot_cfg:
        trace["source"] = "archive_or_shared"
    if not slot_cfg:
        trace["skipped"] = "no_slot_config_found"
        return trace

    team_count = len(dict(ctx.get("league_rosters") or {}))
    patched = persist_live_draft_lineup_metadata(
        ctx,
        slot_cfg,
        roster_size=_context_roster_size(ctx) or 10,
        team_count=team_count,
    )
    upsert_league_context(session, patched, mark_persist_authoritative=True)
    trace["repaired"] = True

    if isinstance(archive, dict) and not archive.get("roster_slots"):
        from draft_archive_state import DRAFT_ARCHIVE_KEY

        entries = session.get(DRAFT_ARCHIVE_KEY)
        if isinstance(entries, list):
            for i, row in enumerate(entries):
                if isinstance(row, dict) and str(row.get("draft_id") or "") == draft_id:
                    patched_arch = dict(row)
                    patched_arch["roster_slots"] = dict(slot_cfg.get("slots") or {})
                    patched_arch["slot_instances"] = list(slot_cfg.get("slot_instances") or [])
                    entries[i] = patched_arch
                    trace["archive_updated"] = True
                    break

    lid = str(league_id or "").strip()
    if not lid:
        try:
            from fantasy_league_identity import resolve_canonical_league_id

            lid = str(resolve_canonical_league_id(patched) or "").strip()
        except ImportError:
            lid = ""
    if lid:
        try:
            from fantasy_shared_league_store import load_shared_league, save_shared_league

            shared = load_shared_league(lid)
            if isinstance(shared, dict):
                shared = dict(shared)
                rs = dict(shared.get("roster_settings") or {})
                rs["roster_slots"] = dict(slot_cfg.get("slots") or {})
                rs["slot_instances"] = list(slot_cfg.get("slot_instances") or [])
                rs["live_draft_lineup_config"] = dict(
                    (patched.get("roster_settings") or {}).get("live_draft_lineup_config") or {}
                )
                shared["roster_settings"] = rs
                save_shared_league(shared)
                trace["shared_updated"] = True
        except ImportError:
            pass

    return trace


def repair_known_live_draft_lineup_configs(session: dict[str, Any]) -> dict[str, Any]:
    """One-time session repair for canonical Live Draft leagues missing slot config."""
    if session.get(REPAIR_SESSION_KEY):
        return {"skipped": "already_done"}
    traces: list[dict[str, Any]] = []
    traces.append(
        repair_live_draft_lineup_config_for_context(
            session,
            draft_id=KNOWN_ROBINS_DRAFT_ID,
            context_id=KNOWN_ROBINS_CONTEXT_ID,
            league_id=KNOWN_ROBINS_LEAGUE_ID,
            allow_standard_fallback=True,
        )
    )
    session[REPAIR_SESSION_KEY] = True
    return {"traces": traces}


def live_draft_skips_lineup_format_setup(context: dict[str, Any] | None) -> bool:
    """True when commissioner position setup must not appear."""
    if not isinstance(context, dict):
        return False
    if is_live_draft_league_context(context) and context_has_roster_slots(context):
        return True
    origin = _creation_origin(context)
    if origin == CREATION_ORIGIN_LIVE_DRAFT_ROOM:
        return context_has_roster_slots(context)
    ctx_type = str(context.get("context_type") or "").strip()
    if ctx_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT:
        return context_has_roster_slots(context)
    if ctx_type == CONTEXT_TYPE_REAL_LEAGUE and origin == CREATION_ORIGIN_LIVE_DRAFT_ROOM:
        return context_has_roster_slots(context)
    return False
