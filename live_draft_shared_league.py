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
    try:
        # The id the league will actually get (shared_draft_identity), not the content fingerprint.
        import streamlit as _st

        from shared_draft_identity import league_for_room, shared_room_code

        _session = _st.session_state
        _code = shared_room_code(_session, room)
        if _code:
            canonical_id = league_for_room(_session, _code)
    except Exception:
        pass

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


ROOM_HOST_MESSAGES = {
    "not_room_host": (
        "Only this room's host can create its Shared League. You keep your team: once the host "
        "creates the league, accept their invite to manage it. Nothing was changed."
    ),
    "room_host_unknown": (
        "This room has no recorded host, so a Shared League cannot be created from it yet. "
        "Nothing was changed. The app owner can review the room and assign its host."
    ),
    "room_unverifiable": "The room could not be checked right now. Nothing was changed; please try again.",
    "room_missing": "This room could not be found, so a Shared League cannot be created from it. Nothing was changed.",
}


def room_host_creation_error(session: dict[str, Any], room_code: str) -> str:
    """'' when this signed-in account is the stored host of ``room_code`` (or outside a user
    request: scripts and tests); otherwise the message to show."""
    try:
        from fantasy_shared_league_authz import (
            current_session,
            room_league_creation_error,
            shared_league_sign_in_error,
        )
    except ImportError:
        return ""
    if current_session() is None:
        return ""
    message = shared_league_sign_in_error(session)
    if message:
        return message
    reason = room_league_creation_error(session, room_code)
    return ROOM_HOST_MESSAGES.get(reason, ROOM_HOST_MESSAGES["not_room_host"]) if reason else ""


def _creating_host_account_id(session: dict[str, Any]) -> str:
    """The verified account creating the league (suite account id when known), or ''."""
    try:
        from fantasy_shared_league_authz import current_session, verified_account_ids
    except ImportError:
        return ""
    if current_session() is None:
        return ""
    ids = verified_account_ids(session)
    return ids[-1] if ids else ""


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
    keep_current_active: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Promote a completed live draft to a shared real_league.

    ``keep_current_active``: when the account already has an active league or draft, the new
    league is not made active (Set active league does that explicitly); with none, it is."""
    from draft_archive_state import save_live_draft_team_archive

    prior_active = (
        str(((session.get("fantasy_league_context_state") or {}).get("active_league_context_id")) or "").strip(),
        str(session.get("active_draft_archive_id") or "").strip(),
    )

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
    try:
        from shared_draft_identity import room_save_ids, shared_room_code

        shared_code = shared_room_code(session, room)
    except ImportError:
        shared_code = ""
    if shared_code:
        # Only the stored room host may create this room's Shared League, and becomes its
        # commissioner (owner decision 2026-11-05). Checked before anything is saved.
        host_error = room_host_creation_error(session, shared_code)
        if host_error:
            raise ValueError(host_error)
    if shared_code:
        # This room's own entry (or a new room-<code> entry), never another room's entry with the
        # same picks: that overwrote a different saved draft (QA 2026-11-05).
        draft_id, league_context_id = room_save_ids(session, shared_code)
    else:
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
        fixed_draft_id=bool(shared_code),
    )
    draft_id = str(entry.get("draft_id") or "")
    if shared_code:
        from shared_draft_identity import stamp_room

        stamp_room(session, draft_id, shared_code)
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
    # Stamped before the shared write (not only after it): the shared league's origin is read from
    # these, and without a room code it was published as an imported league, so invitees' copies
    # showed as Imported League instead of Live Draft.
    meta["created_from"] = CREATED_FROM_LIVE_DRAFT
    meta["source_draft_type"] = "live_draft_room"
    meta["source"] = SOURCE_LIVE_DRAFT_ROOM
    try:
        from fantasy_league_context import CREATION_ORIGIN_LIVE_DRAFT_ROOM, stamp_immutable_creation_origin

        meta = stamp_immutable_creation_origin(meta, CREATION_ORIGIN_LIVE_DRAFT_ROOM)
    except ImportError:
        CREATION_ORIGIN_LIVE_DRAFT_ROOM = "live_draft_room"  # type: ignore[misc,assignment]
        stamp_immutable_creation_origin = None  # type: ignore[assignment,misc]
    # Hand these to the context before the identity step: it used to rebuild metadata from the
    # context alone, dropping created_from and source_room_code before the first shared write.
    context["metadata"] = dict(meta)
    if shared_code:
        # A league made from a Shared Draft room is identified by the room: league:room-<code>, or
        # the id this room's league already has. Never the roster fingerprint, which two rooms can share.
        from fantasy_league_identity import compute_draft_fingerprint
        from shared_draft_identity import league_for_room

        room_league = league_for_room(session, shared_code)
        context["metadata"]["league_id"] = room_league
        context["metadata"]["draft_fingerprint"] = compute_draft_fingerprint(context)
        context["metadata"]["source_room_code"] = shared_code
        context["league_id"] = room_league
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
            if shared_code:
                creator = _creating_host_account_id(session)
                if creator:
                    commissioner = creator  # the verified host, never a value from a local copy
            if commissioner:
                meta["commissioner_user_id"] = commissioner
                context["metadata"] = meta
                context = upsert_league_context(session, context)
            # Non-commissioner Live Draft seats stay reserved/unclaimed until invite Accept.
            from fantasy_league_team_ownership import reserve_team_for_invite_claim

            for team, owner in owner_map.items():
                if team == my_team:
                    continue
                context = reserve_team_for_invite_claim(
                    context,
                    team,
                    user_id=str(owner.get("user_id") or "").strip(),
                    email=str(owner.get("email") or "").strip(),
                    display_name=str(owner.get("display_name") or "").strip(),
                    external_id=str(owner.get("external_id") or "").strip(),
                )
            context = upsert_league_context(session, context)
        except ImportError:
            pass

    activation_skipped = bool(keep_current_active and any(prior_active))
    if activation_skipped:
        # Saving the draft above may have pointed the active draft at it; put the account's own
        # choice back. Nothing else about the active league changes.
        store = session.get("fantasy_league_context_state")
        if isinstance(store, dict):
            store["active_league_context_id"] = prior_active[0]
        if prior_active[1]:
            session["active_draft_archive_id"] = prior_active[1]
    elif defer_activation:
        schedule_league_context_activation(session, league_context_id, archive_id=draft_id)
    else:
        activate_league_context(session, league_context_id)

    # Whether the league reached the shared store (where invitees find it) is reported, not
    # assumed: a refused or failed write leaves shared_league_created False, so the page says the
    # league is on this device only instead of showing success.
    shared_push_error = ""
    pushed = None
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        pushed = push_league_context_to_shared(session, context)
        if not isinstance(pushed, dict):
            shared_push_error = "the shared league store returned nothing"
    except (ImportError, RuntimeError, OSError, ValueError) as exc:
        shared_push_error = f"{type(exc).__name__}: {exc}"

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
    entry["shared_league_created"] = isinstance(pushed, dict) and not shared_push_error
    entry["activation_skipped"] = activation_skipped
    if shared_push_error:
        entry["shared_league_push_error"] = shared_push_error
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
    try:
        from baseball_fantasy_activity import log_shared_league_created

        log_shared_league_created(
            context,
            draft_id=str(entry.get("draft_id") or context.get("source_draft_id") or ""),
        )
    except Exception:
        pass
    return entry, context
