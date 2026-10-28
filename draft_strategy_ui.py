"""Draft Strategy Assistant page: the working queue and the saved strategy library (Pro).

Everything here goes through draft_strategy_store, which checks sign-in and the
``draft_strategy_library`` capability itself, so this page never decides access on its own. The
draft settings shown are the canonical ones (League setup in Draft Room Simulator, projection
settings): this page reads them and links there instead of keeping its own copies.
"""

from __future__ import annotations

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
            help="Saved with each new strategy so you remember how it was built.",
        )


def _render_queue(st: Any, session: dict[str, Any]) -> list[str]:
    queue = store._queue(session)
    meta = session.get("_queue_player_meta") if isinstance(session.get("_queue_player_meta"), dict) else {}
    with st.container(border=True):
        st.markdown(f"**Current queue** · {len(queue)} player{'s' if len(queue) != 1 else ''}")
        if not queue:
            st.caption("Your queue is empty. Add players with **⭐ Add to Queue** in Draft Assistant, "
                       "or load a saved strategy below.")
        else:
            lines = []
            for i, name in enumerate(queue[:30], start=1):
                pos = str((meta.get(name.lower()) or {}).get("position") or "").strip()
                lines.append(f"{i}. {name}" + (f" · {pos}" if pos and pos != "—" else ""))
            st.markdown("\n".join(lines))
            if len(queue) > 30:
                st.caption(f"…and {len(queue) - 30} more.")
        st.caption("Drafting takes players off this queue; it never changes a saved strategy.")
    return queue


def _render_save(st: Any, session: dict[str, Any], queue: list[str]) -> None:
    with st.container(border=True):
        st.markdown("**Save this queue as a strategy**")
        name = st.text_input("Strategy name", key="draft_strategy_new_name", max_chars=store.NAME_MAX,
                             placeholder="e.g. 12-team points, early pitching")
        if st.button("Save strategy", key="draft_strategy_save_btn", type="primary", icon=":material/save:",
                     disabled=not queue, use_container_width=True):
            saved = _run(st, store.save_strategy, session, name,
                         approach=str(session.get(APPROACH_KEY) or "balanced"))
            if saved:
                _flash(st, "success", f"Saved **{saved['name']}** ({len(saved['players'])} players).")
            st.rerun()


def _load(st: Any, session: dict[str, Any], sid: str) -> None:
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
                if st.button("Load into queue", key=f"strategy_{sid}_load_btn", icon=":material/playlist_add:",
                             use_container_width=True):
                    _load(st, session, sid)
                    st.rerun()
            elif confirm_destructive_action(
                st,
                key=f"strategy_{sid}_load_btn",
                label="Load into queue",
                icon=":material/playlist_add:",
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
                icon=":material/sync:",
                use_container_width=True,
                warning=f"Replace the {len(players)} players saved in {strategy['name']} with your current "
                        f"{len(queue)}-player queue?",
                confirm_label="Update strategy",
                target=sid,
            ):
                _run(st, store.update_strategy, session, sid, confirm_overwrite=True,
                     ok=f"Updated **{strategy['name']}** from your queue.")
                st.rerun()
        with st.expander("Rename, duplicate or delete"):
            new_name = st.text_input("New name", value=strategy["name"], key=f"strategy_{sid}_rename_input",
                                     max_chars=store.NAME_MAX)
            ren_col, dup_col = st.columns(2)
            with ren_col:
                if st.button("Rename", key=f"strategy_{sid}_rename_btn", icon=":material/edit:",
                             use_container_width=True):
                    _run(st, store.rename_strategy, session, sid, new_name, ok="Renamed.")
                    st.rerun()
            with dup_col:
                if st.button("Duplicate", key=f"strategy_{sid}_dup_btn", icon=":material/content_copy:",
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
                st.rerun()


def render_draft_strategy_page(st: Any, session: dict[str, Any]) -> None:
    can_use, reason, is_pro = _access(st, session)
    if is_pro:
        st.caption("♟️ **PRO** · included in your plan")
    elif can_use:
        st.caption("♟️ **PRO** feature · open to everyone while billing is in preview")
    else:
        st.caption("♟️ **PRO** feature")
    _show_flash(st)
    _render_settings(st, session)
    queue = _render_queue(st, session)
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
