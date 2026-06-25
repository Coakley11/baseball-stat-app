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
    teams_txt = ", ".join(teams) if teams else "—"
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
                <strong>Teams:</strong> {teams_txt}
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


def _rec_plain_explanation(row: Any, pos: str) -> str:
    fit = pd.to_numeric(row.get("Positional Fit", np.nan), errors="coerce")
    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    sleeper = pd.to_numeric(row.get("Sleeper Score", np.nan), errors="coerce")
    if pd.notna(fit) and float(fit) >= 0.65:
        return f"Fills your {pos} need with strong projection."
    if pd.notna(scarcity) and float(scarcity) >= 0.6:
        return "Scarce position with few alternatives left."
    if pd.notna(sleeper) and float(sleeper) >= 0.55:
        return "Undervalued upside compared to market rank."
    if pd.notna(edge) and float(edge) >= 8:
        return "Best value remaining compared to ADP."
    return "Strong combination of safety and upside."


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
        explanation = _rec_plain_explanation(r, pos)
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
            st.markdown(f"**{name}**")
            st.caption(f"{pos} · {tier_lbl}")
            st.caption(f"Fantasy Edge {edge_txt} · {surv_pct} · {action}")
            st.caption(f"Reason: {explanation}")
            btn_col, detail_col = st.columns([2, 1])
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
            with detail_col:
                with st.expander("Details", expanded=False):
                    detail_cols = [
                        c
                        for c in (
                            "Model Rank",
                            "Market Rank",
                            "Sleeper Score",
                            "Positional Fit",
                            "Scarcity Score",
                            "Draft Fit Score",
                            "Decision Score",
                            "Survival Label",
                            "Trend Signal",
                            "Expected Fantasy Value",
                        )
                        if c in rec_df.columns
                    ]
                    for col in detail_cols:
                        val = r.get(col)
                        if pd.notna(val):
                            st.text(f"{col}: {val}")
