"""Streamlit UI for weekly lineup management — circular face-to-circle board."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

import pandas as pd

from fantasy_lineup_interactive_board import (
    apply_drop_event,
    build_interactive_board_payload,
    parse_board_drop_result,
    parse_board_player_select,
    render_interactive_lineup_board,
)
from fantasy_lineup_scope import (
    LINEUP_IDENTITY_SYNC_ERROR,
    assert_lineup_write_identity,
    apply_lineup_scope_change,
    render_lineup_identity_diagnostics_from_session,
    resolve_canonical_lineup_team,
    resolve_lineup_scope,
)
from fantasy_lineup_ui import (
    SlotKeyLabel,
    build_slot_key_labels,
    emit_html_block,
    inject_lineup_board_styles,
    slot_key_labels_as_tuples,
)
from fantasy_league_lineup_format import (
    is_lineup_format_commissioner,
    resolve_lineup_page_context,
)
from fantasy_league_lineup_format_ui import (
    render_edit_lineup_format_action,
    render_lineup_format_setup,
)
from fantasy_weekly_hitter_scoring import (
    ensure_weekly_scoring_populated,
    get_weekly_scoring_record,
    maybe_mark_legacy_lineup_scoring,
    resolve_hitter_scoring_profile,
    should_start_week_empty,
    week_editability_message,
)
from fantasy_weekly_hitter_scoring_ui import (
    render_finalize_week_section,
    render_locked_weekly_dashboard,
    render_player_detail_panel,
    render_scoring_refresh_controls,
    render_week_transition_notice,
)
from fantasy_weekly_lineup import (
    assignments_to_slot_player_map,
    eligible_players_for_slot,
    get_saved_weekly_lineup,
    is_lineup_locked,
    list_week_options,
    not_starting_players,
    persist_weekly_lineup_draft,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
    slot_display_name,
    validate_weekly_lineup,
    week_label,
)


def canonical_week_key(prefix: str, week: int, *, scope_key: str = "") -> str:
    """Session key holding the canonical assignment dict for a scoped week."""
    if scope_key:
        return f"{scope_key}|assignments"
    return f"{prefix}_canon_{int(week)}"


def assignment_signature(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (key, str((assignments or {}).get(key) or "").strip()) for key, _label in slot_keys
    )


def _normalize_assignments(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
) -> dict[str, str]:
    return {key: str((assignments or {}).get(key) or "").strip() for key, _label in slot_keys}


def ensure_canonical_assignments(
    session: dict[str, Any],
    *,
    canon_key: str,
    slot_keys: list[tuple[str, str]],
    saved_assignments: dict[str, str],
    scope_changed: bool = False,
) -> dict[str, str]:
    """Return canonical per-scope assignments; hydrate from persisted when scope changes."""
    saved_norm = _normalize_assignments(saved_assignments, slot_keys)
    if scope_changed:
        session[canon_key] = dict(saved_norm)
        return dict(session[canon_key])

    current = session.get(canon_key)
    if not isinstance(current, dict):
        session[canon_key] = dict(saved_norm)
    else:
        current_norm = _normalize_assignments(current, slot_keys)
        for key, _label in slot_keys:
            current_norm.setdefault(key, "")
        session[canon_key] = current_norm
    return dict(session[canon_key])


def reconcile_editor_assignments(
    session: dict[str, Any],
    *,
    canon_key: str,
    slot_keys: list[tuple[str, str]],
    new_assignments: dict[str, str],
) -> bool:
    current = session.get(canon_key) or {}
    if assignment_signature(new_assignments, slot_keys) != assignment_signature(current, slot_keys):
        session[canon_key] = _normalize_assignments(new_assignments, slot_keys)
        return True
    return False


def _waiver_slot_label_for_open_prompt(slot_label: SlotKeyLabel) -> str:
    if slot_label.base_slot == "OF":
        return "Outfield"
    return slot_display_name(slot_label.base_slot)


def _unused_roster_options(team_roster: pd.DataFrame | None, code: str, assigned: set[str]) -> list[str]:
    """Rostered players eligible for ``code`` who are not already in this week's lineup."""
    if team_roster is None or getattr(team_roster, "empty", True):
        return []
    return [name for name in eligible_players_for_slot(team_roster, code) if name not in assigned]


def build_open_slot_prompts(
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
    team_roster: pd.DataFrame | None = None,
) -> list[dict[str, str]]:
    """One prompt per open position (outfield combined).

    With ``team_roster``, an open spot that an unused rostered player can fill asks the
    user to start someone from the roster; the waiver button is only offered when the
    roster has nobody eligible (or not enough outfielders).
    """
    open_slots = [label for label in slot_labels if not str(assignments.get(label.key) or "").strip()]
    if not open_slots:
        return []

    try:
        from fantasy_roster_validation import missing_position_message, open_waiver_button_label
    except ImportError:
        missing_position_message = None  # type: ignore[assignment]
        open_waiver_button_label = None  # type: ignore[assignment]

    assigned = {str(v or "").strip() for v in assignments.values() if str(v or "").strip()}
    check_roster = team_roster is not None and not getattr(team_roster, "empty", True)

    def _missing(code: str, fallback: str) -> tuple[str, str]:
        if missing_position_message is not None:
            return missing_position_message(code), open_waiver_button_label(code)
        return fallback, "Open Waiver Wire"

    rows: list[dict[str, str]] = []
    of_labels = [label for label in open_slots if label.base_slot == "OF"]
    other_labels = [label for label in open_slots if label.base_slot != "OF"]

    for label in other_labels:
        code = str(label.base_slot or "").strip().upper()
        options = _unused_roster_options(team_roster, code, assigned) if check_roster else []
        if options:
            text, button = f"{slot_display_name(code)} open — start someone from your roster", ""
        else:
            text, button = _missing(code, f"{label.label} is empty")
        rows.append(
            {
                "text": text,
                "waiver_label": _waiver_slot_label_for_open_prompt(label),
                "button_label": button,
                "position_code": code,
            }
        )

    if of_labels:
        n_open = len(of_labels)
        n_options = len(_unused_roster_options(team_roster, "OF", assigned)) if check_roster else 0
        short = max(0, n_open - n_options)
        if short == 0:
            spots = "Outfield spot" if n_open == 1 else f"{n_open} outfield spots"
            text, button = f"{spots} open — start someone from your roster", ""
        elif n_open == 1:
            text, button = _missing("OF", f"{of_labels[0].label} is empty")
        elif missing_position_message is not None:
            text = f"Missing {short} outfielder" + ("" if short == 1 else "s")
            if n_options:
                text += f" — your roster covers {n_options} of the {n_open} open spots"
            button = open_waiver_button_label("OF")
        else:
            text, button = f"{n_open} Outfield spots are empty", "Open Waiver Wire"
        rows.append(
            {
                "text": text,
                "waiver_label": "Outfield",
                "button_label": button,
                "position_code": "OF",
            }
        )
    return rows


def _phone_inline_row(st: Any, key: str):
    try:
        from fantasy_mobile_layout import phone_inline_row

        return phone_inline_row(st, key)
    except ImportError:  # pragma: no cover
        from contextlib import nullcontext

        return nullcontext()


def _wrap_row(st: Any, key: str):
    """Phones: keep a short button row two-up instead of stacking (desktop unchanged)."""
    try:
        from mobile_foundation import mobile_wrap_row

        return mobile_wrap_row(st, key)
    except ImportError:  # pragma: no cover
        return nullcontext()


def _inject_open_slots_styles(st: Any) -> None:
    emit_html_block(
        st,
        """
<style>
.fl-open-slots-wrap { margin: 2px 0 6px 0; }
.fl-open-slots-wrap [data-testid="column"] { padding-top: 0.15rem; padding-bottom: 0.15rem; }
.fl-open-slots-wrap p { margin: 0; line-height: 1.35; font-size: 0.92rem; }
</style>
<div class="fl-open-slots-wrap"></div>
""",
    )


def _render_open_slots_and_validation(
    st: Any,
    *,
    slots: list[str],
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
    team_roster: pd.DataFrame,
    on_open_waiver_wire: Callable[[str], None] | None,
    prefix: str,
    selected_week: int,
) -> dict[str, Any]:
    validation = validate_weekly_lineup(slots, assignments, team_roster)

    for message in validation.get("messages") or []:
        lower = str(message).lower()
        if " is empty" in lower:
            continue
        if "need eligible" in lower and "waiver wire" in lower:
            continue
        if "empty" in lower or "not eligible" in lower or "twice" in lower:
            st.warning(message)
        else:
            st.info(message)

    open_rows = build_open_slot_prompts(slot_labels, assignments, team_roster)
    if open_rows:
        _inject_open_slots_styles(st)
        # Phones: keep "Missing X" and its waiver button on one line (desktop unchanged).
        with _phone_inline_row(st, "fl-open-slots"):
            for idx, row in enumerate(open_rows):
                text_col, btn_col = st.columns([5, 2], gap="small")
                with text_col:
                    st.markdown(f"**{row['text']}**")
                with btn_col:
                    if on_open_waiver_wire is not None and row.get("button_label"):
                        st.button(
                            str(row.get("button_label") or "Open Waiver Wire"),
                            key=f"{prefix}_waiver_{row['waiver_label']}_{idx}_{int(selected_week)}",
                            on_click=on_open_waiver_wire,
                            args=(row["waiver_label"],),
                        )

    return validation


def _proxy_controls(session: dict[str, Any], context: dict[str, Any], *, own_team: str) -> list[Any]:
    """Unclaimed teams the commissioner may act for (never the user's own team)."""
    try:
        from fantasy_team_control import manageable_teams
    except ImportError:
        return []
    return [c for c in manageable_teams(session, context) if c.is_proxy and c.team != own_team]


def _render_manage_team_picker(st: Any, session: dict[str, Any], context: dict[str, Any], *, own_team: str,
                               proxy: list[Any] | None = None):
    """Commissioner picks a team to manage; returns its TeamControl when acting as proxy."""
    if proxy is None:
        proxy = _proxy_controls(session, context, own_team=own_team)
    if not proxy:
        return None
    options = ([own_team] if own_team else []) + [c.team for c in proxy]
    key = "lineup_manage_team"
    if session.get(key) not in options:
        session[key] = options[0]
    choice = st.selectbox(
        "Manage team",
        options,
        key=key,
        format_func=lambda t: f"{t} (your team)" if t == own_team else f"{t} — unclaimed, commissioner",
        help="As commissioner you can set lineups for teams no manager has claimed yet.",
    )
    return next((c for c in proxy if c.team == choice), None)


_SAVE_ERROR_KEY = "_weekly_lineup_save_error"


def _on_save_lineup_click(scope: Any, proxy_control: Any, **save_kwargs: Any) -> None:
    import streamlit as st

    session = st.session_state
    write_ok, write_err = _lineup_write_check(scope, proxy_control)
    if not write_ok:
        session[_SAVE_ERROR_KEY] = write_err
        return
    result = save_weekly_lineup(session, **save_kwargs)
    if result.get("ok"):
        session["weekly_lineup_save_flash"] = True
    else:
        session[_SAVE_ERROR_KEY] = "; ".join(result.get("errors") or []) or "Couldn't save changes. Try again."


def _lineup_write_check(scope: Any, proxy_control: Any) -> tuple[bool, str]:
    if proxy_control is not None and proxy_control.is_proxy:
        return True, ""
    return assert_lineup_write_identity(scope)


def render_weekly_lineup_section(
    st: Any,
    session: dict[str, Any],
    *,
    team_roster: pd.DataFrame,
    lineup_team: str,
    on_open_waiver_wire: Callable[[str], None] | None = None,
    scored_roster: pd.DataFrame | None = None,
    nav_callback: Callable[[str], Callable[[], None]] | None = None,
) -> None:
    """Weekly lineup builder — one circular face-to-circle interaction.

    U3 order: Commissioner Tools (commissioners only) → week → answer (complete? missing? saved?)
    → next actions → board → Save Lineup. ``nav_callback(page)`` returns an on_click callback
    that only navigates (Check Waivers)."""
    del scored_roster
    import ui_hierarchy as ui

    context = resolve_lineup_page_context(session)
    if not context:
        st.info("Set an **Active Draft** to manage your weekly lineup.")
        return

    page_team = str(lineup_team or "").strip()
    active_team = resolve_canonical_lineup_team(session, context, page_lineup_team=page_team)
    if not active_team:
        active_team = str(context.get("my_team_name") or page_team or "").strip()
    if page_team and active_team and page_team != active_team:
        st.warning(LINEUP_IDENTITY_SYNC_ERROR)

    # Commissioner controls live in one panel, apart from the team's own lineup. It is
    # created here and filled as the page renders (team picker now; format, calendar and
    # finalize further down).
    is_commissioner = bool(is_lineup_format_commissioner(session, context))
    proxy_teams = _proxy_controls(session, context, own_team=active_team)
    panel = ui.commissioner_panel(st) if (is_commissioner or proxy_teams) else None
    proxy_control = None
    with (panel if panel is not None else nullcontext()):
        proxy_choice = _render_manage_team_picker(st, session, context, own_team=active_team, proxy=proxy_teams)
    if proxy_choice is not None:
        proxy_control = proxy_choice
        active_team = proxy_control.team
        page_team = proxy_control.team
        team_roster = None  # load this team's roster below
        ui.proxy_banner(st, proxy_control.banner(),
                        "This team is unclaimed; lineups you set are logged as commissioner actions.")

    if not active_team:
        st.info("Claim your team in this league before managing weekly lineups.")
        return

    if team_roster is None or team_roster.empty:
        try:
            from fantasy_lineup_stats_loader import ensure_lineup_page_hitter_stats

            loaded = ensure_lineup_page_hitter_stats(session, context)
            if isinstance(loaded.get("roster_stats"), pd.DataFrame) and not loaded["roster_stats"].empty:
                if "Team" in loaded["roster_stats"].columns:
                    team_roster = loaded["roster_stats"][
                        loaded["roster_stats"]["Team"].astype(str) == active_team
                    ].copy()
                else:
                    team_roster = loaded["roster_stats"].copy()
            elif loaded.get("error"):
                st.warning(str(loaded["error"]))
        except ImportError:
            pass
    if team_roster is None or team_roster.empty:
        st.warning(
            "Load roster stats to set your weekly lineup. "
            "The app will try to fetch current MLB stats automatically when an active league is set."
        )
        return

    if session.pop("lineup_format_saved_flash", None) and is_lineup_format_commissioner(session, context):
        st.success("League lineup format saved.")

    if bool(session.get("lineup_format_editing")):
        render_lineup_format_setup(st, session, team_roster=team_roster, editing=True)
        return
    if not render_lineup_format_setup(st, session, team_roster=team_roster):
        return

    with (panel if panel is not None else nullcontext()):
        render_edit_lineup_format_action(st, session)
    inject_lineup_board_styles(st)

    slots = resolve_weekly_lineup_slots(context)
    if not slots:
        st.info("League starting positions are not configured yet.")
        return
    slot_labels = build_slot_key_labels(slots)
    slot_keys = slot_key_labels_as_tuples(slot_labels)
    from fantasy_season_ledger import current_period_number
    from fantasy_season_ledger_ui import (
        period_editability,
        period_option_label,
        period_week_options,
        render_season_calendar_setup,
    )

    render_season_calendar_setup(st, session, context, is_commissioner=is_commissioner,
                                 panel=panel if is_commissioner else None)
    ledger_weeks = period_week_options(context)
    week_options = ledger_weeks or list_week_options()
    prefix = "weekly_lineup"
    if proxy_control is not None:
        import re as _re

        prefix = "weekly_lineup_proxy_" + _re.sub(r"[^A-Za-z0-9]+", "_", active_team)
    if ledger_weeks and session.get(f"{prefix}_selected_week") not in ledger_weeks:
        session[f"{prefix}_selected_week"] = current_period_number(context) or ledger_weeks[0]

    drop_flash = session.pop("weekly_lineup_drop_flash", None)
    if drop_flash:
        st.success(str(drop_flash))

    if session.pop("weekly_lineup_save_flash", None):
        from ui_user_copy import LINEUP_SAVED

        st.success(LINEUP_SAVED)

    if f"{prefix}_selected_week" not in session:
        session[f"{prefix}_selected_week"] = week_options[0]

    week_cols = st.columns([2, 3])
    with week_cols[0]:
        selected_week = st.selectbox(
            "Week",
            week_options,
            format_func=(lambda w: period_option_label(context, w)) if ledger_weeks else week_label,
            key=f"{prefix}_selected_week",
        )

    # Proxy edits use team-specific keys; the account's own lineup scope stays untouched.
    scope = None if proxy_control is not None else resolve_lineup_scope(
        session, context, week=int(selected_week), page_lineup_team=page_team
    )
    scope_changed = bool(scope and apply_lineup_scope_change(session, scope))

    saved = get_saved_weekly_lineup(context, int(selected_week), team=active_team, session=session)
    saved_assignments = dict((saved or {}).get("assignments") or {})

    lineup_locked = is_lineup_locked(context, int(selected_week), team=active_team, session=session)
    if ledger_weeks:
        lineup_locked, edit_message = period_editability(
            context, int(selected_week), lineup_locked=lineup_locked, is_commissioner=is_commissioner
        )
    else:
        edit_state, edit_message = week_editability_message(context, int(selected_week))
        if edit_state in ("future", "past"):
            lineup_locked = True
    # edit_message is stated in the answer below.

    scoring_profile = resolve_hitter_scoring_profile(context, session=session)
    if not ledger_weeks:  # legacy weekly scoring (leagues without a season calendar)
        context = maybe_mark_legacy_lineup_scoring(
            session,
            context,
            week=int(selected_week),
            team=active_team,
            saved_lineup=saved,
        )
        render_week_transition_notice(st, context=context, week=int(selected_week))

    canon_key = scope.assignments_key if scope else canonical_week_key(prefix, int(selected_week))
    if should_start_week_empty(context, int(selected_week)) and not lineup_locked and not saved_assignments:
        session[canon_key] = {key: "" for key, _ in slot_keys}
        saved_assignments = dict(session[canon_key])

    assignments = ensure_canonical_assignments(
        session,
        canon_key=canon_key,
        slot_keys=slot_keys,
        saved_assignments=saved_assignments,
        scope_changed=scope_changed,
    )

    # U1: "Use Suggested Lineup" (flag set by the button's on_click) fills the board with the
    # recommended starters and keeps it as a draft. It never saves, locks or finalizes.
    board_nonce_key = scope.board_nonce_key if scope else f"{prefix}_board_nonce_{int(selected_week)}"
    suggest_flag = f"{canon_key}|apply_suggested"
    if session.pop(suggest_flag, False) and not lineup_locked:
        from suggested_lineup import apply_suggested_lineup

        applied = apply_suggested_lineup(
            session,
            week=int(selected_week),
            slots=list(slots),
            slot_labels=slot_labels,
            team_roster=team_roster,
            team=active_team,
            scoring_format=str(session.get("lineup_format") or "5x5 Roto"),
            write_check=lambda: _lineup_write_check(scope, proxy_control),
        )
        if applied["ok"]:
            session[canon_key] = _normalize_assignments(applied["assignments"], slot_keys)
            assignments = dict(session[canon_key])
            session[board_nonce_key] = int(session.get(board_nonce_key, 0)) + 1
            st.success(applied["message"])
            if applied["unfilled"]:
                st.warning("No eligible player on this roster for: " + ", ".join(
                    slot_display_name(s) for s in applied["unfilled"]) + ".")
        else:
            st.error("; ".join(applied["errors"]))

    try:
        from suite_workspace import can_show_developer_tools

        if can_show_developer_tools(st=st):
            with st.expander("Lineup identity diagnostics (Developer Mode)", expanded=False):
                render_lineup_identity_diagnostics_from_session(st, session, scope)
    except ImportError:
        pass

    # U3 answer: is this week's lineup complete, what is missing, is it saved. Built from the
    # same validation Save Lineup enforces and the saved record's own status.
    from u3_answers import lineup_answer

    week_text = period_option_label(context, int(selected_week)) if ledger_weeks else week_label(int(selected_week))
    slot_map_now = {label.key: str(assignments.get(label.key) or "").strip() for label in slot_labels}
    answer = lineup_answer(
        team=active_team,
        week_text=week_text,
        slots=slot_keys,
        assignments=assignments,
        validation=validate_weekly_lineup(slots, assignments, team_roster),
        bench_count=len(not_starting_players(team_roster, slot_map_now)),
        locked=bool(lineup_locked),
        record_status=str((saved or {}).get("status") or ""),
        edit_message=str(edit_message or ""),
        proxy=proxy_control is not None,
    )
    ui.answer_card(st, answer["headline"], answer["body"], kicker=answer["kicker"], tone=answer["tone"])
    ui.metric_tiles(st, answer["tiles"])
    ui.chips(st, answer["chips"])

    if lineup_locked:
        try:
            from fantasy_lineup_stats_loader import ensure_lineup_page_hitter_stats

            stats_load = ensure_lineup_page_hitter_stats(session, context)
            if stats_load.get("error") and team_roster.empty:
                st.warning(str(stats_load["error"]))
            elif isinstance(stats_load.get("roster_stats"), pd.DataFrame) and not stats_load["roster_stats"].empty:
                merged = stats_load["roster_stats"]
                if "Team" in merged.columns:
                    subset = merged[merged["Team"].astype(str) == str(active_team)]
                    if not subset.empty:
                        team_roster = subset.copy()
        except ImportError:
            pass

        if ledger_weeks:
            from fantasy_season_ledger import PERIOD_FINALIZED, get_period, period_date_label, period_status
            from fantasy_season_results_ui import render_team_period_result

            _period = get_period(context, int(selected_week))
            if period_status(_period) == PERIOD_FINALIZED:
                render_team_period_result(st, context, int(selected_week), active_team)
            else:
                st.caption(
                    f"Results for this week are calculated when the commissioner finalizes it, from stats for "
                    f"{period_date_label(_period)} only — later roster moves never change them."
                )
        else:
            scoring_record = render_scoring_refresh_controls(
                st,
                session,
                context=context,
                week=int(selected_week),
                team=active_team,
                roster_df=team_roster,
                prefix=prefix,
            )
            if scoring_record is None:
                scoring_record = get_weekly_scoring_record(context, week=int(selected_week), team=active_team)
            scoring_record = ensure_weekly_scoring_populated(
                session,
                context,
                week=int(selected_week),
                team=active_team,
                roster_df=team_roster,
                profile=scoring_profile,
            ) or scoring_record
            render_locked_weekly_dashboard(
                st,
                context=context,
                week=int(selected_week),
                team=active_team,
                scoring_record=scoring_record,
                profile=scoring_profile,
                roster_df=team_roster,
                saved_lineup=saved,
                session=session,
            )

    # Next actions. None of them saves: Save Lineup (below the board) is the only submit.
    actions = []
    if not lineup_locked:
        actions.append("suggest")
    if nav_callback is not None:
        actions.append("waivers")
    if proxy_control is None:
        actions.append("trades")
    with _wrap_row(st, f"u3-lineup-actions-{prefix}"):
        action_cols = st.columns(max(1, len(actions)))
    for action, col in zip(actions, action_cols):
        if action == "suggest":
            col.button(
                "Use Suggested Lineup",
                key=f"{suggest_flag}|btn",
                use_container_width=True,
                type="primary" if answer["primary"] == "suggest" else "secondary",
                help="Fills the board with the Lineup Assistant's recommended starters. Review it, then press Save Lineup.",
                on_click=lambda: session.__setitem__(suggest_flag, True),
            )
        elif action == "waivers":
            col.button("Check Waivers", key=f"u3lu_waivers_{prefix}_{int(selected_week)}_btn", use_container_width=True,
                       type="primary" if answer["primary"] == "waivers" else "secondary",
                       on_click=nav_callback("Waiver Wire / Add-Drop Center"))
        else:
            col.button("Explore Trades", key=f"u3lu_trades_{prefix}_{int(selected_week)}_btn", use_container_width=True,
                       on_click=lambda: session.__setitem__("_lineup_focus_trade_center", True))
    board_payload = build_interactive_board_payload(
        slot_labels,
        assignments,
        team_roster,
        editable=not lineup_locked,
        session=session,
    )
    board_nonce = int(session.get(board_nonce_key, 0))
    component_key = (
        f"{scope.component_key_base}_{board_nonce}"
        if scope
        else f"{prefix}_circle_board_{int(selected_week)}_{board_nonce}"
    )
    board_result = render_interactive_lineup_board(
        st,
        payload=board_payload,
        component_key=component_key,
    )

    selected_player_key = f"{scope.fingerprint}|selected_player" if scope else f"{prefix}_selected_player"
    drop_event = parse_board_drop_result(board_result)
    selected_player = parse_board_player_select(board_result) if lineup_locked else ""
    if selected_player and lineup_locked:
        session[selected_player_key] = selected_player
        scoring_record = get_weekly_scoring_record(context, week=int(selected_week), team=active_team)
        if isinstance(scoring_record, dict) and scoring_record.get("baseline_created_at"):
            render_player_detail_panel(
                st,
                player_name=selected_player,
                scoring_record=scoring_record,
                profile=scoring_profile,
            )
    elif lineup_locked and session.get(selected_player_key):
        scoring_record = get_weekly_scoring_record(context, week=int(selected_week), team=active_team)
        if isinstance(scoring_record, dict) and scoring_record.get("baseline_created_at"):
            render_player_detail_panel(
                st,
                player_name=str(session.get(selected_player_key) or ""),
                scoring_record=scoring_record,
                profile=scoring_profile,
            )

    if drop_event and not lineup_locked:
        write_ok, write_err = _lineup_write_check(scope, proxy_control)
        if not write_ok:
            st.error(write_err)
        else:
            prior_assignments = dict(assignments)
            new_assignments = apply_drop_event(
                assignments,
                slot_keys,
                drop_event,
                roster_df=team_roster,
            )
            if new_assignments is not None and reconcile_editor_assignments(
                session,
                canon_key=canon_key,
                slot_keys=slot_keys,
                new_assignments=new_assignments,
            ):
                save_result = persist_weekly_lineup_draft(
                    session,
                    week=int(selected_week),
                    slots=slots,
                    assignments=new_assignments,
                    my_team=active_team,
                    roster_df=team_roster,
                )
                if not save_result.get("ok"):
                    session[canon_key] = _normalize_assignments(prior_assignments, slot_keys)
                    st.error("; ".join(save_result.get("errors") or ["Could not save lineup draft."]))
                else:
                    slot_map = assignments_to_slot_player_map(slots, new_assignments)
                    readback = get_saved_weekly_lineup(
                        context,
                        int(selected_week),
                        team=active_team,
                        session=session,
                    )
                    readback_map = dict((readback or {}).get("assignments") or {})
                    if readback_map != slot_map:
                        session[canon_key] = _normalize_assignments(prior_assignments, slot_keys)
                        st.error("Draft save did not read back correctly. Restored prior lineup.")
                    else:
                        player = str(drop_event.get("player") or "").strip()
                        target = str(drop_event.get("target") or "").strip()
                        slot_label = "Bench"
                        if target and target != "__bench__":
                            for key, label in slot_keys:
                                if key == target:
                                    slot_label = label
                                    break
                        session["weekly_lineup_drop_flash"] = f"{player} saved to {slot_label}"
                        try:
                            from fantasy_lineup_perf import invalidate_lineup_page_caches

                            invalidate_lineup_page_caches(session)
                        except ImportError:
                            pass
                        session[board_nonce_key] = board_nonce + 1
                        st.rerun()
            elif new_assignments is not None:
                assignments = new_assignments

    validation = _render_open_slots_and_validation(
        st,
        slots=slots,
        slot_labels=slot_labels,
        assignments=assignments,
        team_roster=team_roster,
        on_open_waiver_wire=on_open_waiver_wire if not lineup_locked else None,
        prefix=prefix,
        selected_week=int(selected_week),
    )

    if lineup_locked and ledger_weeks:
        _render_period_finalize(st, session, context, int(selected_week), is_commissioner=is_commissioner, panel=panel)
        return
    if lineup_locked:
        roster_by_team = {active_team: team_roster}
        try:
            from fantasy_league_context import build_roster_stats_from_league_context

            full_roster = build_roster_stats_from_league_context(context)
            if isinstance(full_roster, pd.DataFrame) and not full_roster.empty and "Team" in full_roster.columns:
                for team_name in full_roster["Team"].dropna().astype(str).unique():
                    roster_by_team[str(team_name).strip()] = full_roster[
                        full_roster["Team"].astype(str) == str(team_name)
                    ].copy()
        except Exception:
            pass
        with (panel if panel is not None else nullcontext()):  # commissioner-only; renders nothing for owners
            render_finalize_week_section(
                st,
                session,
                context=context,
                week=int(selected_week),
                roster_by_team=roster_by_team,
                prefix=prefix,
            )
        return

    save_key = f"{scope.fingerprint}|save_btn" if scope else f"{prefix}_save_btn"
    reset_key = f"{scope.fingerprint}|reset_btn" if scope else f"{prefix}_reset_btn"
    with _phone_inline_row(st, "fl-save-reset"):
        save_col, _reset_col = st.columns(2)
    with save_col:
        save_disabled = not validation.get("ok")
        save_error = session.pop(_SAVE_ERROR_KEY, None)
        if save_error:
            st.error(save_error)
        # on_click runs before the next script run starts, so a Save pressed while a
        # board drop is still re-rendering is never lost.
        st.button(
            "Save Lineup",
            key=save_key,
            type="primary",
            disabled=bool(save_disabled),
            on_click=_on_save_lineup_click,
            args=(scope, proxy_control),
            kwargs={
                "week": int(selected_week),
                "slots": list(slots),
                "assignments": dict(assignments),
                "my_team": active_team,
                "roster_df": team_roster,
            },
        )
        if save_disabled:
            st.caption("Complete your lineup before saving.")
    with _reset_col:
        if st.button("Reset", key=reset_key):
            session[canon_key] = _normalize_assignments(saved_assignments, slot_keys)
            session[board_nonce_key] = board_nonce + 1
            st.rerun()
    if ledger_weeks:
        _render_period_finalize(st, session, context, int(selected_week), is_commissioner=is_commissioner, panel=panel)


def _render_period_finalize(st: Any, session: dict[str, Any], context: dict[str, Any], week: int, *,
                            is_commissioner: bool, panel: Any) -> None:
    """Finalize controls go in the Commissioner Tools panel; everyone else still sees that a
    finalized week is final (the same panel function, which shows owners only that line)."""
    from fantasy_season_results_ui import render_period_finalize_panel

    with (panel if (is_commissioner and panel is not None) else nullcontext()):
        render_period_finalize_panel(st, session, context, week, is_commissioner=is_commissioner)
