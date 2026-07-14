"""Create a shared real_league from a completed Live Draft."""

from __future__ import annotations

from typing import Any

from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    SOURCE_LIVE_DRAFT_ROOM,
    activate_league_context,
    context_id_for_archive,
    create_league_context,
    get_league_context,
    resolve_canonical_save_ids,
    save_draft_archive_with_league_context,
    schedule_league_context_activation,
    upsert_league_context,
)
from live_draft_completion import apply_live_draft_completion, is_live_draft_explicitly_complete
from live_draft_roster_transfer import build_authoritative_live_draft_rosters, get_roster_transfer_diagnostics

CREATED_FROM_LIVE_DRAFT = "live_draft"
SHARED_LEAGUE_CONFIRM_KEY = "_live_draft_shared_league_confirm"


def _room_teams(room: dict[str, Any]) -> list[str]:
    try:
        from live_draft_team_ownership import list_room_teams

        return list_room_teams(room)
    except ImportError:
        teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
        return teams


def validate_live_draft_ready_for_shared_league(room: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not is_live_draft_explicitly_complete(room):
        errors.append("Draft is not complete. Finish every pick before creating a shared league.")
    teams = _room_teams(room)
    if len(teams) < 2:
        errors.append("Shared leagues require at least two teams.")
    _, _, roster_errors = build_authoritative_live_draft_rosters(room, my_team_name=teams[0] if teams else "")
    errors.extend(roster_errors)
    return not errors, errors


def preview_shared_league_creation(
    room: dict[str, Any],
    *,
    my_team_name: str,
    league_name: str = "",
) -> dict[str, Any]:
    """Confirmation payload shown before league creation."""
    my_team = str(my_team_name or "").strip()
    teams = _room_teams(room)
    draft_results, league_rosters, errors = build_authoritative_live_draft_rosters(room, my_team_name=my_team)
    cfg = dict(room.get("config") or {})
    try:
        from live_draft_roster_slots import normalize_draft_slot_config

        cfg = normalize_draft_slot_config(cfg)
    except ImportError:
        pass
    try:
        from fantasy_league_identity import compute_draft_fingerprint, resolve_canonical_league_id
        from fantasy_league_team_ownership import trades_enabled
    except ImportError:
        compute_draft_fingerprint = None  # type: ignore[assignment]
        resolve_canonical_league_id = lambda _c: ""  # type: ignore[assignment, misc]
        trades_enabled = lambda _c, _s: (False, "")  # type: ignore[assignment, misc]

    preview_context = {
        "context_type": CONTEXT_TYPE_REAL_LEAGUE,
        "league_name": str(league_name or cfg.get("league_name") or "Live Draft League").strip(),
        "league_rosters": league_rosters,
        "fantasy_format": str(cfg.get("fantasy_format") or cfg.get("scoring_type") or "").strip(),
        "scoring_settings": {
            "projection_window": cfg.get("projection_window"),
            "projection_style": cfg.get("projection_style"),
            "use_ml_blend": cfg.get("use_ml_blend"),
            "ml_blend_weight": cfg.get("ml_blend_weight"),
            "scoring_type": cfg.get("scoring_type"),
        },
        "roster_settings": {
            "roster_slots": dict(cfg.get("slots") or {}),
            "slot_instances": list(cfg.get("slot_instances") or []),
        },
        "metadata": {"source_draft_id": str(room.get("draft_room_id") or room.get("draft_id") or "").strip()},
    }
    canonical_id = ""
    draft_fp = ""
    if compute_draft_fingerprint is not None:
        draft_fp = str(compute_draft_fingerprint(preview_context) or "").strip()
        canonical_id = str(resolve_canonical_league_id(preview_context) or "").strip()

    roster_counts = {team: len((entry or {}).get("players") or []) for team, entry in league_rosters.items()}
    trade_enabled, trade_message = trades_enabled(preview_context, {})
    owner_rows: list[dict[str, Any]] = []
    try:
        from live_draft_team_ownership import team_claim_rows

        owner_rows = team_claim_rows({}, room)
    except ImportError:
        owner_rows = [{"team": team, "claimed": False, "owner_label": ""} for team in teams]

    return {
        "league_name": preview_context["league_name"],
        "canonical_league_id": canonical_id,
        "draft_id": str(room.get("draft_room_id") or room.get("draft_id") or "").strip(),
        "draft_fingerprint": draft_fp,
        "teams": teams,
        "owner_assignments": owner_rows,
        "roster_count_by_team": roster_counts,
        "final_roster_for_commissioner_team": list((league_rosters.get(my_team) or {}).get("players") or []),
        "final_rosters": league_rosters,
        "roster_slots": dict(cfg.get("slots") or {}),
        "scoring_settings": preview_context["scoring_settings"],
        "trade_eligibility_status": trade_message or ("enabled" if trade_enabled else "disabled"),
        "draft_results": draft_results,
        "roster_transfer_diagnostics": get_roster_transfer_diagnostics(room),
        "validation_errors": errors,
        "ready": not errors and is_live_draft_explicitly_complete(room),
    }


def _resolve_room_code_for_owners(session: dict[str, Any], room: dict[str, Any]) -> str:
    for candidate in (
        session.get("active_shared_draft_room_code"),
        (room.get("sync") or {}).get("room_code") if isinstance(room.get("sync"), dict) else "",
        room.get("room_code"),
        room.get("draft_room_id"),
    ):
        code = str(candidate or "").strip().upper()
        if code:
            return code
    return ""


def _participant_owner_fields(meta: dict[str, Any], *, participant_id: str = "") -> dict[str, str]:
    pid = str(participant_id or "").strip()
    email = str(meta.get("email") or "").strip().lower()
    display = str(meta.get("display_name") or "").strip()
    if not email and "@" in display:
        email = display.lower()
    external = str(meta.get("external_id") or "").strip().lower()
    if not external and email and "@" in email:
        external = email.split("@", 1)[0].strip().lower()
    user_id = str(
        meta.get("account_user_id") or meta.get("user_id") or ""
    ).strip()
    # Prefer suite/local identity keys over bare Auth participant ids when present.
    if not user_id and external:
        user_id = f"user:{external}"
    if not user_id:
        user_id = pid
    return {
        "user_id": user_id,
        "external_id": external,
        "email": email,
        "display_name": display or email or external or pid,
    }


def _resolve_preassigned_owners(
    session: dict[str, Any],
    room: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Map in-room participant claims to account ownership when available."""
    owners: dict[str, dict[str, str]] = {}
    try:
        from live_draft_team_ownership import load_shared_participants, team_claim_rows

        room_code = _resolve_room_code_for_owners(session, room)
        document = None
        if room_code:
            try:
                from draft_room_shared_state import load_shared_room

                document = load_shared_room(room_code)
            except ImportError:
                document = None
        rows = team_claim_rows(session, room, document=document if isinstance(document, dict) else None)
        participants = {}
        if isinstance(document, dict):
            raw = document.get("participants") or {}
            if isinstance(raw, dict):
                participants = {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
        if not participants:
            participants = load_shared_participants(session, room_code=room_code or None)
        for row in rows:
            if not row.get("claimed"):
                continue
            team = str(row.get("team") or "").strip()
            pid = str(row.get("participant_id") or "").strip()
            if not team or not pid:
                continue
            meta = participants.get(pid) or {}
            fields = _participant_owner_fields(meta if isinstance(meta, dict) else {}, participant_id=pid)
            if not fields.get("display_name"):
                fields["display_name"] = str(row.get("owner_label") or "").strip()
            owners[team] = fields
    except ImportError:
        pass
    return owners


def save_live_draft_shared_league_context(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    my_team_name: str,
    league_name: str = "",
    draft_name: str = "",
    defer_activation: bool = False,
    assign_team: bool = True,
    preassign_owners: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Promote a completed live draft to a shared real_league."""
    from draft_archive_state import save_live_draft_team_archive

    room = apply_live_draft_completion(dict(room), session)
    ready, errors = validate_live_draft_ready_for_shared_league(room)
    if not ready:
        raise ValueError("; ".join(errors))

    my_team = str(my_team_name or "").strip()
    if not my_team:
        raise ValueError("my_team_name is required to create a shared league.")
    teams = _room_teams(room)
    if my_team not in teams:
        raise ValueError(f"Team {my_team!r} is not part of this draft.")

    draft_results, league_rosters, roster_errors = build_authoritative_live_draft_rosters(room, my_team_name=my_team)
    if roster_errors:
        raise ValueError("; ".join(roster_errors))

    cfg = dict(room.get("config") or {})
    try:
        from live_draft_roster_slots import normalize_draft_slot_config

        cfg = normalize_draft_slot_config(cfg)
    except ImportError:
        pass

    label = str(draft_name or league_name or "").strip() or f"{cfg.get('league_name', 'Live Draft')} — Shared"
    league_label = str(league_name or cfg.get("league_name") or label).strip() or label
    draft_id, league_context_id, _fp = resolve_canonical_save_ids(
        session,
        league_rosters=league_rosters,
        config=cfg,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
    )

    entry = save_live_draft_team_archive(
        session,
        room,
        team_name=my_team,
        draft_name=label,
        league_rosters=league_rosters,
        draft_id=draft_id,
    )
    draft_id = str(entry.get("draft_id") or "")
    league_context_id = str(
        entry.get("league_context_id") or league_context_id or context_id_for_archive(draft_id)
    ).strip()
    entry = save_draft_archive_with_league_context(
        session,
        draft_id=draft_id,
        league_rosters=league_rosters,
        league_context_id=league_context_id,
    )

    context = create_league_context(
        league_context_id=league_context_id,
        context_type=CONTEXT_TYPE_REAL_LEAGUE,
        league_name=league_label,
        my_team_name=my_team,
        league_rosters=league_rosters,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or "").strip(),
        scoring_settings={
            "projection_window": cfg.get("projection_window"),
            "projection_style": cfg.get("projection_style"),
            "use_ml_blend": cfg.get("use_ml_blend"),
            "ml_blend_weight": cfg.get("ml_blend_weight"),
            "scoring_type": cfg.get("scoring_type"),
        },
        roster_settings={
            "roster_slots": dict(cfg.get("slots") or {}),
            "slot_instances": list(cfg.get("slot_instances") or []),
        },
        display_name=label,
        source=SOURCE_LIVE_DRAFT_ROOM,
        source_draft_id=draft_id,
    )
    meta = dict(context.get("metadata") or {})
    meta["created_from"] = CREATED_FROM_LIVE_DRAFT
    meta["source_draft_type"] = "live_draft_room"
    meta["source"] = SOURCE_LIVE_DRAFT_ROOM
    meta["draft_results"] = draft_results
    meta["teams"] = teams
    room_code = _resolve_room_code_for_owners(session, room)
    if room_code:
        meta["source_room_code"] = room_code
    try:
        from fantasy_league_context import CREATION_ORIGIN_LIVE_DRAFT_ROOM, stamp_immutable_creation_origin

        meta = stamp_immutable_creation_origin(meta, CREATION_ORIGIN_LIVE_DRAFT_ROOM)
    except ImportError:
        CREATION_ORIGIN_LIVE_DRAFT_ROOM = "live_draft_room"  # type: ignore[misc,assignment]
        stamp_immutable_creation_origin = None  # type: ignore[assignment,misc]
    try:
        from fantasy_league_identity import ensure_league_identity

        context = ensure_league_identity(context)
        meta = dict(context.get("metadata") or meta)
    except ImportError:
        pass
    if callable(stamp_immutable_creation_origin):
        meta = stamp_immutable_creation_origin(meta, CREATION_ORIGIN_LIVE_DRAFT_ROOM)
    context["metadata"] = meta
    context["source"] = SOURCE_LIVE_DRAFT_ROOM
    context["draft_results"] = draft_results
    context = upsert_league_context(session, context)

    owner_map = dict(preassign_owners or {})
    owner_map.update(_resolve_preassigned_owners(session, room))
    if assign_team:
        try:
            from fantasy_league_team_ownership import assign_my_team, assign_team_owner_to_context

            if my_team not in owner_map:
                context, err = assign_my_team(session, my_team)
                if err:
                    raise ValueError(err)
            else:
                me = owner_map[my_team]
                context = assign_team_owner_to_context(
                    context,
                    my_team,
                    user_id=str(me.get("user_id") or "").strip() or None,
                    email=str(me.get("email") or "").strip() or None,
                    display_name=str(me.get("display_name") or "").strip() or None,
                )
                context["my_team_name"] = my_team
                context = upsert_league_context(session, context)
            meta = dict(context.get("metadata") or {})
            commissioner = str(meta.get("commissioner_user_id") or owner_map.get(my_team, {}).get("user_id") or "").strip()
            if not commissioner:
                try:
                    from fantasy_league_team_ownership import _resolve_user_id

                    commissioner = str(_resolve_user_id() or "").strip()
                except ImportError:
                    commissioner = str(owner_map.get(my_team, {}).get("user_id") or "").strip()
            if commissioner:
                meta["commissioner_user_id"] = commissioner
                context["metadata"] = meta
                context = upsert_league_context(session, context)
            for team, owner in owner_map.items():
                if team == my_team:
                    continue
                context = assign_team_owner_to_context(
                    context,
                    team,
                    user_id=str(owner.get("user_id") or "").strip() or None,
                    email=str(owner.get("email") or "").strip() or None,
                    display_name=str(owner.get("display_name") or "").strip() or None,
                    external_id=str(owner.get("external_id") or "").strip() or None,
                )
            context = upsert_league_context(session, context)
        except ImportError:
            pass

    if defer_activation:
        schedule_league_context_activation(session, league_context_id, archive_id=draft_id)
    else:
        activate_league_context(session, league_context_id)

    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, context)
    except (ImportError, RuntimeError, OSError):
        pass

    context = get_league_context(session, league_context_id) or context
    meta = dict(context.get("metadata") or {})
    meta["created_from"] = CREATED_FROM_LIVE_DRAFT
    meta["source_draft_type"] = "live_draft_room"
    meta["source"] = SOURCE_LIVE_DRAFT_ROOM
    try:
        from fantasy_league_context import CREATION_ORIGIN_LIVE_DRAFT_ROOM, stamp_immutable_creation_origin

        meta = stamp_immutable_creation_origin(meta, CREATION_ORIGIN_LIVE_DRAFT_ROOM)
    except ImportError:
        pass
    meta["draft_results"] = draft_results
    context["metadata"] = meta
    context["source"] = SOURCE_LIVE_DRAFT_ROOM
    context["draft_results"] = draft_results
    context = upsert_league_context(session, context)
    entry = dict(entry)
    entry["shared_league_created"] = True
    entry["canonical_league_id"] = str(context.get("league_id") or (context.get("metadata") or {}).get("league_id") or "")
    entry["context_type"] = CONTEXT_TYPE_REAL_LEAGUE
    try:
        from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_LIVE, get_draft_archive

        entry["draft_type"] = DRAFT_TYPE_LIVE
        origin = str(meta.get("creation_origin") or "").strip()
        if origin:
            entry["creation_origin"] = origin
        archives = list(session.get(DRAFT_ARCHIVE_KEY) or [])
        for idx, existing in enumerate(archives):
            if not isinstance(existing, dict):
                continue
            if str(existing.get("draft_id") or "").strip() != draft_id:
                continue
            updated = dict(existing)
            updated["draft_type"] = DRAFT_TYPE_LIVE
            if origin:
                updated["creation_origin"] = origin
            archives[idx] = updated
            session[DRAFT_ARCHIVE_KEY] = archives
            entry = {**updated, **entry}
            break
        else:
            existing = get_draft_archive(session, draft_id)
            if isinstance(existing, dict):
                entry = {**existing, **entry, "draft_type": DRAFT_TYPE_LIVE}
    except ImportError:
        pass
    return entry, context
