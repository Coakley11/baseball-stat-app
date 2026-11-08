"""Pro Draft Strategies on the Draft Strategy page (S2): several named strategies, each with its own
queue, notes, research and ranking preferences, edited as working copies (draft_strategy_work).

Editing a strategy never changes another strategy or the Global Queue. The only links between the
Global Queue and a strategy are the two explicit, confirmed transfers in the "Global Queue" tab.
Access is the store's (sign-in + the ``draft_strategy_library`` capability); the caller only
renders this when draft_strategy_ui._access allows it.
"""

from __future__ import annotations

import action_icons as _icons

from typing import Any

import draft_strategy_store as store
import draft_strategy_v2 as v2
import draft_strategy_work as work

APPROACH_LABELS = {
    "balanced": "Balanced (recommended)",
    "best_available": "Best player available",
    "value_based": "Value-based (value vs. draft cost)",
    "positional_scarcity": "Positional scarcity",
    "roster_aware": "Roster-aware (fill your needs)",
}
CATEGORY_CHOICES = ("HR", "R", "RBI", "SB", "AVG", "OBP", "W", "SV", "K", "ERA", "WHIP", "QS")
NEW_NAME_KEY = "draft_strategy_new_name"
_NEW_SENTINEL = "__new__"
_PICK_KEY = "_draft_strategy_open_pick"
_NEXT_PICK_KEY = "_draft_strategy_open_next"  # set by a button, applied before the selector is drawn


def _flash(st: Any, level: str, text: str) -> None:
    from draft_strategy_ui import _flash as flash

    flash(st, level, text)


def _try(st: Any, fn, *args, ok: str = "", **kwargs) -> Any:
    try:
        out = fn(*args, **kwargs)
    except store.StrategyError as exc:
        _flash(st, "error", str(exc))
        return None
    if ok:
        _flash(st, "success", ok)
    return out


def _save_global(st: Any) -> None:
    """The Global Queue changed by an explicit transfer: save the workspace now (a user edit)."""
    try:
        from draft_queue_modes import flush_personal_changes, mark_personal_change

        mark_personal_change(st.session_state)
        flush_personal_changes(st)
    except Exception:
        pass


def _plural(n: int, word: str = "player") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _pool_names(pool: Any, exclude: set[str]) -> list[str]:
    try:
        col = next(c for c in ("fullName", "Player", "Name") if c in pool.columns)
    except Exception:
        return []
    names = [str(n) for n in pool[col].dropna().tolist() if str(n).strip()]
    return [n for n in dict.fromkeys(names) if v2.player_key(n) not in exclude][:400]


def _pool_row(pool: Any, name: str) -> dict[str, Any]:
    try:
        col = next(c for c in ("fullName", "Player", "Name") if c in pool.columns)
        rows = pool[pool[col].astype(str).str.strip().str.lower() == name.strip().lower()]
        if len(rows) == 1:
            r = rows.iloc[0]
            pos = next((str(r[c]) for c in ("Primary Position", "Position", "Pos") if c in rows.columns and str(r[c]) not in ("", "nan")), "")
            team = next((str(r[c]) for c in ("Team", "MLB Team") if c in rows.columns and str(r[c]) not in ("", "nan")), "")
            return {"position": pos, "team": team}
    except Exception:
        pass
    return {}


# --- create and choose -----------------------------------------------------------------------


def _render_create(st: Any, session: dict[str, Any], pool: Any) -> None:
    gq = store._queue(session)
    with st.container(border=True):
        st.markdown("**➕ New Pro strategy**")
        name = st.text_input("Strategy name", key=NEW_NAME_KEY, max_chars=store.NAME_MAX,
                             placeholder="e.g. 12-team points, power first")
        start = st.radio("Start from", ["empty", "global"], horizontal=True, key="draft_strategy_new_from",
                         format_func=lambda v: "An empty queue" if v == "empty"
                         else f"A copy of my Global Queue ({_plural(len(gq))})")
        if st.button("Create strategy", key="draft_strategy_create_btn", type="primary", icon=_icons.START,
                     use_container_width=True):
            rec = _try(st, work.create, session, name, approach=str(session.get("draft_strategy_approach") or "balanced"),
                       from_global=start == "global", pool=pool)
            if rec:
                saved = _try(st, work.save, session, rec["strategy"]["id"])
                if saved:
                    session[_NEXT_PICK_KEY] = saved["id"]
                    _flash(st, "success", f"Created **{saved['name']}** ({_plural(len(saved['queue']))}). "
                                          "Your Global Queue was not changed.")
                else:
                    work.discard(session, rec["strategy"]["id"])
            st.rerun()


def _choose(session: dict[str, Any]) -> None:
    sid = str(session.get(_PICK_KEY) or "")
    if sid and sid != _NEW_SENTINEL:
        session[work.OPEN_KEY] = sid


def _render_chooser(st: Any, session: dict[str, Any], saved: list[dict[str, Any]]) -> str | None:
    ids = [s["id"] for s in saved]
    names = {s["id"]: s["name"] for s in saved}
    dirty = set(work.dirty_ids(session))
    if not ids:
        st.caption("No saved strategies yet. Create one above: start empty or from a copy of your Global Queue.")
        return None
    nxt = session.pop(_NEXT_PICK_KEY, None)
    if nxt in ids:
        session[work.OPEN_KEY] = nxt
        session[_PICK_KEY] = nxt
    open_id = session.get(work.OPEN_KEY)
    if open_id not in ids:
        open_id = ids[0]
        session[work.OPEN_KEY] = open_id
    if session.get(_PICK_KEY) not in ids:
        session[_PICK_KEY] = open_id
    st.selectbox("Open strategy", ids, key=_PICK_KEY, on_change=_choose, args=(session,),
                 format_func=lambda i: names.get(i, i) + ("  •  unsaved changes" if i in dirty else ""),
                 help="Switching keeps unsaved changes in the strategy you leave; they stay marked until you "
                      "save or discard them.")
    session[work.OPEN_KEY] = session.get(_PICK_KEY) or open_id
    if dirty - {session[work.OPEN_KEY]}:
        others = ", ".join(names.get(i, i) for i in dirty if i != session[work.OPEN_KEY])
        st.caption(f"Unsaved changes also in: {others}.")
    return str(session[work.OPEN_KEY])


# --- the editor --------------------------------------------------------------------------------


def _render_header(st: Any, session: dict[str, Any], rec: dict[str, Any]) -> None:
    s = rec["strategy"]
    sid = s["id"]
    st.markdown(f"### ♟️ {s['name']}")
    st.caption(f"{APPROACH_LABELS.get(s['approach'], 'Balanced')} · {_plural(len(s['queue']))} · "
               f"{_plural(len(s['pins']), 'pin')} · {_plural(len(s['notes']), 'note')} · "
               f"saved {str(rec.get('base_updated_at') or s.get('updated_at') or '')[:16].replace('T', ' ')}")
    save_col, discard_col = st.columns(2)
    if rec.get("dirty"):
        st.warning("Unsaved changes in this strategy. Save to keep them; other strategies and your Global "
                   "Queue are not affected.", icon=_icons.EDIT)
    else:
        st.caption("✅ All changes saved.")
    if save_col.button("Save strategy", key=f"dsp_{sid}_save_btn", type="primary", icon=_icons.SAVE,
                       disabled=not rec.get("dirty"), use_container_width=True):
        saved = _try(st, work.save, session, sid)
        if saved:
            _flash(st, "success", f"Saved **{saved['name']}**.")
        st.rerun()
    if discard_col.button("Discard changes", key=f"dsp_{sid}_discard_btn", icon=_icons.UNDO,
                          disabled=not rec.get("dirty"), use_container_width=True):
        work.discard(session, sid)
        _flash(st, "info", "Unsaved changes discarded.")
        st.rerun()


def _edit(st: Any, session: dict[str, Any], sid: str, op, *args, **kwargs) -> None:
    _try(st, work.edit, session, sid, op, *args, **kwargs)
    st.rerun()


def _render_queue_tab(st: Any, session: dict[str, Any], rec: dict[str, Any], pool: Any) -> None:
    s = rec["strategy"]
    sid = s["id"]
    queue = s["queue"]
    pins = set(s["pins"])
    if not queue:
        st.caption("This strategy's queue is empty. Add players below or copy your Global Queue in "
                   "(Global Queue tab).")
    for i, e in enumerate(queue):
        key = v2.player_key(e["name"])
        note = v2.note_for(s, e["name"], e.get("mlbam_id"))
        bits = [b for b in (e.get("position"), e.get("team")) if b]
        label = f"**{i + 1}. {e['name']}**" + (f" · {' · '.join(bits)}" if bits else "")
        if key in pins:
            label += " · 📌 pinned"
        if e.get("id_status") == v2.ID_AMBIGUOUS:
            label += " · ⚠️ more than one player has this name"
        if note:
            label += f"  \n📝 {note['text'][:120]}"
        name_col, up_col, down_col, top_col, pin_col, rm_col = st.columns([6, 1, 1, 1, 1, 1])
        name_col.markdown(label)
        if up_col.button("", key=f"dsp_{sid}_up_{i}", icon=_icons.MOVE_UP, help="Move up", disabled=i == 0,
                         use_container_width=True):
            _edit(st, session, sid, v2.move, e["name"], i - 1)
        if down_col.button("", key=f"dsp_{sid}_down_{i}", icon=_icons.MOVE_DOWN, help="Move down",
                           disabled=i == len(queue) - 1, use_container_width=True):
            _edit(st, session, sid, v2.move, e["name"], i + 1)
        if top_col.button("", key=f"dsp_{sid}_top_{i}", icon=_icons.MOVE_TOP, help="Move to top", disabled=i == 0,
                          use_container_width=True):
            _edit(st, session, sid, v2.move, e["name"], 0)
        if pin_col.button("", key=f"dsp_{sid}_pin_{i}", icon=_icons.PIN,
                          help="Unpin" if key in pins else "Pin: Adaptive keeps him at this place",
                          type="primary" if key in pins else "secondary", use_container_width=True):
            _edit(st, session, sid, v2.unpin if key in pins else v2.pin, e["name"])
        if rm_col.button("", key=f"dsp_{sid}_rm_{i}", icon=_icons.REMOVE_FROM_LIST,
                         help="Remove from this strategy (its note is kept; nothing else changes)",
                         use_container_width=True):
            _edit(st, session, sid, v2.remove, e["name"])
    st.markdown("**Add a player to this strategy**")
    in_queue = {v2.player_key(e["name"]) for e in queue}
    options = _pool_names(pool, in_queue) if pool is not None else []
    if options:
        pick = st.selectbox("Player", ["—"] + options, key=f"dsp_{sid}_add_pick")
    else:
        pick = st.text_input("Player name", key=f"dsp_{sid}_add_name")
    if st.button("Add to this strategy", key=f"dsp_{sid}_add_btn", icon=_icons.ADD_TO_QUEUE, disabled=not pick or pick == "—",
                 use_container_width=True):
        from draft_strategy_ids import with_ids

        _edit(st, session, sid, v2.insert, with_ids({"name": pick, **_pool_row(pool, pick)}, pool))
    st.caption(f"Up to {v2.QUEUE_MAX} players. Drafting never changes a saved strategy.")


def _render_notes_tab(st: Any, session: dict[str, Any], rec: dict[str, Any]) -> None:
    s = rec["strategy"]
    sid = s["id"]
    names = [e["name"] for e in s["queue"]]
    if names:
        who = st.selectbox("Player note for", names, key=f"dsp_{sid}_note_who")
        entry = next((e for e in s["queue"] if e["name"] == who), {})
        existing = v2.note_for(s, who, entry.get("mlbam_id")) or {}
        text = st.text_area("Note", value=existing.get("text", ""), max_chars=v2.NOTE_MAX,
                            key=f"dsp_{sid}_note_text_{v2.player_key(who)}",
                            help="Saved with this strategy only. Leave empty and save to remove the note.")
        if st.button("Save note", key=f"dsp_{sid}_note_save", icon=_icons.SAVE, use_container_width=True):
            _edit(st, session, sid, v2.set_note, who, text)
    else:
        st.caption("Add players to this strategy to keep notes on them.")
    st.markdown("**🔬 Research findings**")
    if rec.get("new"):
        st.caption("Save the strategy first to start its research log.")
        return
    log = _try(st, v2.research_log, session, sid) or []
    for entry in reversed(log[-10:]):
        who = f" · {entry['player_key'].title()}" if entry.get("player_key") else ""
        st.markdown(f"- {entry['text']}  \n  _{str(entry.get('at') or '')[:10]}{who}_")
    if not log:
        st.caption("No findings yet. Record what you learn on the research pages here.")
    finding = st.text_area("New finding", key=f"dsp_{sid}_finding", max_chars=v2.RESEARCH_TEXT_MAX)
    about = st.selectbox("About", ["(the whole strategy)"] + names, key=f"dsp_{sid}_finding_who")
    if st.button("Add finding", key=f"dsp_{sid}_finding_btn", icon=_icons.RESEARCH_FINDING, use_container_width=True):
        player = "" if about == "(the whole strategy)" else about
        if _try(st, v2.append_research, session, sid, finding, kind="finding", player=player,
                ok="Finding added to this strategy's research log."):
            session.pop(f"dsp_{sid}_finding", None)
        st.rerun()


def _render_preferences_tab(st: Any, session: dict[str, Any], rec: dict[str, Any]) -> None:
    s = rec["strategy"]
    sid = s["id"]
    approach = st.selectbox("Ranking approach", list(store.APPROACHES), index=list(store.APPROACHES).index(s["approach"]),
                            format_func=lambda a: APPROACH_LABELS.get(a, a), key=f"dsp_{sid}_approach")
    prefs = s.get("preferences") or {}
    cats = st.multiselect("Category priorities", list(CATEGORY_CHOICES),
                          default=[c for c in prefs.get("category_priorities") or [] if c in CATEGORY_CHOICES],
                          key=f"dsp_{sid}_cats", help="What this strategy values most (shown with the plan).")
    ranking_note = st.text_input("Ranking note", value=str(prefs.get("ranking_note") or ""), max_chars=200,
                                 key=f"dsp_{sid}_rank_note", placeholder="e.g. prioritize home runs over average")
    if st.button("Apply preferences", key=f"dsp_{sid}_prefs_btn", icon=_icons.PREFERENCES, use_container_width=True):
        def apply(strategy: dict[str, Any]) -> dict[str, Any]:
            out = v2.set_approach(strategy, approach)
            return v2.set_preferences(out, {"category_priorities": list(cats) or None,
                                            "ranking_note": ranking_note.strip() or None})

        _edit(st, session, sid, apply)


def _counts_line(p: dict[str, Any]) -> str:
    bits = [f"{_plural(p['added'])} added", f"{_plural(p['removed'])} removed", f"{p['kept']} kept"]
    if p.get("reordered"):
        bits.append("order changes")
    return " · ".join(bits)


def _render_transfer_tab(st: Any, session: dict[str, Any], rec: dict[str, Any], pool: Any) -> None:
    from ui_confirm import confirm_destructive_action

    s = rec["strategy"]
    sid = s["id"]
    with st.container(border=True):
        st.markdown("**📋 Copy Global Queue into This Strategy**")
        mode = st.radio("How", ["replace", "append"], horizontal=True, key=f"dsp_{sid}_copy_mode",
                        format_func=lambda m: "Replace this strategy's players" if m == "replace"
                        else "Add missing players to the end")
        p = work.preview_copy_global(session, sid, mode=mode)
        st.markdown(f"From **Global Queue** ({_plural(p['source_count'])}) → **{s['name']}** "
                    f"({_plural(p['before'])} now, {p['after']} after)  \n{_counts_line(p)}")
        st.caption("Your Global Queue is not changed. The strategy changes as a working copy: Save to keep it.")
        go = False
        if p["empty_source"]:
            st.caption("Your Global Queue is empty.")
        elif p["needs_confirmation"]:
            go = confirm_destructive_action(
                st, key=f"dsp_{sid}_copy_global", label="Copy Global Queue into This Strategy", icon=_icons.DRAFT_QUEUE,
                use_container_width=True, target=f"{sid}:{mode}",
                warning=(f"This replaces players in {s['name']}: {_counts_line(p)}. Continue?"),
                confirm_label="Copy into strategy")
        else:
            go = st.button("Copy Global Queue into This Strategy", key=f"dsp_{sid}_copy_global_btn", icon=_icons.DRAFT_QUEUE,
                           use_container_width=True)
        if go:
            if _try(st, work.copy_global_into, session, sid, mode=mode, confirmed=True, pool=pool):
                _flash(st, "success", f"Copied your Global Queue into **{s['name']}** ({_counts_line(p)}). "
                                      "Save the strategy to keep it.")
            st.rerun()
    with st.container(border=True):
        st.markdown("**🔁 Replace Global Queue with This Strategy**")
        r = work.preview_replace_global(session, sid)
        st.markdown(f"From **{s['name']}** ({_plural(len(s['queue']))}) → **Global Queue** "
                    f"({_plural(r['before'])} now)  \n{_counts_line(r)}")
        st.caption("This strategy is not changed." + (" It uses the strategy as shown here, including unsaved "
                                                       "changes." if r["unsaved"] else ""))
        go = False
        if r["empty_source"]:
            st.caption("This strategy has no players yet.")
        elif r["needs_confirmation"]:
            go = confirm_destructive_action(
                st, key=f"dsp_{sid}_replace_global", label="Replace Global Queue with This Strategy", icon=_icons.REPLACE_QUEUE,
                use_container_width=True, target=sid, confirm_label="Replace Global Queue",
                warning=(f"Replace your {_plural(r['before'])} Global Queue with the {_plural(len(s['queue']))} "
                         f"in {s['name']}? {_counts_line(r)}."))
        else:
            go = st.button("Replace Global Queue with This Strategy", key=f"dsp_{sid}_replace_global_btn",
                           icon=_icons.REPLACE_QUEUE, use_container_width=True)
        if go:
            if _try(st, work.replace_global_with, session, sid, confirmed=True):
                _save_global(st)
                _flash(st, "success", f"Your Global Queue now holds the {_plural(len(s['queue']))} in **{s['name']}**.")
            st.rerun()


def _render_manage_tab(st: Any, session: dict[str, Any], rec: dict[str, Any]) -> None:
    from ui_confirm import confirm_destructive_action

    s = rec["strategy"]
    sid = s["id"]
    new_name = st.text_input("Name", value=s["name"], key=f"dsp_{sid}_rename", max_chars=store.NAME_MAX)
    ren_col, dup_col = st.columns(2)
    if ren_col.button("Rename", key=f"dsp_{sid}_rename_btn", icon=_icons.EDIT, use_container_width=True):
        _edit(st, session, sid, v2.rename, new_name)
    if dup_col.button("Duplicate", key=f"dsp_{sid}_dup_btn", icon=_icons.DUPLICATE, disabled=bool(rec.get("dirty")),
                      help="Save or discard changes first" if rec.get("dirty") else "A separate copy",
                      use_container_width=True):
        _try(st, store.duplicate_strategy, session, sid, ok=f"Duplicated **{s['name']}**.")
        st.rerun()
    backup = None
    try:
        backup = v2.get_v1_backup(session, sid)
    except store.StrategyError:
        backup = None
    if backup:
        if rec.get("dirty"):
            st.caption("Save or discard your changes before restoring the original version.")
        elif confirm_destructive_action(
                st, key=f"dsp_{sid}_restore_original", label="Restore Original Version", icon=_icons.UNDO,
                use_container_width=True, target=sid, confirm_label="Restore original",
                warning=(f"Bring back {s['name']} as it was before it was first edited here "
                         f"({str(backup.get('backed_up_at') or '')[:10]})? The current version is kept under "
                         "Recently deleted for 30 days.")):
            restored = _try(st, v2.restore_original_version, session, sid, confirmed=True,
                            base_revision=rec["base_revision"], base_updated_at=rec["base_updated_at"],
                            ok="Restored the original version. The previous version is under Recently deleted.")
            if restored:
                work.forget(session, sid)
                session[work.OPEN_KEY] = sid
            st.rerun()
    from strategy_deletion_guard import PAUSED_MESSAGE, deletion_allowed

    if not deletion_allowed():
        st.button("Delete strategy", key=f"dsp_{sid}_delete_btn", icon=_icons.DELETE, use_container_width=True,
                  disabled=True, help=PAUSED_MESSAGE)
        st.caption(PAUSED_MESSAGE)
    elif confirm_destructive_action(
            st, key=f"dsp_{sid}_delete", label="Delete strategy", icon=_icons.DELETE, use_container_width=True, target=sid,
            confirm_label="Delete",
            warning=(f"Delete {s['name']}? You can restore it from Recently deleted for 30 days. Your Global "
                     "Queue and other strategies are not changed."
                     + (" Unsaved changes in it are lost." if rec.get("dirty") else ""))):
        if rec.get("new"):
            work.discard(session, sid)
        elif _try(st, v2.soft_delete, session, sid, confirmed=True, base_revision=rec["base_revision"],
                  base_updated_at=rec["base_updated_at"], ok=f"Deleted **{s['name']}** (recoverable for 30 days)."):
            work.forget(session, sid)
            loaded = session.get(store.LOADED_KEY)
            if isinstance(loaded, dict) and loaded.get("id") == sid:
                session.pop(store.LOADED_KEY, None)
        st.rerun()


def _render_trash(st: Any, session: dict[str, Any]) -> None:
    from ui_confirm import confirm_destructive_action

    rows = _try(st, v2.list_trash, session) or []
    if not rows:
        return
    with st.expander(f"Recently deleted ({len(rows)})", icon=_icons.DELETE):
        st.caption(f"Deleted strategies can be restored for {v2.RECOVERY_DAYS} days, then they are removed.")
        for row in rows:
            tid = row["trash_id"]
            why = " · kept before Restore Original" if row.get("reason") == "before_restore_original" else ""
            players = len((row.get("strategy") or {}).get("players") or [])
            st.markdown(f"**{row.get('name') or 'Strategy'}** · {_plural(players)} · deleted "
                        f"{str(row.get('deleted_at') or '')[:10]} · {_plural(row['days_left'], 'day')} left{why}")
            res_col, del_col = st.columns(2)
            with res_col:
                if st.button("Restore", key=f"dsp_trash_{tid}_restore", icon=_icons.RESTORE, use_container_width=True):
                    restored = _try(st, v2.restore_from_trash, session, tid)
                    if restored:
                        _flash(st, "success", f"Restored **{restored['name']}**.")
                        session[_NEXT_PICK_KEY] = restored["id"]
                    st.rerun()
            with del_col:
                from strategy_deletion_guard import PAUSED_MESSAGE, deletion_allowed

                if not deletion_allowed():
                    st.button("Delete permanently", key=f"dsp_trash_{tid}_purge_btn", icon=_icons.DELETE,
                              use_container_width=True, disabled=True, help=PAUSED_MESSAGE)
                elif confirm_destructive_action(
                        st, key=f"dsp_trash_{tid}_purge", label="Delete permanently", icon=_icons.DELETE,
                        use_container_width=True, target=tid, confirm_label="Delete forever",
                        warning=(f"Permanently delete {row.get('name') or 'this strategy'}, its research log and its "
                                 "original-version backup? This cannot be undone.")):
                    _try(st, v2.permanent_delete, session, tid, confirmed=True, ok="Deleted permanently.")
                    st.rerun()


def render_pro_strategies(st: Any, session: dict[str, Any], *, pool: Any = None) -> None:
    st.markdown("#### ♟️ Pro Draft Strategies")
    st.caption("Each strategy has its own queue, notes, research and ranking preferences. Editing one never "
               "changes another strategy or your Global Queue; moving players between them is always your "
               "explicit choice.")
    _render_create(st, session, pool)
    saved = _try(st, v2.list_strategies_v2, session)
    if saved is None:
        return
    sid = _render_chooser(st, session, saved)
    if sid:
        rec = _try(st, work.open_strategy, session, sid)
        if rec:
            with st.container(border=True):
                _render_header(st, session, rec)
                queue_tab, notes_tab, prefs_tab, transfer_tab, manage_tab = st.tabs(
                    ["Queue", "Notes & research", "Preferences", "Global Queue", "Manage"])
                with queue_tab:
                    _render_queue_tab(st, session, rec, pool)
                with notes_tab:
                    _render_notes_tab(st, session, rec)
                with prefs_tab:
                    _render_preferences_tab(st, session, rec)
                with transfer_tab:
                    _render_transfer_tab(st, session, rec, pool)
                with manage_tab:
                    _render_manage_tab(st, session, rec)
    _render_trash(st, session)
