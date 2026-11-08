"""The Draft Strategy panel at the top of Solo and Live/Shared drafts.

One compact expander with a constant label (PANEL_LABEL) and a one-line status above it
("<strategy> strategy · <mode> queue"). The label never changes, so Streamlit keeps the same
expander when the strategy or mode changes inside it and it stays open (a label that carried the
settings made a new, collapsed expander on every change). Opening or closing it is client-side only,
so the clock, the current selection, the queue and the room are untouched; it can be opened at any
time, including while another manager is picking. Everything in it is this viewer's own
(draft_queue_modes keeps it out of the Shared Draft room).
"""

from __future__ import annotations

import zlib
from typing import Any

import pandas as pd

import draft_queue_modes as dqm

EDIT_RULE = (
    "Edits you make to your queue (add, remove, drag) always change your **Fixed** queue, your plan. "
    "Adaptive never changes it: it re-orders a separate copy for this draft only. Pin a player to keep "
    "him at his Fixed place in Adaptive. Picks are always yours."
)
PANEL_LABEL = "Draft Strategy"
SIMULATOR_PICK_NOTICE = (
    "Nothing here makes a pick: in the Simulator you log every pick yourself. Adaptive only re-orders "
    "your plan."
)


def auto_pick_notice(room: dict[str, Any] | None) -> str:
    """What really happens when a timer runs out (live_draft_autopick: the room's auto-pick rule,
    never a manager's queue)."""
    cfg = (room or {}).get("config") if isinstance((room or {}).get("config"), dict) else {}
    rule = str(cfg.get("auto_pick_rule") or "").strip()
    rule_text = f"this room's auto-pick rule ({rule})" if rule else "this room's auto-pick rule"
    return (f"**Auto Pick doesn't use your queue.** If your timer runs out, {rule_text} picks for you — "
            "not your Fixed queue and not the Adaptive order shown here. Adaptive only re-orders your plan; "
            "it never makes a pick.")


def status_line(session: Any) -> str:
    from draft_strategy_in_draft import LABELS, current_approach

    approach = LABELS.get(current_approach(session), "Balanced").split(" (")[0]
    mode = "Adaptive" if dqm.current_mode(session) == "adaptive" else "Fixed"
    return f"{approach} strategy · {mode} queue"


STRATEGY_PLAN_RULE = (
    "This draft follows a **copy** of your saved strategy: its order is your Fixed plan here, and Adaptive "
    "re-orders a separate copy. Pins and notes you change here stay with this draft until you save them back. "
    "Your saved strategy and your Global Queue are not changed. Picks are always yours."
)


def _plan_options(session: dict[str, Any]) -> dict[str, str]:
    """``{"global": "Global Queue", <id>: <name>}``; strategies only when the store allows access."""
    out = {"global": "Global Queue"}
    try:
        import draft_strategy_store as store

        for s in store.list_strategies(session):
            if isinstance(s, dict) and s.get("id"):
                out[str(s["id"])] = f"♟️ {s.get('name') or 'Strategy'}"
    except Exception:
        pass
    return out


def _choose_plan(session: dict[str, Any], source: str, key: str, flash_key: str) -> None:
    import draft_plan_source as dps
    import draft_strategy_store as store

    try:
        msg = dps.choose(session, source, str(session.get(key) or "global"))
        session[flash_key] = {"kind": "success", "text": msg}
    except store.StrategyError as exc:
        session[flash_key] = {"kind": "warning", "text": str(exc)}


def render_plan_selector(st: Any, session: dict[str, Any], view: dict[str, Any], kp: str) -> None:
    """Starting plan for this draft: the Global Queue or a saved Pro strategy (a per-draft copy)."""
    source = str(view.get("source") or "")
    options = _plan_options(session)
    current = view.get("plan_source") or {"kind": "global"}
    current_id = str(current.get("id") or "global") if current.get("kind") == "strategy" else "global"
    if current_id not in options:  # deleted or renamed elsewhere: keep showing this draft's copy
        options[current_id] = f"♟️ {current.get('name') or 'Strategy'} (this draft's copy)"
    key = f"{kp}_dq_plan_pick"
    if session.get(key) != current_id:
        session[key] = current_id
    flash_key = f"_{kp}_dq_plan_flash"
    st.selectbox("Starting plan for this draft", list(options), format_func=lambda i: options.get(i, i), key=key,
                 disabled=not source or len(options) < 2, on_change=_choose_plan,
                 args=(session, source, key, flash_key),
                 help="Fixed follows this plan's order; Adaptive re-orders a copy of it as players are picked. "
                      "Choosing a strategy never changes it or your Global Queue.")
    flash = session.pop(flash_key, None)
    if isinstance(flash, dict):
        (st.success if flash.get("kind") == "success" else st.warning)(flash.get("text"))


def _add_to_queue(session: dict[str, Any], name: str) -> None:
    import draft_plan_source as dps
    from draft_state import DRAFT_QUEUE_KEY, _normalize_player_list, sync_draft_queue

    source = dqm.draft_source(session)
    if dps.current(session, source) is not None:  # a strategy plan: add to this draft's copy only
        dps.add_player(session, source, name)
        dqm.mark_personal_change(session)
        return

    queue = _normalize_player_list(session.get(DRAFT_QUEUE_KEY))
    if name.lower() not in {q.lower() for q in queue}:
        sync_draft_queue(session, queue + [name], reason="add_to_queue_adaptive_suggestion")


def _save_pins(session: dict[str, Any], key: str, source: str = "") -> None:
    import draft_plan_source as dps

    if source and dps.current(session, source) is not None:
        dps.set_pins(session, source, list(session.get(key) or []))
        dqm.mark_personal_change(session)
        return
    dqm.set_pins(session, list(session.get(key) or []))


def _save_note(session: dict[str, Any], who_key: str, text_key: str, source: str = "") -> None:
    import draft_plan_source as dps

    if source and dps.current(session, source) is not None:
        dps.set_note(session, source, str(session.get(who_key) or ""), str(session.get(text_key) or ""))
        dqm.mark_personal_change(session)
        return
    dqm.set_note(session, str(session.get(who_key) or ""), str(session.get(text_key) or ""))


def _render_compare(st: Any, session: dict[str, Any], view: dict[str, Any], kp: str) -> None:
    rows = dqm.comparison_rows(view)
    if not rows:
        st.caption("Your queue has no available players in this draft. Add players from the cards or the pool.")
    else:
        # Three short columns fit a 390 px phone; the reasons are listed underneath, where they wrap.
        st.dataframe(pd.DataFrame([{k: r[k] for k in ("Fixed Queue", "Adaptive Queue", "Move")} for r in rows]),
                     hide_index=True, width="stretch")
        st.caption("↑ / ↓ marks a move of two or more places from your Fixed queue. "
                   + ("Adaptive is on: this is your working order for this draft."
                      if view["mode"] == "adaptive" else "Fixed is on: the Adaptive column is a preview only."))
        moves = dqm.comparison_moves(view)
        if moves:
            st.markdown("**Why they moved**")
            for m in moves:
                arrow = "↑" if m["direction"] == "up" else "↓"
                st.markdown(f"{arrow} **{m['player']}** · Fixed #{m['fixed']} → Adaptive #{m['adaptive']}  \n"
                            f"{m['reason']}")
    if view.get("drafted_here"):
        st.caption("Drafted in this draft (still in your queue for other drafts): " + ", ".join(view["drafted_here"]))
    if st.checkbox("Show supporting data", key=f"{kp}_dq_show_data"):
        facts = view.get("facts") or {}
        data = [{"Player": f["name"], "Fixed #": f["plan_rank"], "Strategy rank": f.get("strategy_rank"),
                 "Plan": round(f["plan"], 3), "Strategy": round(f["strategy"], 3), "Need": round(f["need"], 3),
                 "Score": round(f["score"], 3)} for f in facts.values()]
        if data:
            st.dataframe(pd.DataFrame(data), hide_index=True, width="stretch")
            w = dqm.WEIGHTS.get(view["approach"], dqm.WEIGHTS["balanced"])
            st.caption(f"Score = {w[0]} × plan + {w[1]} × strategy + {w[2]} × need. A player passes a neighbour only "
                       f"when his score is {dqm.MOVE_MARGIN} higher.")
    if view.get("suggestions"):
        st.markdown("**Worth a look (not in your queue)**")
        for i, s in enumerate(view["suggestions"]):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{s['player']}** ({s['position'] or '—'}) · " + " ".join(s["reasons"]))
            with c2:
                st.button("Add", key=f"{kp}_dq_add_{i}", icon=":material/playlist_add:",
                          help=f"Add {s['player']} to the end of your Fixed queue",
                          on_click=_add_to_queue, args=(session, s["player"]))


def _render_changes(st: Any, session: dict[str, Any], view: dict[str, Any], kp: str) -> None:
    if view["mode"] != "adaptive":
        st.caption("Adaptive is off, so nothing has been changed. Switch to Adaptive to start the history.")
        return
    since_start = st.toggle("Since the draft began", value=False, key=f"{kp}_dq_since_start")
    since = 0 if since_start else int(view.get("reviewed_at") or 0)
    changes = dqm.significant_changes(view, since_pick=since)
    if not changes:
        st.caption("No meaningful changes" + (" since you last reviewed." if since else " yet."))
    for h in changes:
        st.markdown(f"**{h['headline']}**")
        st.markdown("\n".join(f"- {r}" for r in h["reasons"]) or "- Other players moved around him.")
        st.caption(h["alignment"] + f" · after pick {h['pick']}")
    history = view.get("history") or []
    if history:
        st.button("Mark as reviewed", key=f"{kp}_dq_reviewed", icon=":material/done_all:",
                  on_click=dqm.mark_reviewed, args=(session,))
        if st.checkbox(f"Full history ({len(history)} changes)", key=f"{kp}_dq_history"):
            st.dataframe(pd.DataFrame([{"After pick": h["pick"], "Player": h["player"], "From": h["from"], "To": h["to"],
                                        "Trigger": h.get("trigger"), "Follows saved strategy": "yes" if h["follows_strategy"] else "no",
                                        "Why": " ".join(h["reasons"][:2])} for h in reversed(history)]),
                         hide_index=True, width="stretch")


def _render_needs(st: Any, view: dict[str, Any]) -> None:
    needs = view.get("needs") or {}
    if needs.get("points"):
        st.caption(f"{needs.get('format')}: points league, so there are no category needs. Adaptive uses projected "
                   "points value and your open roster slots.")
    elif not needs.get("has_categories"):
        st.caption("This draft's pool has no category projections, so Adaptive uses value, strategy and open slots only.")
    elif needs.get("roster_size") and not needs.get("roster_projected"):
        st.caption("None of your rostered players have projections in this pool, so category needs can't be "
                   "judged yet. Adaptive uses value, strategy and open slots.")
    elif needs.get("weak"):
        st.markdown("**Projected weaknesses:** " + ", ".join(f"{w['label']} ({w['level']})" for w in needs["weak"]))
    elif needs.get("roster_size"):
        st.caption("No category is projected below the league median yet.")
    else:
        st.caption("No players on your roster yet, so there are no category needs.")
    if needs.get("strong"):
        st.markdown("**Projected strengths:** " + ", ".join(needs["strong"]))
    open_slots = needs.get("open_slots") or {}
    if needs.get("slots_assumed"):
        assumed = ", ".join(f"{n} {p}" if int(n) > 1 else p for p, n in (needs.get("slots") or {}).items())
        st.caption("No league roster settings were found for this board, so standard starter slots are assumed"
                   + (f" ({assumed})" if assumed else "") + ". Set an active league to use its real slots.")
    elif needs.get("slots_source"):
        st.caption(f"Open slots use {needs['slots_source']}.")
    if open_slots:
        st.markdown("**Open slots:** " + ", ".join(f"{p} {n}" for p, n in open_slots.items() if n > 0) or "none")


def _render_original(st: Any, session: dict[str, Any], view: dict[str, Any], kp: str) -> None:
    snap = view.get("snapshot") or {}
    players = snap.get("players") or []
    from draft_strategy_in_draft import LABELS

    saved = snap.get("saved_strategy") or {}
    st.caption(f"Saved when this draft started ({snap.get('taken_at', '—')}) · strategy "
               f"{LABELS.get(snap.get('approach'), snap.get('approach') or '—')}"
               + (f" · saved strategy “{saved.get('name')}”" if saved.get("name") else ""))
    if players:
        st.markdown("  \n".join(f"{i}. {p}" for i, p in enumerate(players, start=1)))
    else:
        st.caption("Your queue was empty when this draft started.")
    for line in dqm.research_limitations(session, snap):
        st.caption(line)
    _render_load_saved_plan(st, session, kp)
    if players:
        ok = st.checkbox("Replace my current queue with this original plan", key=f"{kp}_dq_restore_ok")
        if st.button("Restore original plan", key=f"{kp}_dq_restore", icon=":material/restore:", disabled=not ok):
            dqm.restore_snapshot_to_queue(session, confirmed=True)
            st.success("Your Fixed queue is back to the plan you started this draft with.")


def _load_plan(session: dict[str, Any], strategy: dict[str, Any], flash_key: str) -> None:
    """Callback (before the next paint, so the strategy selector may change)."""
    import draft_strategy_store as store
    from draft_strategy_in_draft import APPROACH_KEY, APPROACHES

    try:
        result = store.load_strategy(session, str(strategy.get("id")), confirm_replace=True)
    except store.StrategyError as exc:
        session[flash_key] = {"kind": "warning", "text": str(exc), "notes": []}
        return
    if strategy.get("approach") in APPROACHES:
        session[APPROACH_KEY] = strategy["approach"]
    dqm.mark_personal_change(session)  # the loaded strategy record and approach go with the workspace
    session[flash_key] = {"kind": "success", "notes": list(result.get("warnings") or []),
                          "text": f"Loaded {result.get('loaded', 0)} players from “{strategy.get('name')}” into your Fixed queue."}


def _render_load_saved_plan(st: Any, session: dict[str, Any], kp: str) -> None:
    """Load a saved Draft Strategy's players as the Fixed queue (confirmed). The saved strategy is
    never changed by drafting; this draft's original snapshot stays as it was."""
    flash_key = f"_{kp}_dq_load_flash"
    flash = session.pop(flash_key, None)
    if isinstance(flash, dict):
        (st.success if flash.get("kind") == "success" else st.warning)(flash.get("text"))
        for w in flash.get("notes") or []:
            st.caption(w)
    try:
        import draft_strategy_store as store

        saved = [s for s in store.list_strategies(session) if isinstance(s, dict)]
    except Exception:
        saved = []
    if not saved:
        return
    names = {str(s.get("name") or "Strategy"): s for s in saved}
    pick = st.selectbox("Load a saved plan into my queue", ["—"] + list(names), key=f"{kp}_dq_load_pick")
    if pick == "—":
        return
    ok = st.checkbox(f"Replace my queue with “{pick}”", key=f"{kp}_dq_load_ok")
    st.button("Load plan", key=f"{kp}_dq_load", icon=":material/download:", disabled=not ok,
              on_click=_load_plan, args=(session, names[pick], flash_key))


def _render_pins_notes(st: Any, session: dict[str, Any], view: dict[str, Any], kp: str) -> None:
    import draft_plan_source as dps

    source = str(view.get("source") or "")
    strategy_plan = dps.current(session, source)
    suffix = f"_{strategy_plan['id']}" if strategy_plan else ""
    options = list(view.get("fixed") or [])
    pins_key = f"{kp}_dq_pins{suffix}"
    if strategy_plan:
        current = [p for p in options if p.lower() in set(strategy_plan.get("pins") or [])]
        notes = dict(strategy_plan.get("notes") or {})
        st.caption(f"Pins and notes for this draft's copy of “{strategy_plan.get('name')}”.")
    else:
        current = [p for p in dqm.plan(session)["pins"] if p in options]
        notes = dqm.notes_for(session)
    if pins_key not in session or [p for p in session.get(pins_key) or [] if p not in options]:
        session[pins_key] = current
    st.multiselect("Pinned players (Adaptive keeps them at their Fixed place)", options, key=pins_key,
                   on_change=_save_pins, args=(session, pins_key, source))
    if options:
        who_key = f"{kp}_dq_note_who"
        st.selectbox("Research note for", options, key=who_key)
        who = str(session.get(who_key) or options[0])
        text_key = f"{kp}_dq_note_text_{zlib.crc32(who.lower().encode()):x}{suffix}"  # one box per player
        st.text_input("Note", key=text_key, value=notes.get(who.lower(), ""),
                      help="Shown in that player's explanations. Leave empty to remove.")
        st.button("Save note", key=f"{kp}_dq_note_save", icon=":material/save:",
                  on_click=_save_note, args=(session, who_key, text_key, source))
    if strategy_plan:
        _render_save_back(st, session, source, strategy_plan, kp)


def _save_back(session: dict[str, Any], source: str, flash_key: str) -> None:
    import draft_plan_source as dps
    import draft_strategy_store as store

    try:
        saved = dps.save_back(session, source, confirmed=True)
        session[flash_key] = {"kind": "success", "text": f"Saved this draft's plan back to “{saved['name']}”."}
    except store.StrategyError as exc:
        session[flash_key] = {"kind": "warning", "text": str(exc)}


def _render_save_back(st: Any, session: dict[str, Any], source: str, strategy_plan: dict[str, Any], kp: str) -> None:
    flash_key = f"_{kp}_dq_saveback_flash"
    flash = session.pop(flash_key, None)
    if isinstance(flash, dict):
        (st.success if flash.get("kind") == "success" else st.warning)(flash.get("text"))
    name = strategy_plan.get("name") or "the strategy"
    st.caption("Changes here stay with this draft."
               + (" This draft's copy has changes." if strategy_plan.get("edited") else ""))
    ok = st.checkbox(f"Update my saved strategy “{name}” with this draft's order, pins and notes",
                     key=f"{kp}_dq_saveback_ok")
    st.button(f"Save back to “{name}”", key=f"{kp}_dq_saveback", icon="💾", disabled=not ok,
              on_click=_save_back, args=(session, source, flash_key))


def render_draft_strategy_panel(st: Any, session: dict[str, Any], room: dict[str, Any] | None, *,
                                viewer_team: str, key_prefix: str = "ldr", source: str | None = None,
                                cards: bool = True) -> dict[str, Any]:
    """The panel; returns the adaptive view (for the caller and tests).

    Solo and Live/Shared pass the room (cards=True). The Draft Room Simulator passes
    draft_queue_modes.simulator_room(...) with its own ``source`` and cards=False: same engine,
    no recommendation cards, no clock."""
    from draft_strategy_in_draft import render_strategy_selector

    if session.get(dqm.MODE_KEY) not in dqm.MODES:
        session[dqm.MODE_KEY] = "fixed"
    # Widget values are already in the session at the start of the run, so one refresh is enough.
    view = dqm.refresh(session, room, viewer_team, source=source)
    plan_src = view.get("plan_source") or {}
    plan_txt = f" · following **{plan_src.get('name')}**" if plan_src.get("kind") == "strategy" else ""
    st.caption(f"Your draft plan: **{status_line(session)}**{plan_txt}")
    # A key gives the expander a block id from the key alone (Streamlit 1.59), so it is the same
    # expander whatever moves above it: it stays open when a change inside it reruns the page.
    with st.expander(PANEL_LABEL, icon=":material/psychology:", expanded=False, key=f"{key_prefix}_dq_panel"):
        render_plan_selector(st, session, view, key_prefix)
        render_strategy_selector(st, session, key_prefix=key_prefix, cards=cards)
        st.radio("Draft Queue mode", list(dqm.MODES), format_func=lambda m: dqm.MODE_LABELS[m],
                 key=dqm.MODE_KEY, horizontal=True, on_change=dqm.mark_personal_change, args=(session,))
        is_strategy = (view.get("plan_source") or {}).get("kind") == "strategy"
        st.caption(STRATEGY_PLAN_RULE if is_strategy else EDIT_RULE)
        if not cards:
            st.caption(SIMULATOR_PICK_NOTICE)
        elif dqm.current_mode(session) == "adaptive":
            st.info(auto_pick_notice(room), icon=":material/bolt:")
        else:
            st.caption(auto_pick_notice(room).replace("**", ""))
        compare, changes, needs, original, pins = st.tabs(
            ["Fixed vs Adaptive", "What changed and why?", "Team needs", "Original plan", "Pins & notes"])
        with compare:
            _render_compare(st, session, view, key_prefix)
        with changes:
            _render_changes(st, session, view, key_prefix)
        with needs:
            _render_needs(st, view)
        with original:
            _render_original(st, session, view, key_prefix)
        with pins:
            _render_pins_notes(st, session, view, key_prefix)
    return view
