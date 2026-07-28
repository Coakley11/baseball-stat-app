"""Diag-only RV1: create and start a real Solo room in the same Streamlit session.

Canonical room source (production):
- Runtime authority is ``session['live_draft_room']`` plus ``write_canonical_live_draft_state``.
- There is no production path that restores a full in-progress Solo room from ``draft_room_id`` alone
  after a new browser navigation (Supabase/shared loaders are multiplayer-oriented).
- RV1 therefore uses same-session production create+start helpers instead of post-nav hydration.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

ROOM_STATE_SOURCE_KEY = "_solo_rv_room_state_source"
SAME_SESSION_SOURCE = "same_session_production_create"
RV1_SETUP_OWNER_KEY = "_solo_rv_rv1_production_setup_owner"


def _qp_get(st: Any, key: str) -> str:
    try:
        from live_draft_solo_rv_binding_ladder import _qp_get as _g

        return _g(st, key)
    except ImportError:
        return ""


def room_state_fingerprint(room: dict[str, Any]) -> str:
    payload = {
        "draft_room_id": str(room.get("draft_room_id") or ""),
        "status": str(room.get("status") or ""),
        "current_pick_index": int(room.get("current_pick_index") or 0),
        "pick_order_len": len(list(room.get("pick_order") or [])),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _get_setup_owner(session: dict[str, Any]) -> dict[str, Any]:
    owner = session.get(RV1_SETUP_OWNER_KEY)
    return dict(owner) if isinstance(owner, dict) else {}


def _save_setup_owner(session: dict[str, Any], owner: dict[str, Any]) -> None:
    session[RV1_SETUP_OWNER_KEY] = dict(owner)


def _expected_token_for_room(room: dict[str, Any]) -> str:
    try:
        from solo_countdown_component import build_solo_expire_token

        return str(build_solo_expire_token(room) or "").strip()
    except ImportError:
        return ""


def _room_matches_owner(owner: dict[str, Any], live: dict[str, Any]) -> bool:
    if str(live.get("status") or "") != "in_progress":
        return False
    if live.get("timer_deadline") is None:
        return False
    rid = str(live.get("draft_room_id") or "").strip().upper()
    if rid != str(owner.get("room_id") or "").strip().upper():
        return False
    if int(live.get("current_pick_index") or 0) != int(owner.get("initial_pick") or 0):
        return False
    token = _expected_token_for_room(live)
    owner_token = str(owner.get("expected_token") or "")
    if owner_token and token and token != owner_token:
        return False
    return True


def _try_rv1_reuse_owned_room(
    st: Any,
    session: dict[str, Any],
    *,
    run_id: str,
    step: str,
    probe_placeholder: Any,
) -> dict[str, Any] | None:
    from live_draft_solo_rv_control_probe import append_control_event, render_native_control_probe

    owner = _get_setup_owner(session)
    if not owner.get("setup_completed") or str(owner.get("owner_run_id") or "") != run_id:
        return None
    live = session.get("live_draft_room")
    if not isinstance(live, dict):
        return None
    if not _room_matches_owner(owner, live):
        return {
            "ok": False,
            "invalid": "INVALID_RV_DUPLICATE_ROOM_CREATION_fingerprint_or_state_mismatch",
            "reason": "owner_room_mismatch",
        }
    room_id = str(live.get("draft_room_id") or "").strip().upper()
    token = str(owner.get("expected_token") or _expected_token_for_room(live))
    session[ROOM_STATE_SOURCE_KEY] = SAME_SESSION_SOURCE
    append_control_event(
        st,
        session,
        "production_room_reused",
        control_name=step,
        room=live,
        expected_token=token,
        extra={
            "owner_run_id": run_id,
            "room_id": room_id,
            "room_fingerprint": owner.get("room_fingerprint"),
            "creation_event_id": owner.get("creation_event_id"),
            "draft_start_event_id": owner.get("draft_start_event_id"),
            "room_object_id": owner.get("room_object_id"),
            "logical_reuse": True,
        },
    )
    if probe_placeholder is not None:
        render_native_control_probe(st, session, probe_placeholder)
    return {
        "ok": True,
        "room_id": room_id,
        "room": live,
        "room_state_source": SAME_SESSION_SOURCE,
        "reused": True,
    }


def apply_rv1_setup_query_params(st: Any, session: dict[str, Any]) -> None:
    """Optional runner setup inputs only — never a prebuilt room or token."""
    session["active_page"] = "Live Draft Room"
    for qp, ss_key, cast in (
        ("solo_rv_team_count", "live_draft_team_count", int),
        ("solo_rv_picks_per_team", "live_draft_picks_per_team", int),
        ("solo_rv_timer_seconds", "_solo_rv_timer_seconds_override", int),
        ("solo_rv_auto_rule", "live_draft_auto_rule", str),
        ("solo_rv_league_name", "live_draft_league_name", str),
    ):
        raw = _qp_get(st, qp).strip()
        if not raw:
            continue
        try:
            session[ss_key] = cast(raw)
        except (TypeError, ValueError):
            pass
    names_raw = _qp_get(st, "solo_rv_team_names").strip()
    if names_raw:
        parts = [p.strip() for p in names_raw.split("|") if p.strip()]
        for i, name in enumerate(parts):
            session[f"live_draft_team_name_{i}"] = name


def _session_setup_fields(session: dict[str, Any]) -> dict[str, Any]:
    from streamlit_app import LIVE_DRAFT_AUTO_RULES, LIVE_DRAFT_TIMER_CHOICES, _live_draft_default_teams

    live_scoring = str(session.get("live_draft_scoring") or "Roto (5x5)")
    live_timer_label = str(
        session.get("live_draft_timer")
        or (list(LIVE_DRAFT_TIMER_CHOICES.keys())[1] if len(LIVE_DRAFT_TIMER_CHOICES) > 1 else list(LIVE_DRAFT_TIMER_CHOICES.keys())[0])
    )
    live_auto_rule = str(session.get("live_draft_auto_rule") or LIVE_DRAFT_AUTO_RULES[4])
    live_proj_style = str(session.get("live_draft_proj_style") or "Balanced")
    try:
        from user_page_preferences import live_draft_setup_number_default

        live_proj_window = int(live_draft_setup_number_default(session, "live_draft_proj_window", 3))
        live_num_teams = int(live_draft_setup_number_default(session, "live_draft_team_count", 2))
        live_picks_per_team = int(live_draft_setup_number_default(session, "live_draft_picks_per_team", 4))
    except ImportError:

        def _num(key: str, default: int) -> int:
            raw = session.get(key)
            if raw is None or str(raw).strip() == "":
                return int(default)
            try:
                return int(raw)
            except (TypeError, ValueError):
                return int(default)

        live_proj_window = _num("live_draft_proj_window", 3)
        live_num_teams = _num("live_draft_team_count", 2)
        live_picks_per_team = _num("live_draft_picks_per_team", 4)

    live_league_name = str(session.get("live_draft_league_name") or "My Fantasy League")
    default_teams = _live_draft_default_teams(live_num_teams)
    team_names = [
        str(session.get(f"live_draft_team_name_{i}") or default_teams[i]).strip() or default_teams[i]
        for i in range(int(live_num_teams))
    ]
    try:
        from live_draft_roster_slots import session_slot_count
    except ImportError:

        def session_slot_count(session: dict[str, Any], widget_key: str, default: int = 0) -> int:
            if widget_key not in session:
                return int(default)
            try:
                return int(session[widget_key])
            except (TypeError, ValueError):
                return int(default)

    slot_c = session_slot_count(session, "live_slot_c", 1)
    slot_1b = session_slot_count(session, "live_slot_1b", 1)
    slot_2b = session_slot_count(session, "live_slot_2b", 1)
    slot_3b = session_slot_count(session, "live_slot_3b", 1)
    slot_ss = session_slot_count(session, "live_slot_ss", 1)
    slot_of = session_slot_count(session, "live_slot_of", 3)
    slot_dh = session_slot_count(session, "live_slot_dh", 1)
    slot_p = session_slot_count(session, "live_slot_p", 0)
    slot_bench = session_slot_count(session, "live_slot_bench", 5)
    fantasy_format = "5x5 Roto" if "Roto" in live_scoring else "Points League"
    setup_slots = {
        "C": slot_c,
        "1B": slot_1b,
        "2B": slot_2b,
        "3B": slot_3b,
        "SS": slot_ss,
        "OF": slot_of,
        "DH": slot_dh,
        "P": slot_p,
        "BN": slot_bench,
    }
    timer_seconds = int(LIVE_DRAFT_TIMER_CHOICES.get(live_timer_label, 60))
    override = session.get("_solo_rv_timer_seconds_override")
    if override is not None:
        try:
            timer_seconds = int(override)
        except (TypeError, ValueError):
            pass
    try:
        from live_draft_solo_component_diagnostics import solo_diag_timer_seconds

        diag_timer = solo_diag_timer_seconds(session, None)
        if diag_timer is not None:
            timer_seconds = int(diag_timer)
    except ImportError:
        pass
    user_team = str(team_names[0]).strip() or default_teams[0]
    your_team = str(session.get("room_your_team") or "").strip()
    if your_team and your_team in team_names:
        user_team = your_team
    return {
        "live_scoring": live_scoring,
        "live_num_teams": int(live_num_teams),
        "live_picks_per_team": int(live_picks_per_team),
        "live_proj_window": int(live_proj_window),
        "live_proj_style": live_proj_style,
        "live_auto_rule": live_auto_rule,
        "live_league_name": live_league_name,
        "team_names": team_names,
        "default_teams": default_teams,
        "setup_slots": setup_slots,
        "fantasy_format": fantasy_format,
        "timer_seconds": timer_seconds,
        "user_team": user_team,
    }


def ensure_rv1_production_solo_room(
    st: Any,
    session: dict[str, Any],
    *,
    probe_placeholder: Any = None,
) -> dict[str, Any]:
    """Production Solo create+start in the current Streamlit session (RV1 diag only)."""
    from live_draft_solo_rv_control_probe import append_control_event, render_native_control_probe

    apply_rv1_setup_query_params(st, session)
    try:
        from live_draft_solo_component_diagnostics import bootstrap_solo_component_diag

        bootstrap_solo_component_diag(st, session)
    except ImportError:
        pass
    step = str(session.get("_solo_rv_ladder_step") or "RV1")
    run_id = str(session.get("_solo_rv_run_id") or _qp_get(st, "solo_rv_run_id") or "").strip()

    if step == "RV2" and session.get("_solo_rv_rv2_production_setup_done"):
        reused = _try_rv1_reuse_owned_room(
            st, session, run_id=run_id, step=step, probe_placeholder=probe_placeholder
        )
        if reused is not None:
            return reused
        return {
            "ok": False,
            "invalid": "INVALID_RV_REAL_ROOM_HYDRATION_room_not_in_session",
            "reason": "rv2_setup_owner_without_live_room",
        }
    if step == "RV3" and session.get("_solo_rv_rv3_production_setup_done"):
        reused = _try_rv1_reuse_owned_room(
            st, session, run_id=run_id, step=step, probe_placeholder=probe_placeholder
        )
        if reused is not None:
            return reused
        return {
            "ok": False,
            "invalid": "INVALID_RV_ROOM_REUSE_FAILED_live_room_missing",
            "reason": "rv3_setup_owner_without_live_room",
        }

    reused = _try_rv1_reuse_owned_room(
        st, session, run_id=run_id, step=step, probe_placeholder=probe_placeholder
    )
    if reused is not None:
        return reused

    creation_event_id = f"rv1-create-{uuid.uuid4().hex[:12]}"
    append_control_event(
        st,
        session,
        "production_room_creation_attempted",
        control_name=step,
        extra={"creation_event_id": creation_event_id, "owner_run_id": run_id},
    )
    if probe_placeholder is not None:
        render_native_control_probe(st, session, probe_placeholder)

    try:
        from live_draft_start_progress import begin_live_draft_start, clear_post_delete_create_blocks

        clear_post_delete_create_blocks(session)
        begin_live_draft_start(session, mode="new")
    except ImportError:
        pass

    fields = _session_setup_fields(session)
    live_num_teams = fields["live_num_teams"]
    live_picks_per_team = fields["live_picks_per_team"]
    setup_slots = fields["setup_slots"]
    total_picks = int(live_num_teams) * int(live_picks_per_team)

    try:
        from live_draft_start_setup import fail_closed_setup_check

        setup_check = fail_closed_setup_check(
            session,
            picks_per_team=int(live_picks_per_team),
            slots=dict(setup_slots),
            solo_mode=True,
        )
    except ImportError:
        setup_check = {"ok": False, "error": "setup_helpers_unavailable"}

    if not setup_check.get("ok"):
        reason = str(setup_check.get("error") or "setup_validation_failed").replace(" ", "_")[:80]
        append_control_event(
            st,
            session,
            "production_room_creation_failed",
            control_name=step,
            extra={"reason": reason},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}", "reason": reason}

    setup_slots = dict(setup_check.get("slots_for_room") or setup_slots)

    try:
        from streamlit_app import load_fantasypros_market_data, live_draft_init_room, live_draft_start
        from live_draft_fast_solo_start import build_fast_market_pool, note_start_stage
    except ImportError as exc:
        reason = f"import_{type(exc).__name__}"
        append_control_event(
            st,
            session,
            "production_room_creation_failed",
            control_name=step,
            extra={"reason": reason},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}", "reason": reason}

    try:
        market_df = load_fantasypros_market_data()
        pool_live = build_fast_market_pool(market_df, min_rows=max(400, int(total_picks) * 40))
    except Exception as exc:
        reason = f"pool_build_{type(exc).__name__}"
        append_control_event(
            st,
            session,
            "production_room_creation_failed",
            control_name=step,
            extra={"reason": reason},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}", "reason": reason}

    if pool_live is None or getattr(pool_live, "empty", True):
        reason = "empty_pool"
        append_control_event(
            st,
            session,
            "production_room_creation_failed",
            control_name=step,
            extra={"reason": reason},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}", "reason": reason}
    if total_picks > len(pool_live):
        reason = "pool_too_small"
        append_control_event(
            st,
            session,
            "production_room_creation_failed",
            control_name=step,
            extra={"reason": reason, "pool_count": len(pool_live), "total_picks": total_picks},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}", "reason": reason}

    try:
        note_start_stage(session, "pool_build_end", pool_live_count=int(len(pool_live)), fast_pool=True)
    except Exception:
        pass

    config = {
        "league_name": str(fields["live_league_name"]).strip() or "My Fantasy League",
        "num_teams": int(live_num_teams),
        "picks_per_team": int(live_picks_per_team),
        "draft_type": "snake",
        "scoring_type": fields["live_scoring"],
        "fantasy_format": fields["fantasy_format"],
        "timer_seconds": int(fields["timer_seconds"]),
        "auto_pick_rule": fields["live_auto_rule"],
        "projection_style": fields["live_proj_style"],
        "projection_window": int(fields["live_proj_window"]),
        "use_ml_blend": bool(session.get("draft_use_ml_blend", False)),
        "ml_blend_weight": float(session.get("draft_ml_blend_weight", 0.12) or 0),
        "teams": [
            str(t).strip() or fields["default_teams"][i] for i, t in enumerate(fields["team_names"])
        ],
        "user_team": fields["user_team"],
        "your_team": fields["user_team"],
        "slots": dict(setup_slots),
    }
    try:
        from live_draft_roster_slots import freeze_slot_instances_on_config

        config = freeze_slot_instances_on_config(config)
    except ImportError:
        pass

    try:
        new_room = live_draft_init_room(config, pool_live)
    except Exception as exc:
        reason = f"init_room_{type(exc).__name__}"
        append_control_event(
            st,
            session,
            "production_room_creation_failed",
            control_name=step,
            extra={"reason": reason},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}", "reason": reason}

    room_id = str(new_room.get("draft_room_id") or "").strip().upper()
    fingerprint = room_state_fingerprint(new_room)
    append_control_event(
        st,
        session,
        "production_room_created",
        control_name=step,
        room=new_room,
        extra={
            "room_id": room_id,
            "room_state_source": SAME_SESSION_SOURCE,
            "creation_event_id": creation_event_id,
            "owner_run_id": run_id,
            "room_fingerprint": fingerprint,
            "room_object_id": id(new_room),
        },
    )
    if probe_placeholder is not None:
        render_native_control_probe(st, session, probe_placeholder)

    try:
        from live_draft_termination import reset_context_for_new_live_draft
        from live_draft_setup_mode import SETUP_MODE_SOLO, stamp_room_setup_mode

        reset_context_for_new_live_draft(session)
        stamp_room_setup_mode(new_room, session)
    except ImportError:
        pass

    try:
        from live_draft_setup_mode import SETUP_MODE_SOLO, request_live_draft_setup_mode

        request_live_draft_setup_mode(session, SETUP_MODE_SOLO, persist=False, st=None)
    except ImportError:
        pass

    draft_start_event_id = f"rv1-start-{uuid.uuid4().hex[:12]}"
    append_control_event(
        st,
        session,
        "production_draft_start_attempted",
        control_name=step,
        room=new_room,
        extra={
            "draft_start_event_id": draft_start_event_id,
            "creation_event_id": creation_event_id,
            "owner_run_id": run_id,
        },
    )

    try:
        live_draft_start(new_room)
    except Exception as exc:
        reason = f"start_{type(exc).__name__}"
        append_control_event(
            st,
            session,
            "production_draft_start_failed",
            control_name=step,
            room=new_room,
            extra={"reason": reason, "room_id": room_id},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_DRAFT_START_{reason}", "reason": reason}

    if str(new_room.get("status") or "") != "in_progress" or new_room.get("timer_deadline") is None:
        reason = "timer_not_armed"
        append_control_event(
            st,
            session,
            "production_draft_start_failed",
            control_name=step,
            room=new_room,
            extra={"reason": reason, "room_id": room_id, "status": new_room.get("status")},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "invalid": f"INVALID_RV_PRODUCTION_DRAFT_START_{reason}", "reason": reason}

    session["live_draft_room"] = new_room
    session["room_your_team"] = fields["user_team"]
    session[ROOM_STATE_SOURCE_KEY] = SAME_SESSION_SOURCE
    session["_solo_rv_production_room_id"] = room_id
    token = _expected_token_for_room(new_room)
    owner = {
        "setup_completed": True,
        "owner_run_id": run_id,
        "room_id": room_id,
        "room_fingerprint": fingerprint,
        "creation_event_id": creation_event_id,
        "draft_start_event_id": draft_start_event_id,
        "room_object_id": id(new_room),
        "created_ts": time.time(),
        "initial_pick": int(new_room.get("current_pick_index") or 0),
        "initial_deadline": new_room.get("timer_deadline"),
        "expected_token": token,
    }
    _save_setup_owner(session, owner)

    append_control_event(
        st,
        session,
        "production_draft_started",
        control_name=step,
        room=new_room,
        expected_token=token,
        extra={
            "room_id": room_id,
            "room_state_source": SAME_SESSION_SOURCE,
            "creation_event_id": creation_event_id,
            "draft_start_event_id": draft_start_event_id,
            "owner_run_id": run_id,
            "room_fingerprint": fingerprint,
            "room_object_id": id(new_room),
        },
    )
    append_control_event(
        st,
        session,
        "production_setup_owner_established",
        control_name=step,
        room=new_room,
        expected_token=token,
        extra=dict(owner),
    )

    try:
        from live_draft_canonical_snapshot import begin_live_draft_paint

        begin_live_draft_paint(session, new_room, state_source="solo_start")
    except ImportError:
        pass
    try:
        from live_draft_state import write_canonical_live_draft_state

        write_canonical_live_draft_state(session, new_room, reason="start_draft", local_edit=True)
    except Exception:
        pass
    try:
        from live_draft_creation_trace import protect_new_room

        protect_new_room(session)
    except ImportError:
        pass

    if probe_placeholder is not None:
        render_native_control_probe(st, session, probe_placeholder)
    return {"ok": True, "room_id": room_id, "room": new_room, "room_state_source": SAME_SESSION_SOURCE}
