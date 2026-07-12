"""Streamlit UI for weekly lineup management — circular face-to-circle board."""

from __future__ import annotations

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
    build_team_header_model,
    emit_html_block,
    inject_lineup_board_styles,
    render_team_header_html,
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
    get_saved_weekly_lineup,
    is_lineup_locked,
    list_week_options,
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


def build_open_slot_prompts(
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
) -> list[dict[str, str]]:
    open_slots = [label for label in slot_labels if not str(assignments.get(label.key) or "").strip()]
    if not open_slots:
        return []

    rows: list[dict[str, str]] = []
    of_labels = [label for label in open_slots if label.base_slot == "OF"]
    other_labels = [label for label in open_slots if label.base_slot != "OF"]

    for label in other_labels:
        rows.append(
            {
                "text": f"{label.label} is empty",
                "waiver_label": _waiver_slot_label_for_open_prompt(label),
            }
        )

    if len(of_labels) == 1:
        rows.append({"text": f"{of_labels[0].label} is empty", "waiver_label": "Outfield"})
    elif len(of_labels) > 1:
        rows.append(
            {
                "text": f"{len(of_labels)} Outfield spots are empty",
                "waiver_label": "Outfield",
            }
        )
    return rows


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

    open_rows = build_open_slot_prompts(slot_labels, assignments)
    if open_rows:
        _inject_open_slots_styles(st)
        for idx, row in enumerate(open_rows):
            text_col, btn_col = st.columns([5, 2], gap="small")
            with text_col:
                st.markdown(f"**{row['text']}**")
            with btn_col:
                if on_open_waiver_wire is not None:
                    st.button(
                        "Open Waiver Wire",
                        key=f"{prefix}_waiver_{row['waiver_label']}_{idx}_{int(selected_week)}",
                        on_click=on_open_waiver_wire,
                        args=(row["waiver_label"],),
                    )

    return validation


def render_weekly_lineup_section(
    st: Any,
    session: dict[str, Any],
    *,
    team_roster: pd.DataFrame,
    lineup_team: str,
    on_open_waiver_wire: Callable[[str], None] | None = None,
    scored_roster: pd.DataFrame | None = None,
) -> None:
    """Weekly lineup builder — one circular face-to-circle interaction."""
    del scored_roster

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

    render_edit_lineup_format_action(st, session)
    inject_lineup_board_styles(st)

    slots = resolve_weekly_lineup_slots(context)
    if not slots:
        st.info("League starting positions are not configured yet.")
        return
    slot_labels = build_slot_key_labels(slots)
    slot_keys = slot_key_labels_as_tuples(slot_labels)
    week_options = list_week_options()
    prefix = "weekly_lineup"

    drop_flash = session.pop("weekly_lineup_drop_flash", None)
    if drop_flash:
        st.success(str(drop_flash))

    if session.pop("weekly_lineup_save_flash", None):
        st.success("Lineup saved.")

    if f"{prefix}_selected_week" not in session:
        session[f"{prefix}_selected_week"] = week_options[0]

    week_cols = st.columns([2, 3])
    with week_cols[0]:
        selected_week = st.selectbox(
            "Week",
            week_options,
            format_func=week_label,
            key=f"{prefix}_selected_week",
        )

    scope = resolve_lineup_scope(session, context, week=int(selected_week), page_lineup_team=page_team)
    scope_changed = bool(scope and apply_lineup_scope_change(session, scope))

    saved = get_saved_weekly_lineup(context, int(selected_week), team=active_team, session=session)
    saved_assignments = dict((saved or {}).get("assignments") or {})

    edit_state, edit_message = week_editability_message(context, int(selected_week))
    lineup_locked = is_lineup_locked(context, int(selected_week), team=active_team, session=session)
    if edit_state in ("future", "past"):
        lineup_locked = True
    if edit_message:
        st.info(edit_message)

    scoring_profile = resolve_hitter_scoring_profile(context, session=session)
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

    try:
        from suite_workspace import can_show_developer_tools

        if can_show_developer_tools(st=st):
            with st.expander("Lineup identity diagnostics (Developer Mode)", expanded=False):
                render_lineup_identity_diagnostics_from_session(st, session, scope)
    except ImportError:
        pass

    header_model = build_team_header_model(
        context=context,
        team_name=active_team,
        week=int(selected_week),
        roster_df=team_roster,
        slot_labels=slot_labels,
        assignments=assignments,
        saved=saved,
    )
    emit_html_block(st, render_team_header_html(header_model))

    if lineup_locked:
        st.info(f"Lineup locked for {week_label(int(selected_week))}")
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

    board_payload = build_interactive_board_payload(
        slot_labels,
        assignments,
        team_roster,
        editable=not lineup_locked,
        session=session,
    )
    board_nonce_key = scope.board_nonce_key if scope else f"{prefix}_board_nonce_{int(selected_week)}"
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
        write_ok, write_err = assert_lineup_write_identity(scope)
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
    save_col, _reset_col = st.columns(2)
    with save_col:
        save_disabled = not validation.get("ok")
        if st.button("Save Lineup", key=save_key, type="primary", disabled=bool(save_disabled)):
            write_ok, write_err = assert_lineup_write_identity(scope)
            if not write_ok:
                st.error(write_err)
            else:
                save_result = save_weekly_lineup(
                    session,
                    week=int(selected_week),
                    slots=slots,
                    assignments=assignments,
                    my_team=active_team,
                    roster_df=team_roster,
                )
                if save_result.get("ok"):
                    session["weekly_lineup_save_flash"] = True
                    st.rerun()
                else:
                    st.error("Couldn't save changes. Try again.")
        elif save_disabled:
            st.caption("Complete your lineup before saving.")
    with _reset_col:
        if st.button("Reset", key=reset_key):
            session[canon_key] = _normalize_assignments(saved_assignments, slot_keys)
            session[board_nonce_key] = board_nonce + 1
            st.rerun()
