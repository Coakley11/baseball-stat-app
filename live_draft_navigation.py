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
    ("Trend Value", "Trends", "Breakouts", "trends"),
    ("Valuation", "Valuation", "Perf + trend", "valuation"),
    ("ML Predictions", "ML Projections", "Model view", "ml"),
    ("Comparison Tool", "Comparison", "Side-by-side", "comparison"),
)


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
        .ld-quick-nav-wrap { margin: 0 0 10px 0; }
        .ld-quick-nav-title {
            font-size: 13px; font-weight: 800; color: #334155;
            letter-spacing: 0.04em; margin-bottom: 10px;
        }
        .ld-quick-nav-row { margin-bottom: 6px; }
        .ld-quick-tile {
            border-radius: 12px; padding: 10px 12px 8px 12px;
            min-height: 56px; border: 1px solid transparent;
            margin-bottom: 4px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        .ld-quick-tile-assistant { background: linear-gradient(135deg,#eff6ff,#dbeafe); border-color:#93c5fd; }
        .ld-quick-tile-sleepers { background: linear-gradient(135deg,#fff7ed,#ffedd5); border-color:#fdba74; }
        .ld-quick-tile-trends { background: linear-gradient(135deg,#ecfdf5,#d1fae5); border-color:#6ee7b7; }
        .ld-quick-tile-valuation { background: linear-gradient(135deg,#f5f3ff,#ede9fe); border-color:#c4b5fd; }
        .ld-quick-tile-ml { background: linear-gradient(135deg,#fdf2f8,#fce7f3); border-color:#f9a8d4; }
        .ld-quick-tile-comparison { background: linear-gradient(135deg,#f8fafc,#e2e8f0); border-color:#cbd5e1; }
        .ld-quick-tile-label { font-size: 13px; font-weight: 800; color: #0f172a; line-height: 1.25; }
        .ld-quick-tile-sub { font-size: 10px; color: #64748b; margin-top: 3px; line-height: 1.25; }
        div[data-testid="column"] .ld-quick-tile + div[data-testid="stButton"] button {
            min-height: 30px; padding: 4px 10px; font-size: 11px; font-weight: 700;
            border-radius: 8px; margin-top: 2px;
        }
        @media (max-width: 768px) {
            .ld-quick-nav-wrap { margin-bottom: 8px; }
            .ld-quick-tile { min-height: 48px; padding: 8px 10px 6px 10px; }
            .ld-quick-tile-label { font-size: 12px; }
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
    """Color-coded navigation tiles to related fantasy pages."""
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

    inject_live_draft_quick_nav_styles(st)
    st.markdown('<div class="ld-quick-nav-wrap"><div class="ld-quick-nav-title">Quick navigation</div></div>', unsafe_allow_html=True)
    row_size = 3
    for row_start in range(0, len(LIVE_DRAFT_QUICK_NAV_PAGES), row_size):
        row_pages = LIVE_DRAFT_QUICK_NAV_PAGES[row_start : row_start + row_size]
        cols = st.columns(len(row_pages))
        for col, (page, label, subtitle, theme) in zip(cols, row_pages):
            with col:
                col.markdown(
                    f'<div class="ld-quick-tile ld-quick-tile-{theme}">'
                    f'<div class="ld-quick-tile-label">{_with_page_icon(page, label, page_label_fn)}</div>'
                    f'<div class="ld-quick-tile-sub">{subtitle}</div></div>',
                    unsafe_allow_html=True,
                )
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


def _set_resume_diag(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    ownership = _current_session_ownership(session)
    shared_team = str(session.get("draft_room_participant_team") or "").strip()
    if not shared_team:
        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
        if isinstance(room, dict):
            cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
            shared_team = str(cfg.get("your_team") or cfg.get("user_team") or "").strip()
    frozen = session.get(SIMULATOR_RESUME_IDENTITY_KEY)
    frozen_ws = ""
    frozen_team = ""
    if isinstance(frozen, dict):
        frozen_ws = str(frozen.get("workspace_id") or "").strip()
        frozen_team = str(frozen.get("user_team") or "").strip()
    diag = {
        "current_account": ownership.get("external_id") or ownership.get("auth_user_id") or "",
        "current_workspace": ownership.get("workspace_id") or "",
        "resume_source_kind": "",
        "resume_owner_workspace": frozen_ws,
        "resume_team": frozen_team,
        "active_shared_room_team": shared_team,
        "stale_resume_discarded_reason": "",
    }
    prev = session.get(SIMULATOR_RESUME_DIAG_KEY)
    if isinstance(prev, dict):
        # Keep last discard reason until overwritten or cleared explicitly.
        if prev.get("stale_resume_discarded_reason") and "stale_resume_discarded_reason" not in fields:
            diag["stale_resume_discarded_reason"] = prev.get("stale_resume_discarded_reason")
    diag.update({k: v for k, v in fields.items() if v is not None})
    session[SIMULATOR_RESUME_DIAG_KEY] = diag
    return diag


def collect_simulator_resume_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Compact resume ownership diagnostics for Auth/sidebar UI."""
    raw = session.get(SIMULATOR_RESUME_DIAG_KEY)
    if isinstance(raw, dict) and raw:
        # Refresh live fields without wiping discard reason.
        return _set_resume_diag(
            session,
            resume_source_kind=raw.get("resume_source_kind") or "",
            stale_resume_discarded_reason=raw.get("stale_resume_discarded_reason") or "",
        )
    return _set_resume_diag(session)


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
    # Also drop common simulator editor aliases that can rehydrate the stale board.
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
    ):
        if key in session:
            session.pop(key, None)
            cleared.append(key)
    # page_filter_state often rehydrates draft_room_table after account switches.
    pfs = session.get("page_filter_state")
    if isinstance(pfs, dict):
        for page_key in ("Draft Room Simulator", "Draft Workflow"):
            if page_key in pfs:
                pfs.pop(page_key, None)
                cleared.append(f"page_filter_state.{page_key}")
    _set_resume_diag(
        session,
        resume_source_kind="none",
        resume_owner_workspace="",
        resume_team="",
        stale_resume_discarded_reason=str(reason or "account_or_workspace_changed"),
    )
    session["_private_simulator_runtime_clear_trace"] = {
        "reason": reason,
        "cleared_keys": cleared,
    }
    return {"reason": reason, "cleared_keys": cleared}


def _freeze_simulator_resume_identity(session: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    """Keep an independent simulator resume card scoped to the current account/workspace/board."""
    picks = int(status.get("pick_count") or 0)
    if picks <= 0:
        discard_stale_simulator_resume_identity(session, reason="empty_board")
        return {}

    ownership = _current_session_ownership(session)
    board_fp = _simulator_board_fingerprint(session)
    if not board_fp:
        discard_stale_simulator_resume_identity(session, reason="missing_board_fingerprint")
        return {}
    # Require a signed-in / workspace-scoped owner before freezing private resume.
    if not (ownership.get("auth_user_id") or ownership.get("external_id")) or not ownership.get("workspace_id"):
        discard_stale_simulator_resume_identity(session, reason="unsigned_or_unscoped_session")
        return {}

    frozen = session.get(SIMULATOR_RESUME_IDENTITY_KEY)
    if isinstance(frozen, dict) and str(frozen.get("user_team") or "").strip():
        ok, mismatch = _ownership_matches_frozen(session, frozen)
        if not ok:
            reason = mismatch or "ownership_mismatch"
            # Account/workspace ownership failures must wipe the private board, not rebuild
            # a Donny resume under Coakley11 from leftover Daniel board rows.
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
            )
            return updated

    team = str(status.get("your_team") or session.get("room_your_team") or "").strip()
    # Prefer the most frequent Fantasy Team on the board when room_your_team already drifted.
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
    )
    return identity


def get_draft_return_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Sidebar card context for active live draft, lobby, completed draft, or simulator."""
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

    room = _live_draft_room_for_return(session)

    if isinstance(room, dict):
        try:
            from live_draft_state import analyze_live_draft_progress, has_active_live_draft
            from live_draft_setup_mode import is_shared_multiplayer_intent, shared_room_code

            progress = analyze_live_draft_progress(room)
            cfg = dict(room.get("config") or {})
            teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
            team_label = " vs ".join(teams[:4]) if teams else str(cfg.get("league_name") or "Draft")
            mode_label = "Shared Multiplayer" if is_shared_multiplayer_intent(session, room=room) else "Solo Draft"
            code = shared_room_code(session) or ""
            user_team = str(session.get("draft_room_participant_team") or cfg.get("your_team") or cfg.get("user_team") or "")
            try:
                from fantasy_workspace_team_identity import resolve_current_account_team_for_live_draft_and_league

                resolved = resolve_current_account_team_for_live_draft_and_league(session, room=room)
                if resolved:
                    user_team = resolved
            except ImportError:
                pass
            slot = progress.get("slot") or {}
            round_no = slot.get("Round") if isinstance(slot, dict) else None
            pick_no = progress.get("current_pick")
            on_clock = progress.get("on_clock_team") or "—"
            done = int(progress.get("draft_board_count") or 0)
            total = int(progress.get("total_picks") or 0)
            status = str(room.get("status") or "").strip()

            if progress.get("draft_complete") or status == "complete":
                _set_resume_diag(
                    session,
                    resume_source_kind="live_complete",
                    resume_team=user_team,
                    active_shared_room_team=user_team,
                )
                return {
                    "kind": "live_complete",
                    "title": "Draft Completed",
                    "team_label": team_label,
                    "picks_label": f"{done} of {total} picks completed" if total else f"{done} picks",
                    "room_code": code,
                    "mode_label": mode_label,
                    "user_team": user_team,
                }

            if has_active_live_draft(session) or status in ("not_started", "in_progress", "paused"):
                # Shared Live Draft always wins over any private simulator continuation.
                _set_resume_diag(
                    session,
                    resume_source_kind="live_draft",
                    resume_team=user_team,
                    active_shared_room_team=user_team,
                )
                return {
                    "kind": "live_active" if status in ("in_progress", "paused") else "live_lobby",
                    "title": "Return to Live Draft",
                    "team_label": team_label,
                    "room_code": code,
                    "mode_label": mode_label,
                    "user_team": user_team,
                    "round_no": round_no,
                    "pick_no": pick_no,
                    "on_clock": on_clock,
                    "picks_label": f"{done} / {total} picks made" if total else f"{done} picks",
                    "seconds_remaining": _seconds_remaining(room),
                }
        except Exception:
            status = str(room.get("status") or "").strip()
            user_team = str(session.get("draft_room_participant_team") or "")
            if status == "complete":
                _set_resume_diag(
                    session,
                    resume_source_kind="live_complete",
                    resume_team=user_team,
                    active_shared_room_team=user_team,
                )
                return {
                    "kind": "live_complete",
                    "title": "Draft Completed",
                    "team_label": str((room.get("config") or {}).get("league_name") or "Live Draft"),
                    "user_team": user_team,
                }
            _set_resume_diag(
                session,
                resume_source_kind="live_draft",
                resume_team=user_team,
                active_shared_room_team=user_team,
            )
            return {
                "kind": "live_active" if status in ("in_progress", "paused") else "live_lobby",
                "title": "Return to Live Draft",
                "team_label": str((room.get("config") or {}).get("league_name") or "Live Draft"),
                "user_team": user_team,
            }

    try:
        from draft_room_state import ACTIVE_DRAFT_MODE_LIVE, get_active_draft_status

        status = get_active_draft_status(session)
        if status.get("active"):
            mode = status.get("mode")
            if mode == ACTIVE_DRAFT_MODE_LIVE:
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
    _set_resume_diag(session, resume_source_kind="none")
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
        from draft_room_state import ensure_live_draft_synced_to_canonical_board

        ensure_live_draft_synced_to_canonical_board(session, reason="force_sync_on_return")
        synced = True
    except ImportError:
        pass
    return synced


def render_return_to_draft_sidebar(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str = "",
    page_label_fn=None,
) -> None:
    """Prominent sidebar card to return to active live draft, completed draft, or simulator."""
    ctx = get_draft_return_context(session)
    if not ctx:
        return

    kind = str(ctx.get("kind") or "")
    if active_page == "Live Draft Room" and kind == "live_complete":
        return
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
            diag = collect_simulator_resume_diagnostics(session)
            bits = [
                f"acct={diag.get('current_account') or '—'}",
                f"ws={diag.get('current_workspace') or '—'}",
                f"src={diag.get('resume_source_kind') or '—'}",
                f"team={diag.get('resume_team') or diag.get('active_shared_room_team') or '—'}",
            ]
            if diag.get("active_shared_room_team"):
                bits.append(f"live={diag.get('active_shared_room_team')}")
            if diag.get("stale_resume_discarded_reason"):
                bits.append(f"discard={diag.get('stale_resume_discarded_reason')}")
            st.caption("Resume · " + " · ".join(bits))
        except Exception:
            pass

        if kind in ("live_active", "live_lobby"):
            st.button(
                _with_page_icon("Live Draft Room", "Return to Live Draft", page_label_fn),
                type="primary",
                key="sidebar_return_live_draft_btn",
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "live_complete":
            st.button(
                _with_page_icon("Live Draft Room", "Open Live Draft Room", page_label_fn),
                key="sidebar_open_completed_draft_btn",
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "simulator":
            st.button(
                _with_page_icon("Draft Room Simulator", "Return to Draft Simulator", page_label_fn),
                type="primary",
                key="sidebar_return_simulator_btn",
                use_container_width=True,
                on_click=on_return_to_draft_simulator,
                args=(session,),
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
