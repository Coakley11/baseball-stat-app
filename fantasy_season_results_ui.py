"""Season ledger UI: period finalization, a team's period result, official standings and
completed-week history."""

from __future__ import annotations

from typing import Any

import pandas as pd

from fantasy_season_ledger import (
    PERIOD_FINALIZED,
    PERIOD_LOCKED,
    get_period,
    list_periods,
    period_date_label,
    period_status,
)
from fantasy_season_results import (
    compute_period_result,
    finalize_period,
    official_standings,
    period_category_table,
    period_result,
)

_STATS_CACHE_KEY = "_season_period_stats_cache"


def load_period_stats(session: dict[str, Any], period: dict[str, Any], *, refresh: bool = False) -> tuple[pd.DataFrame | None, str]:
    """Stats for the period's exact dates (cached per period in the session)."""
    import time

    from fantasy_period_stats import fetch_period_hitting_stats

    key = f"{period.get('start')}|{period.get('end')}"
    cache = session.setdefault(_STATS_CACHE_KEY, {})
    if not refresh and isinstance(cache.get(key), pd.DataFrame):
        return cache[key], ""
    try:
        t0 = time.perf_counter()
        df = fetch_period_hitting_stats(period["start"], period["end"])
        session["_season_period_stats_secs"] = round(time.perf_counter() - t0, 2)
    except Exception as exc:
        return None, f"Could not load stats for {period.get('label')}: {exc}"
    cache[key] = df
    return df, ""


def _fmt_rate(v: Any) -> str:
    try:
        return f"{float(v):.3f}".lstrip("0") if v is not None and pd.notna(v) else "—"
    except (TypeError, ValueError):
        return "—"


def _team_rows(result: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for team, res in sorted((result.get("teams") or {}).items()):
        t, r = res.get("totals") or {}, res.get("rates") or {}
        rows.append({
            "Team": team,
            "Lineup": "missing — scores 0" if res.get("lineup_missing") else ("set after lock" if res.get("set_after_lock") else "locked"),
            "R": int(t.get("R") or 0), "HR": int(t.get("HR") or 0), "RBI": int(t.get("RBI") or 0), "SB": int(t.get("SB") or 0),
            "H": int(t.get("H") or 0), "AB": int(t.get("AB") or 0), "AVG": _fmt_rate(r.get("AVG")), "OPS": _fmt_rate(r.get("OPS")),
        })
    return pd.DataFrame(rows)


def render_period_finalize_panel(st: Any, session: dict[str, Any], context: dict[str, Any], number: int, *, is_commissioner: bool) -> None:
    period = get_period(context, number)
    if not period:
        return
    label = str(period.get("label"))
    status = period_status(period)
    if status == PERIOD_FINALIZED:
        who = (period.get("finalized_by") or {}).get("user_id") or "the commissioner"
        st.success(f"{label} is final ({period_date_label(period)}). Finalized {str(period.get('finalized_at'))[:16].replace('T', ' ')} UTC by {who}.")
        return
    if not is_commissioner:
        return
    st.markdown(f"#### Finalize {label}")
    lineups = period.get("lineups") or {}
    teams = sorted(str(t) for t in (context.get("league_rosters") or {}))
    missing = [t for t in teams if t not in lineups]
    st.caption(
        f"{period_date_label(period)}. Lineups: "
        + " · ".join(f"{t}: {'set' if t in lineups else 'missing'}" for t in teams)
    )
    if status != PERIOD_LOCKED:
        st.info(f"{label} can be finalized after it ends on {period.get('end')}.")
        return
    flash = session.pop("_season_finalize_flash", None)
    if flash:
        st.success(flash)
    preview_key = f"_season_preview_{number}"
    if st.button(f"Load {label} stats", key=f"season_load_stats_{number}"):
        stats, err = load_period_stats(session, period, refresh=True)
        if err:
            st.error(err)
        else:
            session[preview_key] = True
    stats = (session.get(_STATS_CACHE_KEY) or {}).get(f"{period.get('start')}|{period.get('end')}")
    if not session.get(preview_key) or not isinstance(stats, pd.DataFrame):
        st.caption(f"Load the stats for {period.get('start')} – {period.get('end')} to preview and finalize.")
        return
    preview = compute_period_result(context, number, stats)
    st.dataframe(_team_rows(preview), hide_index=True, use_container_width=True)
    zero_ok = True
    if missing:
        zero_ok = st.checkbox(
            f"Score {', '.join(missing)} as zero for {label} (no lineup was set)",
            key=f"season_zero_missing_{number}",
        )
    confirm = st.checkbox(f"I understand {label} becomes final and will never change", key=f"season_confirm_{number}")
    if st.button(f"Finalize {label}", key=f"season_finalize_{number}", type="primary", disabled=not (confirm and zero_ok)):
        try:
            from fantasy_team_control import current_user_id

            actor = {"user_id": current_user_id(session), "acting_as": "commissioner"}
        except ImportError:
            actor = {"acting_as": "commissioner"}
        ok, err, _res = finalize_period(
            context, number, stats_df=stats, actor=actor, is_commissioner=True,
            score_missing_lineups_as_zero=bool(missing and zero_ok),
        )
        if not ok:
            st.error(err)
            return
        try:
            from fantasy_league_context import upsert_league_context

            upsert_league_context(session, context)
            from fantasy_shared_league_store import push_season_ledger_to_shared

            push_season_ledger_to_shared(session, context)
        except Exception:
            pass
        try:
            import streamlit as _st
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(_st, reason=f"season_period_finalized_{int(number)}")
        except Exception:
            pass
        session.pop(preview_key, None)
        session["_season_finalize_flash"] = f"{label} finalized. Its results are now part of the official standings."
        st.rerun()


def render_team_period_result(st: Any, context: dict[str, Any], number: int, team: str) -> None:
    """A finalized period's lineup and stats for one team (read-only)."""
    result = period_result(context, number)
    if not result:
        return
    res = (result.get("teams") or {}).get(team)
    if not res:
        return
    if res.get("lineup_missing"):
        st.warning(f"No lineup was set for {team}; it scored zero this week.")
        return
    rows = [{
        "Slot": l.get("slot"), "Player": l.get("player_name"), "AB": int(l.get("AB") or 0), "H": int(l.get("H") or 0),
        "HR": int(l.get("HR") or 0), "R": int(l.get("R") or 0), "RBI": int(l.get("RBI") or 0), "SB": int(l.get("SB") or 0),
    } for l in res.get("starters") or []]
    st.markdown(f"**{team} — Week {int(number)} result**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    t, r = res.get("totals") or {}, res.get("rates") or {}
    st.caption(
        f"Team totals: R {int(t.get('R') or 0)} · HR {int(t.get('HR') or 0)} · RBI {int(t.get('RBI') or 0)} · "
        f"SB {int(t.get('SB') or 0)} · AVG {_fmt_rate(r.get('AVG'))} ({int(t.get('H') or 0)}/{int(t.get('AB') or 0)})"
        + (f" · Empty: {', '.join(res.get('empty_slots'))}" if res.get("empty_slots") else "")
        + (f" · Bench (not scored): {', '.join(res.get('bench'))}" if res.get("bench") else "")
    )


def render_official_standings(st: Any, context: dict[str, Any] | None) -> bool:
    """Official standings from finalized periods. Returns True when the league uses the ledger."""
    periods = list_periods(context)
    st.subheader("League Standings (official)")
    if not periods:
        st.info(
            "Official standings start when the commissioner sets the season calendar (Lineup page) and "
            "finalizes the first week. The table further down is a current-roster snapshot, not the standings."
        )
        return False
    table, weeks = official_standings(context)
    if table.empty:
        st.info("No week is final yet. Official standings appear after the commissioner finalizes Week 1.")
    else:
        shown = table.copy()
        for col in ("AVG", "OBP", "OPS", "SLG"):
            if col in shown.columns:
                shown[col] = shown[col].map(_fmt_rate)
        shown = shown.drop(columns=[c for c in ("H", "AB") if c in shown.columns])
        st.caption(
            f"Sum of finalized weeks ({', '.join(str(w) for w in weeks)}). Each week counts the lineup used that week; "
            "later drops and trades never change a completed week. Tied teams split category points."
        )
        st.dataframe(shown, hide_index=True, use_container_width=True)
    render_completed_weeks(st, context)
    return True


def render_completed_weeks(st: Any, context: dict[str, Any] | None) -> None:
    finalized = [p for p in list_periods(context) if period_status(p) == PERIOD_FINALIZED]
    if not finalized:
        return
    # A plain section, not an expander: changing the week reruns the page, which folded
    # an expander away before the chosen week could be read.
    st.markdown("#### Completed weeks")
    options = [int(p["number"]) for p in finalized]
    number = st.selectbox(
        "Completed week",
        options,
        index=len(options) - 1,
        format_func=lambda n: f"{get_period(context, n)['label']} · {period_date_label(get_period(context, n))}",
        key="season_history_week",
    )
    period = get_period(context, number) or {}
    result = period_result(context, number) or {}
    who = (period.get("finalized_by") or {}).get("user_id") or "the commissioner"
    st.caption(
        f"Final · {period.get('start')} – {period.get('end')} · finalized {str(period.get('finalized_at'))[:16].replace('T', ' ')} UTC "
        f"by {who} · stats: {result.get('stats_source', '')}"
    )
    st.markdown("**Week totals and category points**")
    week_table = period_category_table(context, number)
    if not week_table.empty:
        shown = week_table.drop(columns=[c for c in ("H", "AB") if c in week_table.columns]).copy()
        for col in ("AVG", "OBP", "OPS"):
            if col in shown.columns:
                shown[col] = shown[col].map(_fmt_rate)
        st.dataframe(shown, hide_index=True, use_container_width=True)
    st.markdown("**Lineups used**")
    for team, res in sorted((result.get("teams") or {}).items()):
        if res.get("lineup_missing"):
            st.caption(f"{team}: no lineup — scored zero")
            continue
        starters = ", ".join(f"{l.get('slot')} {l.get('player_name')}" for l in res.get("starters") or [])
        extra = f" · empty: {', '.join(res.get('empty_slots'))}" if res.get("empty_slots") else ""
        st.caption(f"{team}: {starters}{extra}" + (" · set after lock" if res.get("set_after_lock") else ""))
