"""Live Draft Room presentation — styles, badges, cards (no draft logic)."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

LIVE_DRAFT_REC_DIAG_KEY = "_live_draft_rec_diag"


def record_rec_card_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    diag = dict(session.get(LIVE_DRAFT_REC_DIAG_KEY) or {})
    diag.update(fields)
    session[LIVE_DRAFT_REC_DIAG_KEY] = diag
    return diag


def inject_live_draft_room_styles(st: Any) -> None:
    st.markdown(
        """
        <style>
        .live-draft-page-header {
            margin-bottom: 8px;
        }
        .live-draft-on-clock {
            background: linear-gradient(145deg, #061e3a 0%, #0b3d6e 38%, #1a5fbf 72%, #2d8cff 100%);
            color: #fff;
            padding: 32px 30px 26px 30px;
            border-radius: 20px;
            margin-bottom: 20px;
            box-shadow: 0 14px 36px rgba(8, 35, 80, 0.38);
            position: relative;
            overflow: hidden;
        }
        .live-draft-on-clock::after {
            content: "";
            position: absolute;
            top: -40%;
            right: -10%;
            width: 220px;
            height: 220px;
            background: radial-gradient(circle, rgba(255,255,255,0.14) 0%, transparent 70%);
            pointer-events: none;
        }
        .live-draft-on-clock .ld-title {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.18em;
            opacity: 0.92;
            font-weight: 800;
            margin-bottom: 6px;
        }
        .live-draft-on-clock .ld-team-name {
            font-size: clamp(2.6rem, 7vw, 4rem);
            font-weight: 900;
            line-height: 1.02;
            margin: 2px 0 12px 0;
            letter-spacing: -0.03em;
            text-shadow: 0 3px 18px rgba(0,0,0,0.22);
            color: #ffffff;
        }
        .live-draft-on-clock .ld-pick-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 14px;
        }
        .live-draft-on-clock .ld-pill {
            display: inline-block;
            padding: 5px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            background: rgba(255,255,255,0.16);
            border: 1px solid rgba(255,255,255,0.22);
        }
        .live-draft-on-clock .ld-next-pick {
            font-size: 14px;
            opacity: 0.94;
            margin-bottom: 12px;
            font-weight: 600;
        }
        .live-draft-on-clock .ld-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            flex-wrap: wrap;
        }
        .live-draft-on-clock .ld-clock-label {
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            opacity: 0.88;
            font-weight: 700;
        }
        .live-draft-timer {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 88px;
            background: rgba(0,0,0,0.22);
            border: 2px solid rgba(255,255,255,0.28);
            border-radius: 14px;
            padding: 12px 18px;
            font-weight: 900;
            font-size: 34px;
            letter-spacing: -0.03em;
            line-height: 1;
        }
        .ld-room-code-panel {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            margin: 12px 0 16px 0;
            padding: 14px 16px;
            background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
            border: 1px solid #c7d2fe;
            border-radius: 14px;
        }
        .ld-room-code-label {
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #4338ca;
        }
        .ld-room-code-value {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 28px;
            font-weight: 900;
            letter-spacing: 0.22em;
            color: #1e1b4b;
            padding: 4px 10px;
            background: #fff;
            border-radius: 10px;
            border: 2px dashed #a5b4fc;
        }
        .live-draft-status-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 8px 0 14px 0;
        }
        .ld-badge-pill {
            display: inline-block;
            padding: 7px 13px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.01em;
            border: 1px solid transparent;
        }
        .ld-badge-pick { background: #e8f1ff; color: #0b3d6e; border-color: #c5d9f5; }
        .ld-badge-round { background: #f0fdf4; color: #166534; border-color: #bbf7d0; }
        .ld-badge-team { background: #fff7ed; color: #9a3412; border-color: #fed7aa; }
        .ld-badge-live { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
        .live-draft-controls {
            position: sticky;
            top: 0;
            z-index: 100;
            background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
            padding: 14px 0 16px 0;
            border-bottom: 1px solid #e2e8f0;
            margin-bottom: 16px;
            border-radius: 0 0 14px 14px;
        }
        .live-draft-controls .ld-controls-title {
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: #64748b;
            margin-bottom: 10px;
        }
        .live-draft-action-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
            gap: 10px;
            margin: 4px 0 10px 0;
        }
        .live-draft-action-row div[data-testid="stButton"] > button {
            width: 100%;
            min-height: 46px;
            border-radius: 12px !important;
            font-weight: 800 !important;
            font-size: 14px !important;
            border: 1px solid #cbd5e1 !important;
            background: linear-gradient(180deg, #ffffff 0%, #f1f5f9 100%) !important;
            color: #0f172a !important;
            box-shadow: 0 1px 2px rgba(15,23,42,0.06) !important;
            transition: transform 0.12s ease, box-shadow 0.12s ease;
        }
        .live-draft-action-row div[data-testid="stButton"] > button:hover {
            border-color: #94a3b8 !important;
            box-shadow: 0 4px 12px rgba(15,23,42,0.1) !important;
            transform: translateY(-1px);
        }
        .live-draft-action-row div[data-testid="stButton"] > button[kind="primary"] {
            background: linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%) !important;
            border-color: #1e40af !important;
            color: #fff !important;
        }
        .live-draft-action-danger div[data-testid="stButton"] > button {
            border-color: #fca5a5 !important;
            color: #991b1b !important;
            background: linear-gradient(180deg, #fff5f5 0%, #fee2e2 100%) !important;
        }
        .live-draft-board-panel,
        .live-draft-queue-panel,
        .live-draft-totals-panel,
        .live-draft-rec-panel {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 16px 18px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
        }
        .live-draft-section-title {
            font-size: 1.05rem;
            font-weight: 800;
            color: #0f172a;
            margin: 0 0 10px 0;
            letter-spacing: -0.01em;
        }
        .ld-room-header {
            background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
            border: 1px solid #c7d2fe;
            border-radius: 14px;
            padding: 12px 16px;
            margin: 0 0 14px 0;
        }
        .ld-room-header .ld-rh-title {
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: #4338ca;
            margin-bottom: 6px;
        }
        .ld-room-header .ld-rh-code {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 24px;
            font-weight: 900;
            letter-spacing: 0.2em;
            color: #1e1b4b;
        }
        .ld-room-header .ld-rh-meta {
            font-size: 13px;
            line-height: 1.5;
            color: #334155;
            margin-top: 8px;
        }
        .ld-rec-compact-row {
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 10px 12px;
            margin-bottom: 8px;
            background: #fff;
        }
        .ld-rec-compact-row .ld-rec-name {
            font-size: 16px;
            font-weight: 800;
            line-height: 1.25;
            color: #0f172a;
            word-break: break-word;
        }
        .ld-rec-compact-row .ld-rec-line {
            font-size: 13px;
            color: #475569;
            line-height: 1.4;
            margin-top: 4px;
            word-break: break-word;
        }
        .ld-rec-stacked .ld-rec-name {
            font-size: 16px;
            font-weight: 800;
            line-height: 1.25;
            color: #0f172a;
        }
        .live-rec-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 10px;
            margin-bottom: 12px;
        }
        .live-rec-card {
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #dbe3ee;
            border-radius: 14px;
            padding: 14px 14px 12px 14px;
            box-shadow: 0 2px 6px rgba(15,23,42,0.05);
            border-left: 4px solid #2563eb;
        }
        .live-rec-card.tier-top { border-left-color: #16a34a; }
        .live-rec-card.tier-value { border-left-color: #d97706; }
        .live-rec-card.tier-risk { border-left-color: #dc2626; }
        .live-rec-card .rec-rank {
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #64748b;
            margin-bottom: 4px;
        }
        .live-rec-card .name {
            font-weight: 800;
            color: #0f172a;
            font-size: 17px;
            line-height: 1.2;
            margin-bottom: 6px;
        }
        .live-rec-card .pos-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 6px;
            background: #e0e7ff;
            color: #3730a3;
            font-size: 11px;
            font-weight: 800;
            margin-right: 6px;
        }
        .live-rec-card .stats { color: #475569; font-size: 12px; line-height: 1.45; }
        .live-rec-card .surv-high { color: #15803d; font-weight: 700; font-size: 12px; margin-top: 6px; }
        .live-rec-card .surv-mid { color: #b45309; font-weight: 700; font-size: 12px; margin-top: 6px; }
        .live-rec-card .surv-low { color: #b91c1c; font-weight: 700; font-size: 12px; margin-top: 6px; }
        .ld-rec-summary-banner {
            background: linear-gradient(135deg, #eff6ff 0%, #f0fdf4 100%);
            border: 1px solid #bfdbfe;
            border-radius: 12px;
            padding: 12px 14px;
            margin: 0 0 14px 0;
            font-size: 14px;
            line-height: 1.45;
            color: #1e293b;
        }
        .ld-rec-tier-best { background: #dcfce7; color: #166534; }
        .ld-rec-tier-strong { background: #dbeafe; color: #1e40af; }
        .ld-rec-tier-value { background: #fef3c7; color: #92400e; }
        .ld-rec-tier-need { background: #ede9fe; color: #5b21b6; }
        .ld-rec-tier-sleeper { background: #fce7f3; color: #9d174d; }
        .ld-rec-tier-safe { background: #f1f5f9; color: #334155; }
        .ld-rec-edge-pos { color: #16a34a; font-weight: 900; }
        .ld-rec-edge-neu { color: #2563eb; font-weight: 900; }
        .ld-rec-edge-neg { color: #dc2626; font-weight: 900; }
        .ld-roster-tracker-panel,
        .ld-category-outlook-panel {
            background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
            border: 1px solid #bfdbfe;
            border-radius: 14px;
            padding: 14px 16px;
            margin-bottom: 14px;
        }
        .ld-roster-tracker-panel .ld-panel-title,
        .ld-category-outlook-panel .ld-panel-title {
            font-size: 14px;
            font-weight: 800;
            color: #1e3a8a;
            margin-bottom: 8px;
        }
        .ld-roster-line { font-size: 14px; line-height: 1.55; color: #0f172a; font-family: ui-monospace, monospace; }
        .ld-roster-line.open { color: #b45309; font-weight: 700; }
        .ld-roster-progress { font-size: 12px; color: #64748b; margin-top: 6px; }
        .ld-cat-bar-row { font-size: 13px; line-height: 1.5; color: #1e293b; margin: 2px 0; font-family: ui-monospace, monospace; }
        .ld-cat-insight { font-size: 12px; color: #475569; margin-top: 8px; line-height: 1.45; }
        .ld-rec-badge-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 4px 0; }
        .ld-rec-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 800;
            background: #dbeafe;
            color: #1e40af;
            border: 1px solid #93c5fd;
        }
        .ld-rec-badge.gold { background: #fef3c7; color: #92400e; border-color: #fcd34d; }
        .ld-rec-badge.need { background: #ede9fe; color: #5b21b6; border-color: #c4b5fd; }
        .ld-rec-badge.fire { background: #ffedd5; color: #c2410c; border-color: #fdba74; }
        .ld-draft-complete-banner {
            background: linear-gradient(135deg, #ecfdf5 0%, #dbeafe 100%);
            border: 2px solid #22c55e;
            border-radius: 16px;
            padding: 22px 24px;
            margin: 0 0 18px 0;
        }
        .ld-draft-complete-banner .ld-dc-title {
            font-size: 1.6rem;
            font-weight: 900;
            color: #14532d;
            margin-bottom: 6px;
        }
        .ld-draft-complete-banner .ld-dc-sub {
            font-size: 15px;
            color: #334155;
            margin-bottom: 12px;
        }
        .live-draft-manual-panel div[data-testid="stButton"] button[kind="primary"] {
            min-height: 50px;
            font-size: 16px;
            font-weight: 800;
            border-radius: 12px;
        }
        @media (max-width: 768px) {
            .live-draft-on-clock { padding: 20px 16px; }
            .live-draft-on-clock .ld-team-name { font-size: 2.2rem; }
            .live-draft-timer { font-size: 26px; min-width: 72px; padding: 10px 14px; }
            .ld-room-code-value { font-size: 22px; letter-spacing: 0.16em; }
            .live-rec-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_draft_room_code_panel(
    st: Any,
    code: str,
    *,
    join_url: str = "",
    show_copy: bool = True,
) -> None:
    code = str(code or "").strip().upper()
    if not code:
        return
    st.markdown(
        f"""
        <div class="ld-room-code-panel">
            <div>
                <div class="ld-room-code-label">Room Code</div>
                <div class="ld-room-code-value">{code}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    try:
        st.code(code, language=None)
    except TypeError:
        st.code(code)
    st.caption("Share this 6-character code so other managers can join your live draft.")
    if join_url:
        st.markdown(f"**Join link:** [{join_url}]({join_url})")


def render_live_draft_room_code_header(
    st: Any,
    session: dict[str, Any],
    *,
    multiplayer: bool,
    join_url: str = "",
) -> None:
    """Show room code, copy affordance, and missing-code warning near draft header."""
    code = ""
    try:
        from draft_room_context import resolve_shared_room_code

        code = resolve_shared_room_code(session)
    except ImportError:
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()

    if code:
        render_draft_room_code_panel(st, code, join_url=join_url)
        return
    if multiplayer:
        st.warning("Room code missing — shared draft may not be joinable.")
        try:
            from suite_workspace import can_show_developer_tools

            if can_show_developer_tools(st=st):
                room = session.get("live_draft_room") or {}
                internal_id = str(room.get("draft_room_id") or "—")
                st.caption(f"Dev: room_id `{internal_id}` · room_code `—`")
        except ImportError:
            pass


def render_live_draft_room_header(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    multiplayer: bool,
    user_team: str = "",
    on_clock_team: str = "",
    pick_label: str = "",
    status_label: str = "",
    draft_in_progress: bool = False,
) -> None:
    """Always-visible room header: mode, code (multiplayer only), role, team, status."""
    code = ""
    role = ""
    assigned_team = str(user_team or "").strip()
    mode_label = "Solo Draft"
    mode_detail = "You control all teams"
    solo = True
    try:
        from live_draft_setup_mode import is_solo_draft_mode, is_shared_multiplayer_intent, shared_room_code

        solo = is_solo_draft_mode(session, room=room)
        if solo:
            mode_label = "Solo Draft"
            teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
            mode_detail = f"You control all teams ({len(teams)} teams)" if len(teams) > 1 else "You control all teams"
        elif is_shared_multiplayer_intent(session, room=room):
            mode_label = "Shared Multiplayer"
            mode_detail = ""
            from draft_room_context import get_global_draft_context, resolve_shared_room_code

            ctx = get_global_draft_context(session)
            code = shared_room_code(session) or resolve_shared_room_code(session)
            role = "Host" if ctx.get("is_room_host") else "Guest"
            assigned_team = str(ctx.get("participant_team") or assigned_team or "—").strip() or "—"
    except ImportError:
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
        solo = not bool(code) and not multiplayer
        if multiplayer or code:
            solo = False
            mode_label = "Shared Multiplayer"
            role = "Host"

    teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
    ownership_lines: list[str] = []
    try:
        from live_draft_team_ownership import format_team_ownership_html, team_claim_rows

        ownership_lines = [format_team_ownership_html(r) for r in team_claim_rows(session, room)]
    except ImportError:
        ownership_lines = []
    teams_txt = ", ".join(teams) if teams else "—"
    if ownership_lines:
        teams_block = "<br/>".join(f"· {line}" for line in ownership_lines)
    else:
        teams_block = teams_txt
    live_badge = " · **Live**" if draft_in_progress else ""
    status_txt = str(status_label or room.get("status") or "—").replace("_", " ").title()

    if solo:
        st.markdown(
            f"""
            <div class="ld-room-header">
                <div class="ld-rh-title">Live draft room</div>
                <div class="ld-rh-meta">
                    <strong>Mode:</strong> {mode_label} · {mode_detail}<br/>
                    <strong>Your team:</strong> {assigned_team or "—"} ·
                    <strong>Status:</strong> {status_txt}{live_badge} ·
                    <strong>{pick_label or "Pick"}</strong> ·
                    <strong>On clock:</strong> {on_clock_team or "—"}<br/>
                    <strong>Teams:</strong> {teams_txt}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    code_block = (
        f'<div class="ld-rh-code">{code}</div>' if code else '<span style="color:#b45309;">Code missing</span>'
    )
    role_txt = f"<strong>Your role:</strong> {role} · " if role else ""
    st.markdown(
        f"""
        <div class="ld-room-header">
            <div class="ld-rh-title">Live draft room · {mode_label}</div>
            {code_block}
            <div class="ld-rh-meta">
                {role_txt}
                <strong>Your team:</strong> {assigned_team or "—"} ·
                <strong>Status:</strong> {status_txt}{live_badge} ·
                <strong>{pick_label or "Pick"}</strong> ·
                <strong>On clock:</strong> {on_clock_team or "—"}<br/>
                <strong>Teams:</strong><br/>{teams_block}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if code:
        try:
            st.code(code, language=None)
        except TypeError:
            st.code(code)
        st.caption(f"Invite players with this room code: **{code}**")
    else:
        st.error("Could not create shared room. This draft cannot be joined by others.")


def render_live_draft_status_badges(
    st: Any,
    *,
    pick_label: str,
    round_no: str,
    on_clock_team: str,
    live: bool = False,
) -> None:
    live_badge = '<span class="ld-badge-pill ld-badge-live">● Live</span>' if live else ""
    st.markdown(
        f"""
        <div class="live-draft-status-badges">
            <span class="ld-badge-pill ld-badge-pick">{pick_label}</span>
            <span class="ld-badge-pill ld-badge-round">Round {round_no}</span>
            <span class="ld-badge-pill ld-badge-team">On clock: {on_clock_team}</span>
            {live_badge}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_roster_tracker_panel(st: Any, tracker: dict[str, Any]) -> None:
    """Checklist-style roster needs for the user's team."""
    lines = tracker.get("lines") or []
    if not lines:
        st.caption("No roster slots configured.")
        return
    filled = int(tracker.get("filled") or 0)
    target = int(tracker.get("target") or 0)
    html_lines = []
    for ln in lines:
        mark = "✓" if ln.get("filled") else "✗"
        label = str(ln.get("label") or "")
        css = "" if ln.get("filled") else " open"
        html_lines.append(f'<div class="ld-roster-line{css}">{mark} {label}</div>')
    progress = f"Roster complete: {filled} / {target}" if target else ""
    st.markdown(
        f'<div class="ld-roster-tracker-panel">'
        f'<div class="ld-panel-title">Roster Needs Checklist</div>'
        f'{"".join(html_lines)}'
        f'<div class="ld-roster-progress">{progress}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_category_outlook_panel(st: Any, outlook: dict[str, Any]) -> None:
    bars = outlook.get("bars") or []
    if not bars:
        return
    bar_html = "".join(
        f'<div class="ld-cat-bar-row">{b.get("category", "")}  {b.get("bar", "")}  {b.get("level", "")}</div>'
        for b in bars
    )
    needs = outlook.get("needs_attention") or []
    strengths = outlook.get("strengths") or []
    insight_parts = []
    if needs:
        insight_parts.append("<strong>Needs attention:</strong> " + ", ".join(needs))
    if strengths:
        insight_parts.append("<strong>Strengths:</strong> " + ", ".join(strengths))
    insight = "<br/>".join(insight_parts)
    st.markdown(
        f'<div class="ld-category-outlook-panel">'
        f'<div class="ld-panel-title">Team Category Outlook</div>'
        f"{bar_html}"
        f'<div class="ld-cat-insight">{insight}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_live_draft_complete_banner(
    st: Any,
    *,
    team_label: str = "",
    picks_done: int,
    total_picks: int,
) -> None:
    picks_txt = f"{picks_done} of {total_picks} picks completed" if total_picks else f"{picks_done} picks completed"
    team_line = f"<br/><span>{team_label}</span>" if str(team_label or "").strip() else ""
    st.markdown(
        f"""
        <div class="ld-draft-complete-banner">
            <div class="ld-dc-title">Draft Completed</div>
            <div class="ld-dc-sub">{picks_txt}{team_line}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _format_detail_value(col: str, val: Any) -> str:
    try:
        from draft_score_display import format_detail_line

        _label, formatted = format_detail_line(col, val)
        return formatted
    except ImportError:
        pass
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if col in ("Model Rank", "Market Rank"):
        try:
            return str(int(round(float(val))))
        except (TypeError, ValueError):
            return str(val)
    if col == "Fantasy Edge":
        try:
            n = float(val)
            sign = "+" if n > 0 else ""
            return f"{sign}{int(round(n))}"
        except (TypeError, ValueError):
            return str(val)
    if col in ("Draft Fit Score", "Decision Score", "Expected Fantasy Value", "ML Projection Score"):
        try:
            from draft_score_display import format_detail_line

            _label, formatted = format_detail_line(col, val)
            return formatted
        except ImportError:
            pass
        try:
            return f"{float(val):.2f}"
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def _detail_display_label(col: str) -> str:
    try:
        from draft_score_display import format_detail_line

        label, _ = format_detail_line(col, 0)
        return label
    except ImportError:
        mapping = {
            "Draft Fit Score": "Roster Fit Score",
            "Decision Score": "Decision Score",
            "Expected Fantasy Value": "Player Grade",
        }
        return mapping.get(col, col.replace("Draft Fit Score", "Roster Fit"))


def _rec_card_badges(
    rank: int,
    row: Any,
    rec_df: Any,
    *,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Return (label, css_class) badge tuples for a recommendation card."""
    badges: list[tuple[str, str]] = []
    rank_labels = {1: "🏆 Best Overall", 2: "🥈 Second Best", 3: "🥉 Third Best"}
    if rank in rank_labels:
        badges.append((rank_labels[rank], "gold"))

    if rec_df is not None and not getattr(rec_df, "empty", True) and "Fantasy Edge" in rec_df.columns:
        edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
        top_edge = pd.to_numeric(rec_df["Fantasy Edge"], errors="coerce").max()
        if pd.notna(edge) and pd.notna(top_edge) and float(edge) >= float(top_edge):
            badges.append(("🔥 Best Value", "fire"))

    pos = str(row.get("Primary Position") or "")
    fit = pd.to_numeric(row.get("Positional Fit", np.nan), errors="coerce")
    if gaps and pos in gaps and pd.notna(fit) and float(fit) >= 0.5:
        badges.append(("📈 Position Need", "need"))

    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    if pd.notna(scarcity) and float(scarcity) >= 0.6:
        if rec_df is not None and "Scarcity Score" in getattr(rec_df, "columns", []):
            if float(scarcity) >= float(pd.to_numeric(rec_df["Scarcity Score"], errors="coerce").max() or 0):
                badges.append(("⚡ Best Scarcity Pick", "need"))

    cat_bonus = pd.to_numeric(row.get("Category Need Bonus", np.nan), errors="coerce")
    if category_needs and pd.notna(cat_bonus) and float(cat_bonus) > 0:
        badges.append(("🎯 Best Category Fit", "need"))

    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    if pd.notna(edge) and float(edge) >= 10 and not any("Best Value" in b[0] for b in badges):
        badges.append(("Highest Fantasy Edge", "fire"))

    return badges[:4]


def _rec_rank_label(rank: int) -> str:
    labels = {1: "🥇 Best Pick", 2: "🥈 Second Best Option", 3: "🥉 Third Best Option"}
    return labels.get(rank, f"Rank #{rank}")


def _rec_tier_badge(rank: int, row: Any) -> tuple[str, str]:
    fit = pd.to_numeric(row.get("Positional Fit", np.nan), errors="coerce")
    sleeper = pd.to_numeric(row.get("Sleeper Score", np.nan), errors="coerce")
    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    if rank == 1:
        return "Best Pick", "ld-rec-tier-best"
    if pd.notna(fit) and float(fit) >= 0.65:
        return "Position Need", "ld-rec-tier-need"
    if pd.notna(sleeper) and float(sleeper) >= 0.6:
        return "Sleeper", "ld-rec-tier-sleeper"
    if pd.notna(edge) and float(edge) >= 8:
        return "High Value", "ld-rec-tier-value"
    if rank <= 3:
        return "Strong Fit", "ld-rec-tier-strong"
    return "Safe Pick", "ld-rec-tier-safe"


def _rec_action_guidance(surv: float | None, rank: int) -> str:
    if rank == 1:
        return "Draft Now"
    if surv is not None and surv < 0.25:
        return "High Risk if Passed"
    if surv is not None and surv < 0.45:
        return "Strong Consideration"
    if surv is not None and surv >= 0.7:
        return "Can Wait One Round"
    return "Strong Consideration"


def build_draft_insight_text(
    row: Any,
    *,
    badges: list[tuple[str, str]] | None = None,
    strengths: list[str] | None = None,
    gaps: list[str] | None = None,
    rank: int = 0,
) -> str:
    """Non-redundant guidance below badges — never restates badge labels."""
    badge_labels = " ".join(label for label, _css in (badges or []))
    pos = str(row.get("Primary Position") or "")
    parts: list[str] = []

    if strengths:
        parts.append(f"Strengthens {' and '.join(strengths)}.")

    surv = pd.to_numeric(row.get("Survival Probability", np.nan), errors="coerce")
    if pd.notna(surv):
        pct = int(round(float(surv) * 100))
        if float(surv) < 0.25:
            parts.append("High risk if passed — unlikely to reach your next pick.")
        elif float(surv) < 0.35:
            pos_word = pos or "player"
            parts.append(f"May be the last high-quality {pos_word} before your next turn.")
        elif float(surv) < 0.5 and "Scarcity" not in badge_labels:
            parts.append(f"{pct}% chance still available next round.")

    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    if pd.notna(scarcity) and float(scarcity) >= 0.6 and "Scarcity" not in badge_labels:
        if gaps and pos in gaps:
            parts.append(f"Scarcity rising at {pos}.")
        elif pos:
            parts.append(f"Thin {pos} tier remaining.")

    if (
        "Position Need" not in badge_labels
        and gaps
        and pos in gaps
        and not any("Scarcity" in p for p in parts)
    ):
        open_of = sum(1 for g in gaps if g == "OF")
        if pos == "OF" and open_of >= 2:
            parts.append(f"{open_of} OF slots still open on your roster.")

    if (
        rank == 1
        and "Best Overall" not in badge_labels
        and "Best Pick" not in badge_labels
        and "Position Need" not in badge_labels
        and "Highest Fantasy Edge" not in badge_labels
        and "Best Value" not in badge_labels
        and (not gaps or pos not in (gaps or []))
    ):
        parts.append("Top projected value without filling an open roster slot.")

    if rank > 1 and ("Second" in badge_labels or "Third" in badge_labels):
        dec = pd.to_numeric(row.get("Decision Score", np.nan), errors="coerce")
        if pd.notna(dec) and float(dec) >= 0.68 and not parts:
            parts.append("Strong grade among remaining options at this pick.")
    elif rank > 1 and "Second" not in badge_labels and "Third" not in badge_labels:
        dec = pd.to_numeric(row.get("Decision Score", np.nan), errors="coerce")
        if pd.notna(dec) and float(dec) >= 0.72 and not parts:
            parts.append("Strong grade among remaining options at this pick.")

    return " ".join(parts[:3])


def build_draft_insight_expander_text(
    row: Any,
    *,
    badges: list[tuple[str, str]] | None = None,
    strengths: list[str] | None = None,
    gaps: list[str] | None = None,
    rank: int = 0,
) -> str:
    """Longer draft guidance for the Draft Insight expander (no duplicate stats)."""
    lead = build_draft_insight_text(
        row, badges=badges, strengths=strengths, gaps=gaps, rank=rank
    )
    if lead:
        return lead
    pos = str(row.get("Primary Position") or "")
    if gaps and pos in gaps:
        return f"Targets your remaining {pos} roster slot."
    return "Balanced upside and availability at this pick."


def _rec_plain_explanation(
    row: Any,
    pos: str,
    *,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    strengths: list[str] | None = None,
) -> str:
    """Legacy alias — prefer ``build_why_this_pick_summary``."""
    return build_why_this_pick_summary(
        row, pos, gaps=gaps, category_needs=category_needs, strengths=strengths
    )


def build_why_this_pick_summary(
    row: Any,
    pos: str,
    *,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    strengths: list[str] | None = None,
    include_position_need: bool = False,
) -> str:
    """One-line recommendation rationale — main drivers only, no duplicate Proj: prose."""
    parts: list[str] = []

    surv = pd.to_numeric(row.get("Survival Probability", np.nan), errors="coerce")
    if pd.notna(surv) and float(surv) < 0.35:
        parts.append(f"{int(round(float(surv) * 100))}% avail at next pick")
    elif pd.notna(surv) and float(surv) < 0.5:
        parts.append(f"{int(round(float(surv) * 100))}% avail at next pick")

    cat_bonus = pd.to_numeric(row.get("Category Need Bonus", np.nan), errors="coerce")
    if category_needs and pd.notna(cat_bonus) and float(cat_bonus) > 0:
        weak = str(category_needs[0] or "a weak category")
        parts.append(f"helps {weak}")

    if strengths:
        parts.append(f"strong in {'/'.join(strengths[:2])}")

    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    if pd.notna(edge) and abs(float(edge)) >= 5:
        sign = "+" if float(edge) > 0 else ""
        parts.append(f"Fantasy Edge {sign}{int(round(float(edge)))}")

    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    if pd.notna(scarcity) and float(scarcity) >= 0.6:
        parts.append(f"{pos} scarcity rising")

    if include_position_need:
        fit = pd.to_numeric(row.get("Positional Fit", np.nan), errors="coerce")
        if gaps and str(pos) in gaps and pd.notna(fit) and float(fit) >= 0.5:
            open_of = sum(1 for g in gaps if g == "OF")
            if str(pos) == "OF" and open_of >= 2:
                parts.append(f"fills OF need ({open_of} spots open)")
            else:
                parts.append(f"fills {pos} need")

    if not parts:
        return "Strong balance of upside and roster fit."
    return "; ".join(parts[:5]) + "."


def build_draft_assistant_why_this_pick(
    row: Any,
    *,
    needed_positions: list[str] | None = None,
    category_needs: list[str] | None = None,
    pool_df: Any = None,
    draft_format: str = "5x5 Roto",
) -> str:
    """Natural-language one-line rationale for Draft Assistant (no duplicate Proj: prose)."""
    pos = str(row.get("Primary Position") or "")
    strengths: list[str] = []
    if pool_df is not None:
        try:
            from live_draft_category_outlook import player_top_category_strengths

            scoring = (
                "Roto (5x5)"
                if str(draft_format).strip() in ("5x5 Roto", "Roto (5x5)")
                else str(draft_format)
            )
            strengths = player_top_category_strengths(
                row,
                pool_df,
                config={"scoring_type": scoring, "fantasy_format": draft_format},
                max_count=2,
            )
        except ImportError:
            pass

    gaps = list(needed_positions or [])
    clauses: list[str] = []

    surv = pd.to_numeric(row.get("Survival Probability", np.nan), errors="coerce")
    if pd.notna(surv) and float(surv) < 0.35:
        clauses.append(f"roughly {int(round(float(surv) * 100))}% chance to reach your next pick")

    cat_bonus = pd.to_numeric(row.get("Category Need Bonus", np.nan), errors="coerce")
    if category_needs and pd.notna(cat_bonus) and float(cat_bonus) > 0:
        cat_label = "/".join(str(c) for c in category_needs[:2])
        clauses.append(f"improves your {cat_label} outlook")

    if strengths:
        clauses.append(f"adds {'/'.join(strengths)} strength")

    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    mkt = pd.to_numeric(row.get("Market Rank", np.nan), errors="coerce")
    mdl = pd.to_numeric(row.get("Model Rank", np.nan), errors="coerce")
    if pd.notna(edge) and float(edge) >= 8:
        if pd.notna(mkt) and pd.notna(mdl):
            clauses.append(
                f"the model ranks him well above market (model {int(round(float(mdl)))} vs market {int(round(float(mkt)))})"
            )
        else:
            clauses.append(f"Fantasy Edge +{int(round(float(edge)))}")
    elif pd.notna(edge) and float(edge) <= -8:
        clauses.append("market rank runs ahead of the model")

    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    pos_fit = pd.to_numeric(row.get("Positional Fit", np.nan), errors="coerce")
    if pd.notna(scarcity) and float(scarcity) >= 0.6:
        clauses.append(f"few quality {pos} options remain")

    decision = pd.to_numeric(row.get("Decision Score", np.nan), errors="coerce")
    weak_fit = bool(pos and pos not in gaps and pd.notna(pos_fit) and float(pos_fit) < 0.45)
    if weak_fit and pd.notna(decision) and float(decision) >= 0.65:
        lead = f"Good but not urgent: strong player grade, but weaker roster fit because {pos} is already filled"
        if clauses:
            return lead + ", and " + ", ".join(clauses[:3]) + "."
        return lead + "."

    if not clauses:
        return build_why_this_pick_summary(
            row, pos, gaps=gaps, category_needs=category_needs, strengths=strengths
        )
    return ", ".join(clauses[:4]).capitalize() + "."


def add_why_this_pick_column(
    rec_df: Any,
    *,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    pool_df: Any = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Add a single ``Why this pick`` column to a recommendation table."""
    if rec_df is None or getattr(rec_df, "empty", True):
        return rec_df
    out = rec_df.copy()
    whys: list[str] = []
    for _, r in out.iterrows():
        pos = str(r.get("Primary Position") or "")
        strengths: list[str] = []
        if pool_df is not None:
            try:
                from live_draft_category_outlook import player_top_category_strengths

                strengths = player_top_category_strengths(r, pool_df, config=config or {}, max_count=2)
            except ImportError:
                pass
        whys.append(
            build_why_this_pick_summary(
                r, pos, gaps=gaps, category_needs=category_needs, strengths=strengths
            )
        )
    out["Why this pick"] = whys
    return out


def _display_edge(edge: float | None) -> tuple[str, str]:
    if edge is None or pd.isna(edge):
        return "—", "ld-rec-edge-neu"
    val = int(round(float(edge)))
    css = "ld-rec-edge-pos" if val > 0 else ("ld-rec-edge-neg" if val < 0 else "ld-rec-edge-neu")
    sign = "+" if val > 0 else ""
    return f"{sign}{val}", css


def _display_efv(efv: float | None) -> str:
    if efv is None or pd.isna(efv):
        return "—"
    val = float(efv)
    if 0 < val <= 1.5:
        return str(int(round(val * 100)))
    return str(int(round(val)))


def render_live_draft_rec_summary_banner(st: Any, rec_df: Any, *, gaps: list[str] | None = None) -> None:
    if rec_df is None or getattr(rec_df, "empty", True):
        return
    top_name = str(rec_df.iloc[0].get("fullName", "") or "")
    try:
        from live_draft_roster_slots import format_open_position_needs

        need = format_open_position_needs(gaps)
    except ImportError:
        need = ", ".join(gaps or []) or "balanced roster"
    scarcity_note = ""
    if "Scarcity Score" in rec_df.columns:
        scarce = rec_df.sort_values("Scarcity Score", ascending=False).head(1)
        if not scarce.empty:
            sp = str(scarce.iloc[0].get("Primary Position", "") or "")
            if sp:
                scarcity_note = f" {sp} scarcity is rising."
    st.markdown(
        f'<div class="ld-rec-summary-banner"><strong>Recommendation Summary:</strong> '
        f"You need <strong>{need}</strong>.{scarcity_note} "
        f"Top value remaining: <strong>{top_name}</strong>.</div>",
        unsafe_allow_html=True,
    )


def render_live_draft_rec_cards(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    rec_df: Any,
    *,
    max_cards: int = 6,
    multiplayer: bool = False,
    layout: str = "horizontal",
    fmt_rate_4=None,
    fmt_int=None,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
) -> None:
    if rec_df is None or getattr(rec_df, "empty", True):
        st.caption("No recommendations available.")
        return

    rows = list(rec_df.head(max_cards).iterrows())
    if not rows:
        st.caption("No recommendations available.")
        return

    pick_idx = int(room.get("current_pick_index") or 0)
    layout_mode = "stacked" if layout == "stacked" else "compact_horizontal"
    record_rec_card_diagnostics(
        session,
        recommendation_card_layout_mode=layout_mode,
        recommendation_card_width="full_row" if layout_mode == "compact_horizontal" else "stacked",
        recommendation_card_count=len(rows),
        rec_card_render_ts=time.time(),
    )

    gate: dict[str, Any] = {}
    try:
        from draft_actions import draft_action_context, resolve_manual_draft_panel_gate

        gate = resolve_manual_draft_panel_gate(
            session, draft_action_context(session), multiplayer=multiplayer, room=room
        )
    except ImportError:
        gate = {}

    turn_enabled = bool(gate.get("draft_enabled"))
    draft_complete = bool(gate.get("draft_complete"))
    paused = str(room.get("status") or "") == "paused"
    submitting = False
    try:
        from live_draft_pick_timer import is_pick_submitting

        submitting = is_pick_submitting(session)
    except ImportError:
        pass

    for i, (_, r) in enumerate(rows, start=1):
        name = str(r.get("fullName", "Player") or "Player")
        pos = str(r.get("Primary Position", "") or "—")
        edge = pd.to_numeric(r.get("Fantasy Edge", np.nan), errors="coerce")
        surv = pd.to_numeric(r.get("Survival Probability", np.nan), errors="coerce")
        tier_lbl, _tier_css = _rec_tier_badge(i, r)
        edge_txt, _edge_css = _display_edge(edge if pd.notna(edge) else None)
        action = _rec_action_guidance(float(surv) if pd.notna(surv) else None, i)
        pool_df = room.get("pool")
        cfg = dict(room.get("config") or {})
        try:
            from live_draft_category_outlook import player_top_category_strengths

            strengths = player_top_category_strengths(r, pool_df, config=cfg, max_count=2)
        except ImportError:
            strengths = []
        badges = _rec_card_badges(i, r, rec_df, gaps=gaps, category_needs=category_needs)
        explanation = build_draft_insight_text(
            r, badges=badges, strengths=strengths, gaps=gaps, rank=i
        )
        badge_html = "".join(
            f'<span class="ld-rec-badge {css}">{label}</span>' for label, css in badges
        )
        surv_pct = f"{int(round(float(surv) * 100))}% avail next" if pd.notna(surv) else "—"
        player_id = str(r.get("playerID") or r.get("player_id") or "").strip()
        stable_key = player_id or f"name_{name.replace(' ', '_')[:32]}"

        player_available = True
        avail_reason = ""
        try:
            from draft_actions import _live_player_available

            player_available, avail_reason = _live_player_available(session, name)
        except ImportError:
            pass

        draft_enabled = turn_enabled and player_available and not draft_complete and not paused and not submitting
        disable_reason = ""
        if submitting:
            disable_reason = "Submitting pick…"
        elif paused:
            disable_reason = "Draft is paused — resume to pick."
        elif draft_complete:
            disable_reason = "Draft is complete."
        elif not turn_enabled:
            disable_reason = str(gate.get("draft_button_disable_reason") or "Not your turn.")
        elif not player_available:
            disable_reason = avail_reason or f"{name} is not available."

        with st.container(border=True):
            team = str(r.get("Team") or r.get("teamName") or "").strip()
            try:
                from player_photos import (
                    build_draft_score_metrics_html,
                    compact_fantasy_stat_line,
                    get_player_photo_info,
                    inject_player_photo_styles,
                    player_grade_display,
                    render_rec_card_photo_html,
                )

                inject_player_photo_styles(st)
                photo_info = get_player_photo_info(
                    player_id=player_id or None,
                    full_name=name,
                    row=r,
                    use_api=True,
                )
                stat_line = compact_fantasy_stat_line(r)
                photo_html = render_rec_card_photo_html(photo_info, alt=name)
                team_line = f" · {team}" if team else ""
                stat_html = f'<div class="ld-rec-stat-line">{stat_line}</div>' if stat_line else ""
                metrics_html = build_draft_score_metrics_html(
                    r,
                    show_decision_score=True,
                    show_player_grade=True,
                    show_roster_fit=True,
                    show_market_rank=True,
                    show_model_rank=True,
                    show_fantasy_edge=True,
                )
                strength_txt = ""
                if strengths:
                    strength_txt = (
                        f'<div style="font-size:0.82rem;color:#475569;margin-top:2px;">'
                        f"Top strengths: {', '.join(strengths)}</div>"
                    )
                st.markdown(
                    f'<div class="ld-rec-card-header">{photo_html}<div class="ld-rec-card-meta">'
                    f'<div style="font-size:1.05rem;font-weight:800;">{name}</div>'
                    f'<div style="font-size:0.88rem;color:#475569;">{pos}{team_line} · {tier_lbl}</div>'
                    f"{stat_html}{metrics_html}{strength_txt}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
            except ImportError:
                st.markdown(f"**{name}**")
                st.caption(f"{pos} · {tier_lbl}")
            if badge_html:
                st.markdown(f'<div class="ld-rec-badge-row">{badge_html}</div>', unsafe_allow_html=True)
            insight_parts = [surv_pct, action]
            if explanation:
                insight_parts.append(explanation)
            st.caption(" · ".join(insight_parts))
            btn_col, queue_col, detail_col = st.columns([2, 1, 1])
            queued_names = {
                str(x).strip().lower()
                for x in (session.get("draft_queue") or [])
                if str(x).strip()
            }
            already_queued = name.strip().lower() in queued_names
            with btn_col:
                btn_label = f"Draft {name.split()[-1]}" if name else "Draft Player"
                btn_key = f"rec_card_draft_{pick_idx}_{stable_key}"

                def _on_rec_draft_click(
                    _session: dict[str, Any] = session,
                    _name: str = name,
                    _pid: str = player_id,
                    _stable: str = stable_key,
                ) -> None:
                    record_rec_card_diagnostics(
                        _session,
                        rec_card_draft_click_received=True,
                        rec_card_player=_name,
                        rec_card_player_id=_pid or None,
                        rec_card_stable_key=_stable,
                    )
                    try:
                        from draft_ui import queue_manual_draft_pick

                        queue_manual_draft_pick(
                            _session,
                            player_name=_name,
                            player_id=_pid or None,
                            candidate_source="rec_card",
                            pool_source="recommendation_card",
                            widget_key="",
                        )
                    except ImportError:
                        pass

                if draft_enabled:
                    st.button(
                        btn_label,
                        key=btn_key,
                        type="primary",
                        use_container_width=True,
                        on_click=_on_rec_draft_click,
                    )
                else:
                    st.button(
                        btn_label,
                        key=btn_key,
                        disabled=True,
                        use_container_width=True,
                        help=disable_reason[:200],
                    )
            with queue_col:

                def _on_rec_queue_click(
                    _session: dict[str, Any] = session,
                    _name: str = name,
                ) -> None:
                    try:
                        from draft_state import add_player_to_draft_queue

                        add_player_to_draft_queue(_session, _name)
                        try:
                            from baseball_persistent_state import force_save_baseball_state

                            force_save_baseball_state(st, reason="draft_edit")
                        except Exception:
                            pass
                    except ImportError:
                        pass

                if already_queued:
                    st.button(
                        "Queued",
                        key=f"rec_card_queue_{pick_idx}_{stable_key}",
                        disabled=True,
                        use_container_width=True,
                        help=f"{name} is already in your draft queue.",
                    )
                else:
                    st.button(
                        "Add to Queue",
                        key=f"rec_card_queue_{pick_idx}_{stable_key}",
                        use_container_width=True,
                        on_click=_on_rec_queue_click,
                        help=f"Add {name} to your draft queue.",
                    )
            with detail_col:
                with st.expander("Draft Insight", expanded=False):
                    st.caption(
                        build_draft_insight_expander_text(
                            r,
                            badges=badges,
                            strengths=strengths,
                            gaps=gaps,
                            rank=i,
                        )
                    )


def _position_heat_class(dropoff: float, *, strong_cut: float, weak_cut: float) -> str:
    if pd.isna(dropoff):
        return "ld-pos-heat-weak"
    val = float(dropoff)
    if val >= strong_cut:
        return "ld-pos-heat-strong"
    if val >= weak_cut:
        return "ld-pos-heat-moderate"
    return "ld-pos-heat-weak"


def render_position_scarcity_panel(
    st: Any,
    available_df: Any,
    *,
    gaps: list[str] | None = None,
    room: dict[str, Any] | None = None,
) -> None:
    """Demand-adjusted positional scarcity for active draft slots only."""
    if available_df is None or getattr(available_df, "empty", True):
        return
    try:
        from live_draft_pick_scoring import _draft_compute_position_replacement
        from live_draft_roster_slots import get_active_position_codes, get_league_remaining_demand, normalize_draft_slot_config
    except ImportError:
        return
    cfg = normalize_draft_slot_config(dict((room or {}).get("config") or {}))
    active = get_active_position_codes(cfg)
    if not active:
        st.caption("No roster slots configured.")
        return
    league_demand = get_league_remaining_demand(room, cfg)
    _, rows = _draft_compute_position_replacement(
        available_df,
        active_positions=active,
        league_demand=league_demand,
    )
    if not rows:
        return
    try:
        from player_photos import inject_player_photo_styles

        inject_player_photo_styles(st)
    except ImportError:
        pass
    dropoffs = [
        float(r.get("Scarcity Score"))
        for r in rows
        if r.get("Scarcity Score") is not None and not pd.isna(r.get("Scarcity Score"))
    ]
    if not dropoffs:
        return
    strong_cut = float(np.percentile(dropoffs, 66))
    weak_cut = float(np.percentile(dropoffs, 33))
    open_gaps = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    cells: list[str] = []
    scarcity_tip = (
        "Higher scores indicate fewer quality players remain relative to teams that still need the position."
    )
    for row in sorted(rows, key=lambda x: str(x.get("Position") or "")):
        pos = str(row.get("Position") or "").strip()
        if not pos:
            continue
        score = row.get("Scarcity Score")
        css = _position_heat_class(score, strong_cut=strong_cut, weak_cut=weak_cut)
        if pos in open_gaps:
            css += " ld-pos-heat-need"
        demand = int(row.get("Remaining Demand") or 0)
        quality = int(row.get("Quality Supply") or 0)
        try:
            score_txt = f"+{float(score):.1f}" if pd.notna(score) else "—"
        except (TypeError, ValueError):
            score_txt = "—"
        need_mark = " *" if pos in open_gaps else ""
        cells.append(
            f'<div class="ld-pos-heat-cell {css}" title="{scarcity_tip}">'
            f'<span class="ld-pos-heat-label">{pos}{need_mark}</span>'
            f'<span class="ld-pos-heat-val">Scarcity Score: {score_txt}</span>'
            f'<span class="ld-pos-heat-val" style="font-size:0.72rem;">'
            f'{quality} quality · {demand} slots open league-wide</span></div>'
        )
    if not cells:
        return
    st.markdown(
        '<div class="ld-category-outlook-panel">'
        '<div class="ld-panel-title">Position Scarcity Map</div>'
        '<div style="font-size:0.8rem;color:#64748b;margin-bottom:4px;">'
        "<strong>Thin position</strong> = few quality players remain relative to remaining roster demand. "
        "🟢 Low scarcity · 🟡 Moderate · 🔴 High scarcity. * = open roster need.</div>"
        f'<div class="ld-pos-heat-grid">{"".join(cells)}</div></div>',
        unsafe_allow_html=True,
    )
