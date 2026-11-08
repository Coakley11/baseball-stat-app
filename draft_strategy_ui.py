"""Draft Strategy Assistant page: the working queue and the saved strategy library (Pro).

Everything here goes through draft_strategy_store, which checks sign-in and the
``draft_strategy_library`` capability itself, so this page never decides access on its own. The
draft settings shown are the canonical ones (League setup in Draft Room Simulator, projection
settings): this page reads them and links there instead of keeping its own copies.
"""

from __future__ import annotations

import action_icons as _icons

import time
from typing import Any

import draft_strategy_store as store

PAGE = "Draft Strategy Assistant"
ICON = "♟️"
APPROACH_LABELS = {
    "balanced": "Balanced (recommended)",
    "best_available": "Best player available",
    "value_based": "Value-based (value vs. draft cost)",
    "positional_scarcity": "Positional scarcity",
    "roster_aware": "Roster-aware (fill your needs)",
}
APPROACH_KEY = "draft_strategy_approach"
# Which saved strategy the working queue was last loaded from, and what it held then. The
# working queue and the saved snapshot are different things: this only says where the queue
# came from and whether it has been edited since.
LOADED_KEY = "_draft_strategy_loaded"
_SETTING_LABELS = (
    ("room_team_count", "Teams"),
    ("room_rounds", "Rounds"),
    ("room_format", "Scoring format"),
    ("room_window", "Projection window"),
    ("fantasy_draft_projection_style", "Projection style"),
)

# Messages to show on the next run, kept per browser session outside st.session_state (the
# same reason as ui_confirm: keys set by a callback did not reliably survive to render).
_FLASH: dict[str, tuple[str, str, float]] = {}


def _sid(st: Any) -> str:
    from ui_confirm import _session_id

    return _session_id(st)


def _flash(st: Any, level: str, text: str) -> None:
    if len(_FLASH) > 500:
        _FLASH.pop(next(iter(_FLASH)))
    _FLASH[_sid(st)] = (level, text, time.time())


def _show_flash(st: Any) -> None:
    item = _FLASH.pop(_sid(st), None)
    if item and time.time() - item[2] < 120:
        getattr(st, item[0], st.info)(item[1])


def _run(st: Any, fn, *args, ok: str = "", **kwargs) -> Any:
    try:
        out = fn(*args, **kwargs)
    except store.StrategyError as exc:
        _flash(st, "error", str(exc))
        return None
    if ok:
        _flash(st, "success", ok)
    return out


def _persist(st: Any) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="draft_strategy_queue_loaded")
    except Exception:
        pass


def _access(st: Any, session: dict[str, Any]) -> tuple[bool, str, bool]:
    """(can_use, reason, is_pro) — the same checks the store applies."""
    import baseball_monetization as bm
    from baseball_monetization_ui import current_entitlement

    snapshot = current_entitlement(session)
    try:
        from suite_auth import is_anonymous_guest

        if is_anonymous_guest(session):
            return False, "Sign in to save and load draft strategies.", False
    except ImportError:
        pass
    if not bm.entitlement_for_capability(snapshot, store.CAPABILITY):
        return False, "Saved Draft Strategies are a Pro feature.", bool(snapshot.grants_pro)
    return True, "", bool(snapshot.grants_pro)


def _render_settings(st: Any, session: dict[str, Any]) -> None:
    ctx = store.current_draft_context(session)
    with st.container(border=True):
        st.markdown("**Your draft settings**")
        rows = [f"- **{label}:** {ctx[key]}" for key, label in _SETTING_LABELS if ctx.get(key) not in (None, "")]
        st.markdown("\n".join(rows) if rows else "No draft settings yet.")
        st.caption("These come from **Draft Room Simulator → League setup** and your projection settings; "
                   "change them there. Saved strategies remember the settings they were built with.")
        current = session.get(APPROACH_KEY) if session.get(APPROACH_KEY) in store.APPROACHES else "balanced"
        st.selectbox(
            "Preferred approach",
            list(store.APPROACHES),
            index=list(store.APPROACHES).index(current),
            format_func=lambda v: APPROACH_LABELS.get(v, v),
            key=APPROACH_KEY,
            on_change=_approach_changed,
            args=(session,),
            help="Saved with each new strategy so you remember how it was built.",
        )


def _approach_changed(session: dict[str, Any]) -> None:
    from draft_strategy_in_draft import strategy_changed

    strategy_changed(session)


def loaded_strategy_state(session: dict[str, Any], queue: list[str]) -> dict[str, Any] | None:
    """``{"name", "id", "modified"}`` when the working queue came from a saved strategy."""
    loaded = session.get(LOADED_KEY)
    if not isinstance(loaded, dict) or not loaded.get("id"):
        return None
    return {**loaded, "modified": [q.lower() for q in queue] != [q.lower() for q in loaded.get("queue") or []]}


def _queue_action(st: Any, session: dict[str, Any], fn, *args) -> None:
    fn(session, *args)
    _persist(st)
    st.rerun()


def _render_queue(st: Any, session: dict[str, Any], *, drafted: set[str] | None = None,
                  backups: dict[str, list[str]] | None = None) -> list[str]:
    from draft_state import (
        move_queue_item_down,
        move_queue_item_to_top,
        move_queue_item_up,
        remove_player_from_user_draft_queue,
    )

    queue = store._queue(session)
    meta = session.get("_queue_player_meta") if isinstance(session.get("_queue_player_meta"), dict) else {}
    # Marks come from the active draft only (draft_queue_contract), never from a finished
    # Simulator board or the planning context's league rosters.
    try:
        from draft_queue_contract import draft_status_label, queue_draft_status

        draft_marks = queue_draft_status(session, queue)
    except ImportError:
        draft_marks = {}
    with st.container(border=True):
        st.markdown(f"**Working queue** · {len(queue)} player{'s' if len(queue) != 1 else ''}")
        loaded = loaded_strategy_state(session, queue)
        if loaded:
            st.caption(f"Loaded from **{loaded['name']}**" + (
                " · edited since loading (the saved strategy is unchanged)" if loaded["modified"] else " · unchanged"))
        if not queue:
            st.caption("Your queue is empty. Add players with **⭐ Add to Queue** from the recommendations below, "
                       "the research pages or Draft Assistant, or load a saved strategy.")
        for i, name in enumerate(queue):
            pos = str((meta.get(name.lower()) or {}).get("position") or "").strip()
            label = f"**{i + 1}. {name}**" + (f" · {pos}" if pos and pos != "—" else "")
            info = draft_marks.get(name.lower())
            if info:
                label += f" · ✓ {draft_status_label(info)}"
            alts = (backups or {}).get(name)
            if alts:
                label += f"  \nIf taken: {', '.join(alts)}"
            name_col, up_col, down_col, top_col, rm_col = st.columns([6, 1, 1, 1, 1])
            name_col.markdown(label)
            if up_col.button("", key=f"dsq_up_{i}_btn", icon=_icons.MOVE_UP, help="Move up",
                             disabled=i == 0, use_container_width=True):
                _queue_action(st, session, move_queue_item_up, i)
            if down_col.button("", key=f"dsq_down_{i}_btn", icon=_icons.MOVE_DOWN, help="Move down",
                               disabled=i == len(queue) - 1, use_container_width=True):
                _queue_action(st, session, move_queue_item_down, i)
            if top_col.button("", key=f"dsq_top_{i}_btn", icon=_icons.MOVE_TOP, help="Move to top",
                              disabled=i == 0, use_container_width=True):
                _queue_action(st, session, move_queue_item_to_top, i)
            if rm_col.button("", key=f"dsq_rm_{i}_btn", icon=_icons.REMOVE_FROM_LIST,
                             help="Remove from the working queue (saved strategies are not changed)",
                             use_container_width=True):
                _queue_action(st, session, remove_player_from_user_draft_queue, name)
        st.caption("A player drafted in a draft is marked there and stays in this queue for your other "
                   "drafts; drafting never changes a saved strategy.")
    return queue


def _queue_notes(session: dict[str, Any]) -> dict[str, str]:
    """The user's research notes for queued players (Pins & notes, and a loaded strategy's notes)."""
    try:
        from draft_queue_modes import notes_for

        return notes_for(session)
    except Exception:
        return {}


def _render_save(st: Any, session: dict[str, Any], queue: list[str]) -> None:
    with st.container(border=True):
        st.markdown("**Save this queue as a strategy**")
        name = st.text_input("Strategy name", key="draft_strategy_new_name", max_chars=store.NAME_MAX,
                             placeholder="e.g. 12-team points, early pitching")
        if st.button("Save strategy", key="draft_strategy_save_btn", type="primary", icon=_icons.SAVE,
                     disabled=not queue, use_container_width=True):
            saved = _run(st, store.save_strategy, session, name,
                         approach=str(session.get(APPROACH_KEY) or "balanced"), notes=_queue_notes(session))
            if saved:
                _flash(st, "success", f"Saved **{saved['name']}** ({len(saved['players'])} players).")
            st.rerun()


def _load(st: Any, session: dict[str, Any], sid: str) -> None:
    # The store records the loaded strategy (LOADED_KEY) itself: id, name, approach, notes and the
    # queue as loaded. Overwriting it here used to drop the notes and approach.
    out = _run(st, store.load_strategy, session, sid, confirm_replace=True)
    if out:
        _persist(st)
        msg = f"Loaded {out['loaded']} players into your queue."
        for warning in out.get("warnings") or []:
            msg += f"\n\n{warning}"
        _flash(st, "success", msg)


def _render_strategy(st: Any, session: dict[str, Any], strategy: dict[str, Any], queue: list[str]) -> None:
    from ui_confirm import ICON_DELETE, confirm_destructive_action

    sid = str(strategy["id"])
    players = sorted(strategy.get("players") or [], key=lambda p: int(p.get("rank") or 0))
    with st.container(border=True):
        st.markdown(f"**{strategy['name']}**")
        st.caption(f"{APPROACH_LABELS.get(strategy.get('approach'), 'Balanced')} · {len(players)} players · "
                   f"updated {str(strategy.get('updated_at') or '')[:10]}")
        if players:
            st.markdown(" · ".join(p["name"] for p in players[:6]) + (" …" if len(players) > 6 else ""))
        load_col, update_col = st.columns(2)
        with load_col:
            if not queue:
                if st.button("Load into queue", key=f"strategy_{sid}_load_btn", icon=_icons.OPEN,
                             use_container_width=True):
                    _load(st, session, sid)
                    st.rerun()
            elif confirm_destructive_action(
                st,
                key=f"strategy_{sid}_load_btn",
                label="Load into queue",
                icon=_icons.OPEN,
                use_container_width=True,
                warning=(f"Loading this strategy will replace your current {len(queue)}-player queue with the "
                         f"{len(players)} players in {strategy['name']}. Continue?"),
                confirm_label="Replace queue",
                target=sid,
            ):
                _load(st, session, sid)
                st.rerun()
        with update_col:
            if confirm_destructive_action(
                st,
                key=f"strategy_{sid}_update_btn",
                label="Update from queue",
                icon=_icons.REFRESH,
                use_container_width=True,
                warning=f"Replace the {len(players)} players saved in {strategy['name']} with your current "
                        f"{len(queue)}-player queue?",
                confirm_label="Update strategy",
                target=sid,
            ):
                updated = _run(st, store.update_strategy, session, sid, confirm_overwrite=True,
                               notes=_queue_notes(session), ok=f"Updated **{strategy['name']}** from your queue.")
                if updated:
                    session[LOADED_KEY] = store.loaded_record(updated, store._queue(session))
                st.rerun()
        with st.expander("Rename, duplicate or delete", icon=_icons.EDIT):
            new_name = st.text_input("New name", value=strategy["name"], key=f"strategy_{sid}_rename_input",
                                     max_chars=store.NAME_MAX)
            ren_col, dup_col = st.columns(2)
            with ren_col:
                if st.button("Rename", key=f"strategy_{sid}_rename_btn", icon=_icons.EDIT,
                             use_container_width=True):
                    renamed = _run(st, store.rename_strategy, session, sid, new_name, ok="Renamed.")
                    loaded = session.get(LOADED_KEY)
                    if renamed and isinstance(loaded, dict) and loaded.get("id") == sid:
                        session[LOADED_KEY] = {**loaded, "name": renamed["name"]}
                    st.rerun()
            with dup_col:
                if st.button("Duplicate", key=f"strategy_{sid}_dup_btn", icon=_icons.DUPLICATE,
                             use_container_width=True):
                    _run(st, store.duplicate_strategy, session, sid, ok=f"Duplicated **{strategy['name']}**.")
                    st.rerun()
            if confirm_destructive_action(
                st,
                key=f"strategy_{sid}_delete_btn",
                label="Delete strategy",
                icon=ICON_DELETE,
                use_container_width=True,
                warning=f"Permanently delete {strategy['name']}? Your current queue is not changed.",
                confirm_label="Delete",
                target=sid,
            ):
                _run(st, store.delete_strategy, session, sid, confirmed=True, ok=f"Deleted **{strategy['name']}**.")
                loaded = session.get(LOADED_KEY)
                if isinstance(loaded, dict) and loaded.get("id") == sid:
                    session.pop(LOADED_KEY, None)
                st.rerun()


def _add_to_queue(st: Any, session: dict[str, Any], name: str, position: str = "", team: str = "") -> None:
    from draft_state import add_player_to_draft_queue

    _q, added = add_player_to_draft_queue(session, name)
    if added:
        try:
            from draft_ui import cache_queue_player_meta

            cache_queue_player_meta(session, name, {"position": position or "—", "team": team or "—"})
        except Exception:
            pass
        _persist(st)
        _flash(st, "success", f"⭐ Added **{name}** to your working queue.")
    else:
        _flash(st, "info", f"**{name}** is already in your working queue.")
    st.rerun()


def _render_plan(st: Any, session: dict[str, Any], pool_fn) -> dict[str, Any]:
    """Team needs, positional depth and explained targets. Returns what the queue panel reuses."""
    import draft_strategy_plan as plan

    out: dict[str, Any] = {"drafted": set(), "backups": {}}
    try:
        pool = pool_fn() if pool_fn is not None else None
    except Exception as exc:  # the plan is advice; the rest of the page must keep working
        st.warning(f"Recommendations are unavailable right now ({type(exc).__name__}).")
        return out
    profile = plan.team_profile(session, pool)
    available = plan.available_pool(session, pool, profile)
    queue = store._queue(session)
    out["drafted"] = {n.lower() for n in profile["drafted"]}
    out["backups"] = plan.backups_for_queue(available, queue)

    with st.container(border=True):
        st.markdown("**Your team and needs**")
        team = profile["team"] or "No team selected"
        st.markdown(f"Team **{team}** · {profile['fantasy_format']} · {len(profile['roster'])} drafted so far")
        if profile["roster"]:
            st.caption("Roster: " + ", ".join(profile["roster"][:15]))
        needs = profile["position_needs"]
        st.markdown("**Open positions:** " + (", ".join(needs) if needs else "none required yet"))
        if profile["category_needs"]:
            st.markdown("**Weak categories:** " + ", ".join(
                f"{c['label']} ({c['level'].lower()})" for c in profile["category_needs"]))
        if profile["strengths"] and profile["roster"]:
            st.markdown("**Strengths:** " + ", ".join(profile["strengths"]))
        if not profile["roster"]:
            st.caption("Category strengths and weaknesses appear once your team has drafted players "
                       "(Draft Room Simulator or Live Draft Room).")

    depth = plan.positional_depth(available)
    if depth:
        with st.expander("Positional depth: how many strong players are left at each position", expanded=False):
            st.dataframe(
                [{"Position": d["position"], "Top-150 players left": d["startable_left"],
                  "Best available": d["best_available"]} for d in depth],
                hide_index=True, use_container_width=True,
            )
            st.caption("Thin positions are worth addressing earlier; deep ones can wait.")

    with st.container(border=True):
        st.markdown("**Recommended targets**")
        positions = ["All positions"] + list(plan.DEPTH_POSITIONS)
        default_pos = needs[0] if needs and needs[0] in positions else "All positions"
        choice = st.selectbox("Position", positions, index=positions.index(default_pos), key="draft_strategy_target_pos")
        targets = plan.recommended_targets(session, available, profile, queue=queue,
                                           position="" if choice == "All positions" else choice, limit=8)
        if not targets:
            st.caption("No recommendations: the projection pool is empty or every remaining player is queued.")
        for t in targets:
            info_col, add_col = st.columns([5, 2])
            bits = [t["position"]]
            if t["adp"] is not None:
                bits.append(f"ADP {t['adp']:.0f}")
            if t["fills_need"]:
                bits.append("fills a need")
            info_col.markdown(f"**{t['rank']}. {t['name']}** · " + " · ".join(bits)
                              + (f"  \n{t['reason']}" if t["reason"] else ""))
            if add_col.button("Add to Queue", key=f"dsq_add_{t['name']}_btn", icon=_icons.ADD_TO_QUEUE, use_container_width=True):
                _add_to_queue(st, session, t["name"], t["position"], t["team"])
        st.caption("Ranked by the same Decision Score as Draft Assistant, for your team and scoring format. "
                   "Nothing is added to your queue unless you choose it.")
    return out


def render_draft_strategy_page(st: Any, session: dict[str, Any], *, pool_fn=None) -> None:
    """``pool_fn`` returns the canonical projection pool scored for the active team (optional)."""
    can_use, reason, is_pro = _access(st, session)
    if is_pro:
        st.caption("♟️ **PRO** · included in your plan")
    elif can_use:
        st.caption("♟️ **PRO** feature · open to everyone while billing is in preview")
    else:
        st.caption("♟️ **PRO** feature")
    _show_flash(st)
    _render_settings(st, session)
    plan_state = _render_plan(st, session, pool_fn) if pool_fn is not None else {}
    queue = _render_queue(st, session, drafted=plan_state.get("drafted"), backups=plan_state.get("backups"))
    if not can_use:
        with st.container(border=True):
            st.markdown("**Saved strategies**")
            st.info(reason)
            if "Pro" in reason and st.button("View Pricing & Upgrade", key="draft_strategy_pricing_btn",
                                             type="primary", use_container_width=True):
                from baseball_monetization_ui import PRICING_PAGE, schedule_page

                schedule_page(session, PRICING_PAGE)
                st.rerun()
        return
    _render_save(st, session, queue)
    st.markdown("#### Saved strategies")
    strategies = _run(st, store.list_strategies, session)
    if strategies is None:
        _show_flash(st)
        return
    if not strategies:
        st.caption("No saved strategies yet. Build a queue, name it above and save it.")
        return
    for strategy in strategies:
        _render_strategy(st, session, strategy, queue)
