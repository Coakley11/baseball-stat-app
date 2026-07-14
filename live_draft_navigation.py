"""Leave / return draft navigation for Live Draft Room and Draft Simulator."""

from __future__ import annotations

from typing import Any

BROWSING_AWAY_KEY = "_live_draft_browsing_away"
FORCE_SYNC_ON_RETURN_KEY = "_live_draft_force_sync_on_return"
MAIN_SIDEBAR_PAGE_KEY = "main_sidebar_page"
DEFAULT_BROWSE_PAGE = "Fantasy Trends"

LIVE_DRAFT_QUICK_NAV_PAGES: tuple[tuple[str, str, str, str], ...] = (
    ("Draft Assistant Simulator", "Draft Assistant", "Next-pick ranks", "assistant"),
    ("Fantasy Sleepers & Busts", "Sleepers", "Market edge", "sleepers"),
)

LIVE_DRAFT_QUICK_NAV_QUEUE_ACTION = ("__live_draft_queue__", "Queue", "Your queue", "queue")


def _page_label(page_key: str, page_label_fn=None) -> str:
    if callable(page_label_fn):
        return str(page_label_fn(page_key))
    return page_key


def _page_icon(page_key: str, page_label_fn=None) -> str:
    label = _page_label(page_key, page_label_fn)
    first = label.split(" ", 1)[0].strip()
    return first if first and first != page_key else ""


def _with_page_icon(page_key: str, text: str, page_label_fn=None) -> str:
    icon = _page_icon(page_key, page_label_fn)
    return f"{icon} {text}".strip()


def inject_live_draft_quick_nav_styles(st: Any) -> None:
    st.markdown(
        """
        <style>
        .ld-quick-nav-wrap { margin: 0 0 6px 0; }
        .ld-quick-nav-title {
            font-size: 11px; font-weight: 700; color: #64748b;
            letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 6px;
        }
        .ld-quick-tile {
            border-radius: 10px; padding: 6px 10px;
            min-height: 40px; border: 1px solid transparent;
            margin-bottom: 2px;
        }
        .ld-quick-tile-assistant { background: linear-gradient(135deg,#eff6ff,#dbeafe); border-color:#93c5fd; }
        .ld-quick-tile-sleepers { background: linear-gradient(135deg,#fff7ed,#ffedd5); border-color:#fdba74; }
        .ld-quick-tile-queue { background: linear-gradient(135deg,#f0fdf4,#dcfce7); border-color:#86efac; }
        .ld-quick-tile-label { font-size: 12px; font-weight: 800; color: #0f172a; line-height: 1.2; }
        .ld-quick-tile-sub { font-size: 10px; color: #64748b; margin-top: 2px; line-height: 1.2; }
        div[data-testid="column"] .ld-quick-tile + div[data-testid="stButton"] button {
            min-height: 28px; padding: 2px 8px; font-size: 11px; font-weight: 700;
            border-radius: 8px; margin-top: 2px;
        }
        @media (max-width: 768px) {
            .ld-quick-tile-sub { display: none; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _go_body(session: dict[str, Any], target_page: str, prepare_canonical_scoring_context) -> None:
    if prepare_canonical_scoring_context is not None:
        try:
            prepare_canonical_scoring_context(session, active_page=target_page)
        except Exception:
            pass
    session[BROWSING_AWAY_KEY] = True
    _apply_scheduled_page(session, target_page)


def render_live_draft_quick_nav(st: Any, session: dict[str, Any], *, page_label_fn=None) -> None:
    """Compact navigation: Draft Assistant, Sleepers, and in-page Queue focus."""
    try:
        from shared_draft_context import prepare_canonical_scoring_context
    except ImportError:
        prepare_canonical_scoring_context = None  # type: ignore[misc,assignment]

    def _go(target_page: str) -> None:
        try:
            from live_draft_perf import PHASE_SECTION_NAV, live_draft_perf_action

            with live_draft_perf_action(session, f"nav:{target_page}", phase=PHASE_SECTION_NAV):
                _go_body(session, target_page, prepare_canonical_scoring_context)
        except ImportError:
            _go_body(session, target_page, prepare_canonical_scoring_context)

    def _focus_queue() -> None:
        session["_live_draft_focus_queue"] = True

    inject_live_draft_quick_nav_styles(st)
    st.markdown(
        '<div class="ld-quick-nav-wrap"><div class="ld-quick-nav-title">Quick navigation</div></div>',
        unsafe_allow_html=True,
    )
    tiles = list(LIVE_DRAFT_QUICK_NAV_PAGES) + [LIVE_DRAFT_QUICK_NAV_QUEUE_ACTION]
    cols = st.columns(len(tiles))
    for col, (page, label, subtitle, theme) in zip(cols, tiles):
        with col:
            col.markdown(
                f'<div class="ld-quick-tile ld-quick-tile-{theme}">'
                f'<div class="ld-quick-tile-label">{_with_page_icon(page, label, page_label_fn) if not page.startswith("__") else label}</div>'
                f'<div class="ld-quick-tile-sub">{subtitle}</div></div>',
                unsafe_allow_html=True,
            )
            if page.startswith("__"):
                col.button(
                    "Jump →",
                    key="live_draft_quick_nav_queue",
                    use_container_width=True,
                    on_click=_focus_queue,
                )
            else:
                col.button(
                    "Open →",
                    key=f"live_draft_quick_nav_{page.replace(' ', '_')}",
                    use_container_width=True,
                    on_click=_go,
                    args=(page,),
                )


def _apply_scheduled_page(session: dict[str, Any], target_page: str) -> None:
    """Navigate immediately — sidebar radio reads these keys on the same rerun."""
    page = str(target_page or "").strip()
    if not page:
        return
    session["_navigate_to_page"] = page
    session[MAIN_SIDEBAR_PAGE_KEY] = page
    session["active_page"] = page
    session["_suite_page_user_nav"] = True
    session.pop("_suite_cloud_target_page", None)


def on_browse_other_pages(session: dict[str, Any], *, target_page: str | None = None) -> None:
    """Leave Live Draft Room without ending or pausing the draft."""
    page = str(target_page or session.get("_live_draft_browse_return_page") or DEFAULT_BROWSE_PAGE).strip()
    session[BROWSING_AWAY_KEY] = True
    _apply_scheduled_page(session, page)


def on_return_to_live_draft(session: dict[str, Any]) -> None:
    session.pop(BROWSING_AWAY_KEY, None)
    session[FORCE_SYNC_ON_RETURN_KEY] = True
    _apply_scheduled_page(session, "Live Draft Room")


def on_return_to_draft_simulator(session: dict[str, Any]) -> None:
    session.pop(BROWSING_AWAY_KEY, None)
    _apply_scheduled_page(session, "Draft Room Simulator")


def _seconds_remaining(room: dict[str, Any]) -> int | None:
    try:
        from live_draft_timer_logic import live_draft_seconds_remaining

        if str(room.get("status") or "") == "in_progress":
            return int(live_draft_seconds_remaining(room))
        paused = room.get("paused_remaining_seconds")
        if paused is not None:
            return int(paused)
    except ImportError:
        pass
    return None


def _is_live_draft_room(room: Any) -> bool:
    return isinstance(room, dict) and bool(room.get("draft_room_id") or room.get("pick_order"))


def _live_draft_room_for_return(session: dict[str, Any]) -> dict[str, Any] | None:
    """Hydrate a return-card room without running the full Live Draft page pipeline."""
    room = session.get("live_draft_room")
    if _is_live_draft_room(room):
        return room
    try:
        from live_draft_state import canonical_live_draft, room_from_persist_dict

        blob = canonical_live_draft(session)
        if isinstance(blob, dict) and (blob.get("draft_room_id") or blob.get("pick_order")):
            restored = room_from_persist_dict(blob)
            if restored:
                session["live_draft_room"] = restored
                return restored
    except ImportError:
        pass
    return None


SIMULATOR_RESUME_IDENTITY_KEY = "_draft_simulator_resume_identity"
SIMULATOR_RESUME_DIAG_KEY = "_draft_simulator_resume_diag"
SIMULATOR_BOARD_OWNERSHIP_KEY = "_simulator_board_ownership"
SIMULATOR_OWNERSHIP_SCRUB_TOKEN_KEY = "_simulator_ownership_scrub_token"

# Private Draft Room Simulator runtime — cleared on account/workspace change.
# Never include shared Live Draft room keys here.
PRIVATE_SIMULATOR_RUNTIME_KEYS: tuple[str, ...] = (
    "draft_room_table",
    "draft_room_state",
    "room_your_team",
    "room_team_count",
    "room_rounds",
    "room_format",
    "room_window",
    "fantasy_draft_projection_style",
    "draft_shared_settings",
    SIMULATOR_RESUME_IDENTITY_KEY,
    SIMULATOR_BOARD_OWNERSHIP_KEY,
)


def _current_session_ownership(session: dict[str, Any]) -> dict[str, str]:
    uid = ""
    external = ""
    workspace = ""
    try:
        from fantasy_workspace_team_identity import session_account_identity

        uid, external, workspace, _, _ = session_account_identity(session)
    except ImportError:
        uid = str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
        external = str(session.get("_suite_auth_external_id") or "").strip().lower()
        workspace = str(
            session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
        ).strip()
    return {
        "auth_user_id": str(uid or "").strip(),
        "external_id": str(external or "").strip().lower(),
        "workspace_id": str(workspace or "").strip(),
    }


def _is_daniel_account(ownership: dict[str, str]) -> bool:
    ext = str(ownership.get("external_id") or "").strip().lower()
    ws = str(ownership.get("workspace_id") or "").strip().lower()
    return ext == "daniel" or ws == "daniel"


def _simulator_board_fingerprint(session: dict[str, Any]) -> str:
    """Stable fingerprint of the private simulator board (pick count + teams + players)."""
    import hashlib

    table = session.get("draft_room_table")
    if table is None or not hasattr(table, "empty") or table.empty:
        return ""
    col_team = "Fantasy Team" if "Fantasy Team" in table.columns else ("Team" if "Team" in table.columns else "")
    col_player = "Player" if "Player" in table.columns else ""
    parts: list[str] = []
    try:
        rows = table.to_dict("records") if hasattr(table, "to_dict") else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            player = str(row.get(col_player) or "").strip() if col_player else ""
            if not player:
                continue
            team = str(row.get(col_team) or "").strip() if col_team else ""
            pick = str(row.get("Pick") or row.get("pick") or "").strip()
            parts.append(f"{pick}|{team}|{player}")
    except Exception:
        return ""
    if not parts:
        return ""
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"sim:{len(parts)}:{digest}"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stamp_simulator_board_ownership(
    session: dict[str, Any],
    *,
    origin: str,
) -> dict[str, Any] | None:
    """Stamp ownership when the current account deliberately creates/edits the private board.

    Never call this merely because an unowned board exists in session.
    """
    ownership = _current_session_ownership(session)
    if not (ownership.get("auth_user_id") or ownership.get("external_id")) or not ownership.get("workspace_id"):
        return None
    board_fp = _simulator_board_fingerprint(session)
    if not board_fp:
        return None
    stamp = {
        "simulator_owner_auth_user_id": ownership.get("auth_user_id") or "",
        "simulator_owner_external_id": ownership.get("external_id") or "",
        "simulator_owner_workspace_id": ownership.get("workspace_id") or "",
        "simulator_board_fingerprint": board_fp,
        "simulator_board_created_at": _utc_now_iso(),
        "simulator_board_origin": str(origin or "local_edit").strip() or "local_edit",
    }
    session[SIMULATOR_BOARD_OWNERSHIP_KEY] = stamp
    return stamp


def verify_simulator_board_ownership(session: dict[str, Any]) -> tuple[bool, str]:
    """Return (verified, reason). Unowned boards are not owned by inventing a new stamp."""
    board_fp = _simulator_board_fingerprint(session)
    if not board_fp:
        return True, ""
    ownership = _current_session_ownership(session)
    stamp = session.get(SIMULATOR_BOARD_OWNERSHIP_KEY)
    if not isinstance(stamp, dict) or not str(stamp.get("simulator_board_fingerprint") or "").strip():
        if _is_daniel_account(ownership):
            return True, "legacy_daniel_allowed"
        return False, "legacy_or_foreign_board"
    if str(stamp.get("simulator_owner_external_id") or "").strip().lower() != (
        ownership.get("external_id") or ""
    ):
        return False, "foreign_board_owner_mismatch"
    if str(stamp.get("simulator_owner_workspace_id") or "").strip() != (ownership.get("workspace_id") or ""):
        return False, "foreign_board_workspace_mismatch"
    owned_uid = str(stamp.get("simulator_owner_auth_user_id") or "").strip()
    current_uid = ownership.get("auth_user_id") or ""
    if owned_uid and current_uid and owned_uid != current_uid:
        return False, "foreign_board_auth_mismatch"
    if str(stamp.get("simulator_board_fingerprint") or "").strip() != board_fp:
        return False, "board_fingerprint_mismatch"
    return True, ""


def scrub_simulator_runtime_for_current_account(
    session: dict[str, Any],
    *,
    reason: str = "first_render_migration",
    force: bool = False,
) -> dict[str, Any]:
    """Reject unowned/foreign private boards — safe to call on every prepare / sidebar render."""
    ownership = _current_session_ownership(session)
    token = f"{ownership.get('external_id')}|{ownership.get('workspace_id')}|{_simulator_board_fingerprint(session)}"
    if not force and session.get(SIMULATOR_OWNERSHIP_SCRUB_TOKEN_KEY) == token:
        verified, reject = verify_simulator_board_ownership(session)
        return {
            "skipped": "already_scrubbed",
            "verified": verified,
            "reason": reject,
        }
    session[SIMULATOR_OWNERSHIP_SCRUB_TOKEN_KEY] = token
    board_fp = _simulator_board_fingerprint(session)
    if not board_fp:
        return {"cleared": False, "verified": True, "reason": "empty_board"}
    verified, reject = verify_simulator_board_ownership(session)
    if verified:
        _set_resume_diag(
            session,
            simulator_board_owner_verified=True,
            simulator_board_rejected_reason="",
        )
        return {"cleared": False, "verified": True, "reason": reject or "ok"}
    clear_private_baseball_simulator_runtime(
        session,
        reason=reject or reason or "legacy_unowned_board_rejected",
    )
    session[SIMULATOR_OWNERSHIP_SCRUB_TOKEN_KEY] = (
        f"{ownership.get('external_id')}|{ownership.get('workspace_id')}|"
    )
    _set_resume_diag(
        session,
        simulator_board_owner_verified=False,
        simulator_board_rejected_reason=reject or "legacy_unowned_board_rejected",
        sidebar_source_selected="none",
        sidebar_priority_reason="foreign_or_unowned_board_cleared",
    )
    return {"cleared": True, "verified": False, "reason": reject}


def _set_resume_diag(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    ownership = _current_session_ownership(session)
    stamp = session.get(SIMULATOR_BOARD_OWNERSHIP_KEY) if isinstance(session.get(SIMULATOR_BOARD_OWNERSHIP_KEY), dict) else {}
    shared = _shared_membership_snapshot(session)
    frozen = session.get(SIMULATOR_RESUME_IDENTITY_KEY)
    frozen_ws = ""
    frozen_team = ""
    if isinstance(frozen, dict):
        frozen_ws = str(frozen.get("workspace_id") or "").strip()
        frozen_team = str(frozen.get("user_team") or "").strip()
    verified, reject = verify_simulator_board_ownership(session)
    diag = {
        "current_account": ownership.get("external_id") or ownership.get("auth_user_id") or "",
        "current_workspace": ownership.get("workspace_id") or "",
        "resume_source_kind": "",
        "resume_owner_workspace": frozen_ws or str(stamp.get("simulator_owner_workspace_id") or ""),
        "resume_team": frozen_team,
        "active_shared_room_team": shared.get("shared_membership_team") or "",
        "stale_resume_discarded_reason": "",
        "simulator_board_owner_auth_user_id": str(stamp.get("simulator_owner_auth_user_id") or ""),
        "simulator_board_owner_external_id": str(stamp.get("simulator_owner_external_id") or ""),
        "simulator_board_owner_workspace_id": str(stamp.get("simulator_owner_workspace_id") or ""),
        "simulator_board_owner_verified": verified,
        "simulator_board_rejected_reason": "" if verified else reject,
        "active_shared_room_code": shared.get("active_shared_room_code") or "",
        "shared_membership_room_id": shared.get("shared_membership_room_id") or "",
        "shared_membership_team": shared.get("shared_membership_team") or "",
        "shared_room_hydrated": bool(shared.get("shared_room_hydrated")),
        "sidebar_source_selected": "",
        "sidebar_priority_reason": "",
    }
    prev = session.get(SIMULATOR_RESUME_DIAG_KEY)
    if isinstance(prev, dict):
        if prev.get("stale_resume_discarded_reason") and "stale_resume_discarded_reason" not in fields:
            diag["stale_resume_discarded_reason"] = prev.get("stale_resume_discarded_reason")
        # Keep last rejection visible after the foreign board was cleared from session.
        if prev.get("simulator_board_rejected_reason") and "simulator_board_rejected_reason" not in fields:
            if not verified or not _simulator_board_fingerprint(session):
                diag["simulator_board_rejected_reason"] = prev.get("simulator_board_rejected_reason")
                if not _simulator_board_fingerprint(session) and prev.get("simulator_board_owner_verified") is False:
                    diag["simulator_board_owner_verified"] = False
    diag.update({k: v for k, v in fields.items() if v is not None})
    # After a foreign/unowned board was rejected and cleared, keep verified=false for diagnostics.
    if diag.get("simulator_board_rejected_reason") and not _simulator_board_fingerprint(session):
        diag["simulator_board_owner_verified"] = False
    session[SIMULATOR_RESUME_DIAG_KEY] = diag
    return diag


def collect_simulator_resume_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Compact resume ownership diagnostics for Auth/sidebar UI."""
    raw = session.get(SIMULATOR_RESUME_DIAG_KEY)
    if isinstance(raw, dict) and raw:
        return _set_resume_diag(
            session,
            resume_source_kind=raw.get("resume_source_kind") or "",
            stale_resume_discarded_reason=raw.get("stale_resume_discarded_reason") or "",
            sidebar_source_selected=raw.get("sidebar_source_selected") or "",
            sidebar_priority_reason=raw.get("sidebar_priority_reason") or "",
            simulator_board_rejected_reason=raw.get("simulator_board_rejected_reason") or "",
        )
    return _set_resume_diag(session)


def _shared_membership_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    code = ""
    try:
        from live_draft_setup_mode import shared_room_code

        code = str(shared_room_code(session) or "").strip().upper()
    except ImportError:
        pass
    if not code:
        # Prefer resolved join codes, but still honor an explicit session membership code
        # when the room object is not hydrated yet (pending lobby card).
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    team = ""
    room_id = ""
    membership_bound = False
    if code:
        try:
            from draft_room_participant_state import membership_team_for_participant

            team = str(membership_team_for_participant(session, code) or "").strip()
            membership_bound = bool(team) or _membership_entry_exists(session, code)
        except ImportError:
            membership_bound = _membership_entry_exists(session, code)
        if not team and membership_bound:
            # Global participant team only when membership binds it to this exact room.
            team = str(session.get("draft_room_participant_team") or "").strip()
        if not membership_bound:
            # Room-scoped participant_state may carry assigned_team without membership blob.
            try:
                from draft_room_participant_state import participant_state_for_room

                room_state = participant_state_for_room(session, code)
                slot_team = str(room_state.get("assigned_team") or "").strip()
                if slot_team:
                    team = team or slot_team
                    membership_bound = True
            except ImportError:
                pass
        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
        if isinstance(room, dict):
            room_id = str(room.get("draft_room_id") or room.get("room_id") or "").strip()
    hydrated = bool(_live_draft_room_for_return(session))
    has_membership = bool(code and (team or membership_bound))
    return {
        "active_shared_room_code": code,
        "shared_membership_room_id": room_id or code,
        "shared_membership_team": team,
        "shared_room_hydrated": hydrated,
        "has_shared_membership": has_membership,
    }


def _membership_entry_exists(session: dict[str, Any], room_code: str) -> bool:
    code = str(room_code or "").strip().upper()
    if not code:
        return False
    membership = session.get("draft_room_participant_membership")
    if not isinstance(membership, dict):
        return False
    entry = membership.get(code)
    return bool(entry)


def _try_hydrate_shared_room(session: dict[str, Any], room_code: str) -> dict[str, Any] | None:
    code = str(room_code or "").strip().upper()
    if not code:
        return None
    room = _live_draft_room_for_return(session)
    if isinstance(room, dict):
        return room
    try:
        from draft_room_shared_state import load_shared_room
        from live_draft_state import room_from_persist_dict

        doc = load_shared_room(code)
        if not isinstance(doc, dict):
            return None
        # Shared docs often wrap live draft under live_draft / draft_room keys.
        blob = doc.get("live_draft") or doc.get("live_draft_room") or doc.get("room") or doc
        restored = None
        if isinstance(blob, dict):
            try:
                restored = room_from_persist_dict(blob)
            except Exception:
                restored = blob if blob.get("draft_room_id") or blob.get("pick_order") or blob.get("status") else None
        if isinstance(restored, dict):
            session["live_draft_room"] = restored
            return restored
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from draft_room_context import poll_shared_draft_room, sync_shared_draft_room

        sync_shared_draft_room(session, force=True)
        poll_shared_draft_room(session)
        return _live_draft_room_for_return(session)
    except ImportError:
        pass
    except Exception:
        pass
    return None


def resolve_live_draft_activation_phase(session: dict[str, Any]) -> str:
    """Product activation phases for shared Live Draft.

    setup_draft → shared_room_created → participant_joined → participant_team_claimed → draft_started
    Setup form edits alone remain ``setup_draft`` (no shared room / membership).
    """
    snap = _shared_membership_snapshot(session)
    code = str(snap.get("active_shared_room_code") or "").strip().upper()
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
    if not isinstance(room, dict) and code:
        room = _live_draft_room_for_return(session)
    status = str((room or {}).get("status") or "").strip() if isinstance(room, dict) else ""
    if status in ("in_progress", "paused"):
        return "draft_started"
    if status == "complete":
        return "draft_complete"
    team = str(snap.get("shared_membership_team") or "").strip()
    if code and team:
        return "participant_team_claimed"
    if code and snap.get("has_shared_membership"):
        return "participant_joined"
    if code or (isinstance(room, dict) and (room.get("draft_room_id") or room.get("pick_order"))):
        return "shared_room_created"
    return "setup_draft"


def _live_room_team_label(room: dict[str, Any], *, code: str = "", team: str = "") -> tuple[str, str]:
    cfg = dict(room.get("config") or {})
    teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
    team_label = " vs ".join(teams[:4]) if teams else str(cfg.get("league_name") or code or "Draft")
    if not team:
        team = str(cfg.get("your_team") or cfg.get("user_team") or "").strip()
    return team_label, team


def _started_shared_live_draft_return_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Primary Live Draft card — only while a draft is in_progress/paused (not completed)."""
    snap = _shared_membership_snapshot(session)
    code = str(snap.get("active_shared_room_code") or "").strip().upper()
    team = str(snap.get("shared_membership_team") or "").strip()
    room = None
    if code:
        room = _try_hydrate_shared_room(session, code)
    if not isinstance(room, dict):
        room = _live_draft_room_for_return(session)
    if not isinstance(room, dict):
        return None
    status = str(room.get("status") or "").strip()
    # Completed drafts stay available via the completion hub until End Live Draft.
    # They must not advertise as an active resume target after the session ends.
    if status not in ("in_progress", "paused"):
        return None
    try:
        from live_draft_state import analyze_live_draft_progress

        progress = analyze_live_draft_progress(room)
        team_label, team = _live_room_team_label(room, code=code, team=team)
        if not team:
            team = str(session.get("draft_room_participant_team") or "").strip()
        if code:
            try:
                from draft_room_participant_state import membership_team_for_participant

                scoped = membership_team_for_participant(session, code)
                if scoped:
                    team = scoped
            except ImportError:
                pass
        if progress.get("draft_complete") or status == "complete":
            return None
        kind = "live_active"
        slot = progress.get("slot") or {}
        _set_resume_diag(
            session,
            resume_source_kind="live_draft",
            resume_team=team,
            active_shared_room_team=team,
            shared_room_hydrated=True,
            sidebar_source_selected="live_draft",
            sidebar_priority_reason="draft_started",
            simulator_board_owner_verified=verify_simulator_board_ownership(session)[0],
        )
        return {
            "kind": kind,
            "title": "Return to Live Draft",
            "team_label": team_label,
            "room_code": code,
            "mode_label": "Shared Multiplayer" if code else "Solo Draft",
            "user_team": team,
            "round_no": slot.get("Round") if isinstance(slot, dict) else None,
            "pick_no": progress.get("current_pick"),
            "on_clock": progress.get("on_clock_team") or "—",
            "picks_label": (
                f"{int(progress.get('draft_board_count') or 0)} / {int(progress.get('total_picks') or 0)} picks made"
                if progress.get("total_picks")
                else f"{int(progress.get('draft_board_count') or 0)} picks"
            ),
            "seconds_remaining": _seconds_remaining(room) if kind == "live_active" else None,
            "shared_room_hydrated": True,
            "activation_phase": resolve_live_draft_activation_phase(session),
        }
    except Exception:
        team_label, team = _live_room_team_label(room, code=code, team=team)
        kind = "live_active"
        _set_resume_diag(
            session,
            resume_source_kind="live_draft",
            resume_team=team,
            active_shared_room_team=team,
            shared_room_hydrated=True,
            sidebar_source_selected="live_draft",
            sidebar_priority_reason="draft_started",
        )
        return {
            "kind": kind,
            "title": "Return to Live Draft",
            "team_label": team_label,
            "room_code": code,
            "mode_label": "Shared Multiplayer" if code else "Solo Draft",
            "user_team": team,
            "shared_room_hydrated": True,
            "activation_phase": resolve_live_draft_activation_phase(session),
        }


def get_live_draft_lobby_return_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Secondary lobby card for created/joined rooms that have not started.

    Must not replace an owned Simulator continuation — use only as an optional
    secondary control after the primary Simulator card.
    """
    phase = resolve_live_draft_activation_phase(session)
    if phase in ("draft_started", "draft_complete", "setup_draft"):
        return None
    snap = _shared_membership_snapshot(session)
    code = str(snap.get("active_shared_room_code") or "").strip().upper()
    team = str(snap.get("shared_membership_team") or "").strip()
    room = _live_draft_room_for_return(session)
    if isinstance(room, dict) and str(room.get("status") or "").strip() in ("in_progress", "paused", "complete"):
        return None
    team_label = code or "Shared Live Draft"
    if isinstance(room, dict):
        team_label, team = _live_room_team_label(room, code=code, team=team)
    if not team:
        team = str(session.get("draft_room_participant_team") or "").strip()
    return {
        "kind": "live_lobby",
        "title": "Return to Live Draft Lobby",
        "team_label": team_label,
        "room_code": code,
        "mode_label": "Shared Multiplayer",
        "user_team": team,
        "picks_label": "Waiting for Start Draft…",
        "shared_room_hydrated": isinstance(room, dict),
        "activation_phase": phase,
        # Lobby must not advertise Pick 1 / on-clock before Start Draft.
        "round_no": None,
        "pick_no": None,
        "on_clock": None,
        "secondary": True,
    }


def _ownership_matches_frozen(session: dict[str, Any], frozen: dict[str, Any]) -> tuple[bool, str]:
    ownership = _current_session_ownership(session)
    board_fp = _simulator_board_fingerprint(session)
    checks = (
        ("auth_user_id", ownership.get("auth_user_id") or "", str(frozen.get("auth_user_id") or "").strip()),
        ("external_id", ownership.get("external_id") or "", str(frozen.get("external_id") or "").strip().lower()),
        ("workspace_id", ownership.get("workspace_id") or "", str(frozen.get("workspace_id") or "").strip()),
        ("board_fingerprint", board_fp, str(frozen.get("board_fingerprint") or "").strip()),
    )
    for label, current, owned in checks:
        if not owned:
            return False, f"missing_frozen_{label}"
        if not current:
            return False, f"missing_current_{label}"
        if current != owned:
            return False, f"mismatch_{label}"
    return True, ""


def discard_stale_simulator_resume_identity(session: dict[str, Any], *, reason: str) -> None:
    session.pop(SIMULATOR_RESUME_IDENTITY_KEY, None)
    _set_resume_diag(
        session,
        resume_source_kind="none",
        resume_owner_workspace="",
        resume_team="",
        stale_resume_discarded_reason=str(reason or "stale"),
    )


def clear_private_baseball_simulator_runtime(
    session: dict[str, Any],
    *,
    reason: str = "account_or_workspace_changed",
) -> dict[str, Any]:
    """Clear private Draft Simulator browser state without touching shared Live Draft rooms."""
    cleared: list[str] = []
    for key in PRIVATE_SIMULATOR_RUNTIME_KEYS:
        if key in session:
            session.pop(key, None)
            cleared.append(key)
    for key in (
        "draft_room_board_editor_cache",
        "draft_room_board_editor_seed",
        "draft_room_board_editor_version",
        "simulated_draft_room_table",
        "_draft_room_manual_save_result",
        "_draft_room_last_prepare_source",
        "_draft_room_picks_fp",
        "_draft_room_active_board_pick_count",
        "_draft_room_canonical_sync_reason",
        "_draft_room_canonical_pick_count",
        "local_has_draft_room_board",
        "local_draft_room_pick_count",
        "session_pick_count",
        "payload_has_draft_board",
        "cloud_payload_pick_count",
        "canonical_draft_meta",
        SIMULATOR_OWNERSHIP_SCRUB_TOKEN_KEY,
    ):
        if key in session:
            session.pop(key, None)
            cleared.append(key)
    pfs = session.get("page_filter_state")
    if isinstance(pfs, dict):
        for page_key in ("Draft Room Simulator", "Draft Workflow"):
            if page_key in pfs:
                pfs.pop(page_key, None)
                cleared.append(f"page_filter_state.{page_key}")
    # Canonical draft-room copies nested under full-session / workflow blobs in-session.
    for bag_key in ("_suite_full_session_cache", "_workflow_persist_cache", "full_session"):
        bag = session.get(bag_key)
        if not isinstance(bag, dict):
            continue
        for nested in ("draft_room_table", "draft_room_state", SIMULATOR_RESUME_IDENTITY_KEY, SIMULATOR_BOARD_OWNERSHIP_KEY):
            if nested in bag:
                bag.pop(nested, None)
                cleared.append(f"{bag_key}.{nested}")
        nested_pfs = bag.get("page_filter_state")
        if isinstance(nested_pfs, dict):
            for page_key in ("Draft Room Simulator", "Draft Workflow"):
                if page_key in nested_pfs:
                    nested_pfs.pop(page_key, None)
                    cleared.append(f"{bag_key}.page_filter_state.{page_key}")
    _set_resume_diag(
        session,
        resume_source_kind="none",
        resume_owner_workspace="",
        resume_team="",
        stale_resume_discarded_reason=str(reason or "account_or_workspace_changed"),
        simulator_board_owner_verified=False,
        simulator_board_rejected_reason=str(reason or "account_or_workspace_changed"),
    )
    session["_private_simulator_runtime_clear_trace"] = {
        "reason": reason,
        "cleared_keys": cleared,
    }
    return {"reason": reason, "cleared_keys": cleared}


def _freeze_simulator_resume_identity(session: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    """Keep an independent simulator resume card scoped to the current account-owned board."""
    picks = int(status.get("pick_count") or 0)
    if picks <= 0:
        discard_stale_simulator_resume_identity(session, reason="empty_board")
        return {}

    ownership = _current_session_ownership(session)
    board_fp = _simulator_board_fingerprint(session)
    if not board_fp:
        discard_stale_simulator_resume_identity(session, reason="missing_board_fingerprint")
        return {}
    if not (ownership.get("auth_user_id") or ownership.get("external_id")) or not ownership.get("workspace_id"):
        discard_stale_simulator_resume_identity(session, reason="unsigned_or_unscoped_session")
        return {}

    # Board ownership stamp is required — never invent ownership around a leftover board.
    verified, reject = verify_simulator_board_ownership(session)
    if not verified:
        clear_private_baseball_simulator_runtime(
            session,
            reason=reject or "legacy_unowned_board_rejected",
        )
        return {}
    if reject == "legacy_daniel_allowed":
        # Daniel may keep legacy boards for continuity, but still require an explicit stamp
        # before advertising a resume card under a fresh freeze.
        stamped = stamp_simulator_board_ownership(session, origin="legacy_daniel_resume_adopt")
        if not stamped:
            discard_stale_simulator_resume_identity(session, reason="legacy_daniel_stamp_failed")
            return {}

    frozen = session.get(SIMULATOR_RESUME_IDENTITY_KEY)
    if isinstance(frozen, dict) and str(frozen.get("user_team") or "").strip():
        ok, mismatch = _ownership_matches_frozen(session, frozen)
        if not ok:
            reason = mismatch or "ownership_mismatch"
            if reason.startswith(("mismatch_auth", "mismatch_external", "mismatch_workspace", "missing_frozen", "missing_current")):
                clear_private_baseball_simulator_runtime(session, reason=reason)
                return {}
            discard_stale_simulator_resume_identity(session, reason=reason)
            frozen = None
        else:
            updated = dict(frozen)
            updated["pick_count"] = picks
            updated["round_no"] = status.get("current_round")
            updated["pick_no"] = status.get("current_pick")
            updated["on_clock"] = status.get("on_clock_team")
            updated["board_fingerprint"] = board_fp
            updated.update(ownership)
            session[SIMULATOR_RESUME_IDENTITY_KEY] = updated
            _set_resume_diag(
                session,
                resume_source_kind="draft_simulator",
                resume_owner_workspace=ownership.get("workspace_id") or "",
                resume_team=str(updated.get("user_team") or ""),
                stale_resume_discarded_reason="",
                sidebar_source_selected="draft_simulator",
                sidebar_priority_reason="current_account_owned_simulator",
                simulator_board_owner_verified=True,
                simulator_board_rejected_reason="",
            )
            return updated

    team = str(status.get("your_team") or session.get("room_your_team") or "").strip()
    try:
        table = session.get("draft_room_table")
        if table is not None and hasattr(table, "empty") and not table.empty:
            col = "Fantasy Team" if "Fantasy Team" in table.columns else ("Team" if "Team" in table.columns else "")
            if col:
                counts = table[col].astype(str).str.strip().value_counts()
                if len(counts) > 0:
                    top = str(counts.index[0] or "").strip()
                    if top and top.lower() not in {"nan", "none"}:
                        if team and team in set(counts.index.astype(str)):
                            pass
                        else:
                            team = top
    except Exception:
        pass
    identity = {
        "kind": "simulator",
        "source_kind": "draft_simulator",
        "user_team": team,
        "pick_count": picks,
        "round_no": status.get("current_round"),
        "pick_no": status.get("current_pick"),
        "on_clock": status.get("on_clock_team"),
        "return_page": "Draft Room Simulator",
        "draft_name": str(
            session.get("sim_draft_archive_name_input")
            or session.get("draft_room_league_name")
            or "Draft Simulator"
        ),
        "board_fingerprint": board_fp,
        **ownership,
    }
    session[SIMULATOR_RESUME_IDENTITY_KEY] = identity
    _set_resume_diag(
        session,
        resume_source_kind="draft_simulator",
        resume_owner_workspace=ownership.get("workspace_id") or "",
        resume_team=team,
        stale_resume_discarded_reason="",
        sidebar_source_selected="draft_simulator",
        sidebar_priority_reason="current_account_owned_simulator",
        simulator_board_owner_verified=True,
        simulator_board_rejected_reason="",
    )
    return identity


def get_draft_return_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Primary sidebar card: active Live Draft (in_progress/paused), else owned Simulator.

    Priority:
    1. Live Draft only when status is in_progress / paused (Start Draft pressed)
       — never mere setup, completed sessions, Create Room, Join, or Claim lobby
    2. Current-account-owned private Simulator board
    3. No continuation card

    Lobby membership may still be shown via ``get_live_draft_lobby_return_context``
    as a secondary control that does not replace Simulator.
    """
    scrub_simulator_runtime_for_current_account(session, reason="sidebar_render_scrub")

    # Drop private simulator ownership that no longer matches this browser account.
    frozen = session.get(SIMULATOR_RESUME_IDENTITY_KEY)
    if isinstance(frozen, dict) and frozen:
        ok, mismatch = _ownership_matches_frozen(session, frozen)
        if not ok:
            reason = mismatch or "ownership_mismatch"
            if reason.startswith(
                ("mismatch_auth", "mismatch_external", "mismatch_workspace", "missing_frozen", "missing_current")
            ):
                clear_private_baseball_simulator_runtime(session, reason=reason)
            elif reason.startswith("mismatch_board") or reason.startswith("missing"):
                discard_stale_simulator_resume_identity(session, reason=reason)

    started_ctx = _started_shared_live_draft_return_context(session)
    if started_ctx is not None:
        return started_ctx

    # Hydrated solo/shared room still not started → fall through to Simulator.
    # Completed rooms are not resumable sidebar targets (use End Live Draft).
    room = _live_draft_room_for_return(session)
    if isinstance(room, dict):
        status = str(room.get("status") or "").strip()
        if status in ("in_progress", "paused"):
            # Membership path missed this room (no code) — still treat started room as primary.
            started_ctx = _started_shared_live_draft_return_context(session)
            if started_ctx is not None:
                return started_ctx
            try:
                from live_draft_state import analyze_live_draft_progress

                progress = analyze_live_draft_progress(room)
                if not progress.get("draft_complete"):
                    cfg = dict(room.get("config") or {})
                    teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
                    team_label = " vs ".join(teams[:4]) if teams else str(cfg.get("league_name") or "Draft")
                    user_team = str(
                        session.get("draft_room_participant_team")
                        or cfg.get("your_team")
                        or cfg.get("user_team")
                        or ""
                    ).strip()
                    slot = progress.get("slot") or {}
                    _set_resume_diag(
                        session,
                        resume_source_kind="live_draft",
                        resume_team=user_team,
                        active_shared_room_team=user_team,
                        sidebar_source_selected="live_draft",
                        sidebar_priority_reason="draft_started",
                    )
                    return {
                        "kind": "live_active",
                        "title": "Return to Live Draft",
                        "team_label": team_label,
                        "user_team": user_team,
                        "round_no": slot.get("Round") if isinstance(slot, dict) else None,
                        "pick_no": progress.get("current_pick"),
                        "on_clock": progress.get("on_clock_team") or "—",
                        "picks_label": (
                            f"{int(progress.get('draft_board_count') or 0)} / "
                            f"{int(progress.get('total_picks') or 0)} picks made"
                            if progress.get("total_picks")
                            else f"{int(progress.get('draft_board_count') or 0)} picks"
                        ),
                        "seconds_remaining": _seconds_remaining(room),
                        "activation_phase": resolve_live_draft_activation_phase(session),
                    }
            except Exception:
                pass

    try:
        from draft_room_state import ACTIVE_DRAFT_MODE_LIVE, get_active_draft_status

        status = get_active_draft_status(session)
        if status.get("active"):
            mode = status.get("mode")
            if mode == ACTIVE_DRAFT_MODE_LIVE:
                # Runtime live ownership without a return card — do not invent a lobby card here.
                return None
            identity = _freeze_simulator_resume_identity(session, status)
            if not identity:
                return None
            user_team = str(identity.get("user_team") or status.get("your_team") or "").strip()
            return {
                "kind": "simulator",
                "source_kind": "draft_simulator",
                "title": "Return to Draft Simulator",
                "picks_label": f"{int(identity.get('pick_count') or status.get('pick_count') or 0)} pick(s) logged",
                "round_no": identity.get("round_no") if identity.get("round_no") is not None else status.get("current_round"),
                "pick_no": identity.get("pick_no") if identity.get("pick_no") is not None else status.get("current_pick"),
                "on_clock": str(identity.get("on_clock") or status.get("on_clock_team") or "").strip(),
                "user_team": user_team,
                "return_page": "Draft Room Simulator",
                "draft_name": str(identity.get("draft_name") or "Draft Simulator"),
            }
    except ImportError:
        pass
    _set_resume_diag(
        session,
        resume_source_kind="none",
        sidebar_source_selected="none",
        sidebar_priority_reason="no_continuation",
    )
    return None


def apply_force_sync_on_return(session: dict[str, Any]) -> bool:
    """Fetch latest shared draft state when user returns to Live Draft Room."""
    if not session.pop(FORCE_SYNC_ON_RETURN_KEY, None):
        return False
    synced = False
    try:
        from draft_room_context import is_multiplayer_draft_active, poll_shared_draft_room, sync_shared_draft_room

        if is_multiplayer_draft_active(session):
            sync_shared_draft_room(session, force=True)
            poll_shared_draft_room(session)
            synced = True
    except ImportError:
        pass
    try:
        from draft_room_state import ensure_live_draft_synced_to_canonical_board, is_live_draft_runtime_active

        # Mirror live picks into Simulator only after Start Draft.
        if is_live_draft_runtime_active(session):
            ensure_live_draft_synced_to_canonical_board(session, reason="force_sync_on_return")
            synced = True
    except ImportError:
        pass
    return synced


def _render_return_card(
    st: Any,
    session: dict[str, Any],
    ctx: dict[str, Any],
    *,
    page_label_fn=None,
    button_key: str,
) -> None:
    kind = str(ctx.get("kind") or "")
    with st.sidebar.container(border=True):
        st.markdown(f"**{ctx.get('title')}**")
        if ctx.get("team_label"):
            st.caption(str(ctx["team_label"]))
        if ctx.get("room_code"):
            st.caption(f"Room **{ctx['room_code']}** · {ctx.get('mode_label', '')}")
        if ctx.get("user_team"):
            st.caption(f"Your team: **{ctx['user_team']}**")
        if ctx.get("round_no") and ctx.get("pick_no"):
            st.caption(f"Round **{ctx['round_no']}** · Pick **{ctx['pick_no']}**")
        on_clock = str(ctx.get("on_clock") or "").strip()
        if on_clock and on_clock != "—":
            st.caption(f"On clock: **{on_clock}**")
        if ctx.get("picks_label"):
            st.caption(str(ctx["picks_label"]))
        sec = ctx.get("seconds_remaining")
        if sec is not None and kind == "live_active":
            st.caption(f"Time remaining: **{sec}s**")

        try:
            from suite_workspace import developer_mode_checkbox_enabled

            _show_resume_diag = bool(developer_mode_checkbox_enabled(st=st))
        except ImportError:
            _show_resume_diag = False
        if _show_resume_diag:
            try:
                diag = collect_simulator_resume_diagnostics(session)
                bits = [
                    f"acct={diag.get('current_account') or '—'}",
                    f"ws={diag.get('current_workspace') or '—'}",
                    f"src={diag.get('sidebar_source_selected') or diag.get('resume_source_kind') or '—'}",
                    f"team={diag.get('resume_team') or diag.get('shared_membership_team') or '—'}",
                    f"phase={resolve_live_draft_activation_phase(session)}",
                ]
                if diag.get("shared_membership_team") or diag.get("active_shared_room_team"):
                    bits.append(
                        f"live={diag.get('shared_membership_team') or diag.get('active_shared_room_team')}"
                    )
                bits.append(f"sim_ok={diag.get('simulator_board_owner_verified')}")
                if diag.get("simulator_board_rejected_reason"):
                    bits.append(f"sim_reject={diag.get('simulator_board_rejected_reason')}")
                if diag.get("sidebar_priority_reason"):
                    bits.append(f"pri={diag.get('sidebar_priority_reason')}")
                if diag.get("stale_resume_discarded_reason"):
                    bits.append(f"discard={diag.get('stale_resume_discarded_reason')}")
                st.caption("Resume · " + " · ".join(str(b) for b in bits))
            except Exception:
                pass

        if kind == "live_active":
            st.button(
                _with_page_icon("Live Draft Room", "Return to Live Draft", page_label_fn),
                type="primary",
                key=button_key,
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "live_lobby":
            st.button(
                _with_page_icon("Live Draft Room", "Return to Live Draft Lobby", page_label_fn),
                key=button_key,
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "live_complete":
            st.button(
                _with_page_icon("Live Draft Room", "Open Live Draft Room", page_label_fn),
                key=button_key,
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "simulator":
            st.button(
                _with_page_icon("Draft Room Simulator", "Return to Draft Simulator", page_label_fn),
                type="primary",
                key=button_key,
                use_container_width=True,
                on_click=on_return_to_draft_simulator,
                args=(session,),
            )


def render_return_to_draft_sidebar(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str = "",
    page_label_fn=None,
) -> None:
    """Primary started-live/simulator card, plus optional secondary lobby control."""
    ctx = get_draft_return_context(session)
    if ctx:
        kind = str(ctx.get("kind") or "")
        if not (active_page == "Live Draft Room" and kind == "live_complete"):
            _render_return_card(
                st,
                session,
                ctx,
                page_label_fn=page_label_fn,
                button_key="sidebar_return_primary_btn",
            )

    # Secondary lobby only when primary is Simulator (or nothing) — never replaces it.
    primary_kind = str((ctx or {}).get("kind") or "")
    if primary_kind in ("", "simulator", "none"):
        lobby = get_live_draft_lobby_return_context(session)
        if lobby and active_page != "Live Draft Room":
            _render_return_card(
                st,
                session,
                lobby,
                page_label_fn=page_label_fn,
                button_key="sidebar_return_lobby_secondary_btn",
            )


def render_leave_draft_button(st: Any, session: dict[str, Any]) -> None:
    """In-room control to browse other pages without ending the draft."""
    st.button(
        "Leave Draft / Browse Other Pages",
        key="live_draft_browse_other_btn",
        help="Draft continues running. Use the sidebar Return to Draft button to come back.",
        on_click=on_browse_other_pages,
        args=(session,),
    )
