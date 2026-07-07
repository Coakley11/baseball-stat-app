"""Stable canonical league identity — fingerprint-based league_id without save timestamps."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fantasy_league_context import normalize_player_key

FINGERPRINT_PREFIX = "league:"


def _normalize_settings_block(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in sorted(raw.keys()):
        val = raw[key]
        if isinstance(val, (str, int, float, bool)) or val is None:
            out[str(key)] = val
        elif isinstance(val, (list, tuple)):
            out[str(key)] = [str(x).strip() for x in val if str(x).strip()]
        elif isinstance(val, dict):
            out[str(key)] = _normalize_settings_block(val)
    return out


def _normalize_roster_settings(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"roster_slots": {}, "slot_instances": []}
    roster_slots = raw.get("roster_slots") or {}
    slot_instances = raw.get("slot_instances") or []
    slots_out: dict[str, Any] = {}
    if isinstance(roster_slots, dict):
        for slot, count in sorted(roster_slots.items()):
            slots_out[str(slot).strip()] = int(count or 0)
    instances_out: list[str] = []
    if isinstance(slot_instances, list):
        for item in slot_instances:
            if isinstance(item, dict):
                instances_out.append(
                    json.dumps(item, sort_keys=True, separators=(",", ":"))
                )
            else:
                text = str(item or "").strip()
                if text:
                    instances_out.append(text)
        instances_out.sort()
    return {"roster_slots": slots_out, "slot_instances": instances_out}


def _stable_roster_payload(league_rosters: Any) -> dict[str, list[str]]:
    if not isinstance(league_rosters, dict):
        return {}
    out: dict[str, list[str]] = {}
    for team_name in sorted(league_rosters.keys()):
        team = str(team_name or "").strip()
        if not team:
            continue
        entry = league_rosters.get(team_name)
        players = entry.get("players") if isinstance(entry, dict) else []
        keys: list[str] = []
        if isinstance(players, list):
            for player in players:
                if not isinstance(player, dict):
                    continue
                key = str(
                    player.get("player_key")
                    or normalize_player_key(player.get("player_name"))
                ).strip()
                if key:
                    keys.append(key)
        out[team] = sorted(set(keys))
    return out


def _draft_structure_payload(context: dict[str, Any]) -> dict[str, Any]:
    rosters = context.get("league_rosters") or {}
    teams = sorted(_stable_roster_payload(rosters).keys())
    pick_counts = {
        team: len(_stable_roster_payload(rosters).get(team) or [])
        for team in teams
    }
    return {
        "team_count": len(teams),
        "teams": teams,
        "pick_counts": pick_counts,
    }


def stable_fingerprint_payload(context: dict[str, Any] | None) -> dict[str, Any]:
    """Content-only payload for canonical league matching (no save timestamps)."""
    if not isinstance(context, dict):
        return {}
    return {
        "teams_rosters": _stable_roster_payload(context.get("league_rosters")),
        "fantasy_format": str(context.get("fantasy_format") or "").strip(),
        "scoring_settings": _normalize_settings_block(context.get("scoring_settings")),
        "roster_settings": _normalize_roster_settings(context.get("roster_settings")),
        "draft_structure": _draft_structure_payload(context),
    }


def compute_draft_fingerprint(context: dict[str, Any] | None) -> str:
    payload = stable_fingerprint_payload(context)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def resolve_canonical_league_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    meta = context.get("metadata") or {}
    existing = str(meta.get("league_id") or context.get("league_id") or "").strip()
    if existing:
        return existing
    fp = compute_draft_fingerprint(context)
    return f"{FINGERPRINT_PREFIX}{fp}" if fp else ""


def resolve_draft_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    meta = context.get("metadata") or {}
    return str(meta.get("source_draft_id") or meta.get("draft_id") or context.get("source_draft_id") or "").strip()


def ensure_league_identity(context: dict[str, Any]) -> dict[str, Any]:
    """Attach league_id, draft_id, and draft_fingerprint to context metadata."""
    meta = dict(context.get("metadata") or {})
    existing_fp = str(meta.get("draft_fingerprint") or "").strip()
    existing_league_id = str(meta.get("league_id") or context.get("league_id") or "").strip()
    draft_id = resolve_draft_id(context)
    if draft_id:
        meta["draft_id"] = draft_id
        context["draft_id"] = draft_id
    if existing_league_id and existing_fp:
        meta["league_id"] = existing_league_id
        meta["draft_fingerprint"] = existing_fp
        context["league_id"] = existing_league_id
        context["metadata"] = meta
        return context
    fp = compute_draft_fingerprint(context)
    league_id = f"{FINGERPRINT_PREFIX}{fp}" if fp else ""
    if fp:
        meta["draft_fingerprint"] = fp
    if league_id:
        meta["league_id"] = league_id
        context["league_id"] = league_id
    context["metadata"] = meta
    return context
