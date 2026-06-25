"""Live Draft Room presentation — styles, badges, cards (no draft logic)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


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


def render_live_draft_rec_cards(st: Any, rec_df: Any, *, max_cards: int = 6, fmt_rate_4=None, fmt_int=None) -> None:
    if rec_df is None or getattr(rec_df, "empty", True):
        st.caption("No recommendations available.")
        return

    rows = list(rec_df.head(max_cards).iterrows())
    if not rows:
        st.caption("No recommendations available.")
        return

    cols = st.columns(min(3, len(rows)))
    for i, (_, r) in enumerate(rows, start=1):
        name = str(r.get("fullName", "Player") or "Player")
        pos = str(r.get("Primary Position", "") or "—")
        team = str(r.get("Team", "") or r.get("MLB Team", "") or "")
        efv = pd.to_numeric(r.get("Expected Fantasy Value", np.nan), errors="coerce")
        edge = pd.to_numeric(r.get("Fantasy Edge", np.nan), errors="coerce")
        surv = pd.to_numeric(r.get("Survival Probability", np.nan), errors="coerce")
        scarcity = pd.to_numeric(r.get("Scarcity Score", np.nan), errors="coerce")
        decision = pd.to_numeric(r.get("Decision Score", np.nan), errors="coerce")
        draft_fit = pd.to_numeric(r.get("Draft Fit Score", np.nan), errors="coerce")
        tier_lbl, tier_css = _rec_tier_badge(i, r)
        edge_txt, edge_css = _display_edge(edge if pd.notna(edge) else None)
        action = _rec_action_guidance(float(surv) if pd.notna(surv) else None, i)
        explanation = _rec_plain_explanation(r, pos)
        surv_txt = f"{int(round(float(surv) * 100))}% Chance Available Next Round" if pd.notna(surv) else "—"
        scarcity_txt = f"{int(round(float(scarcity) * 100))}%" if pd.notna(scarcity) else "—"
        decision_txt = f"{int(round(float(decision) * 100))}" if pd.notna(decision) and float(decision) <= 1.5 else (
            f"{int(round(float(decision)))}" if pd.notna(decision) else "—"
        )
        fit_txt = f"{int(round(float(draft_fit) * 100))}%" if pd.notna(draft_fit) and float(draft_fit) <= 1.5 else (
            f"{int(round(float(draft_fit)))}" if pd.notna(draft_fit) else "—"
        )

        with cols[(i - 1) % len(cols)]:
            with st.container(border=True):
                st.caption(_rec_rank_label(i))
                st.markdown(f"## {name}")
                st.markdown(
                    f'`{pos}` · '
                    f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
                    f'font-size:12px;font-weight:700;" class="{tier_css}">{tier_lbl}</span>',
                    unsafe_allow_html=True,
                )
                if team:
                    st.caption(team)
                st.markdown(
                    f'<div style="font-size:28px;line-height:1.1;margin:8px 0 4px 0;" class="{edge_css}">'
                    f'Fantasy Edge {edge_txt}</div>',
                    unsafe_allow_html=True,
                )
                st.caption(f"Expected Value: {_display_efv(efv if pd.notna(efv) else None)}")
                st.markdown(f"**{surv_txt}**")
                st.caption("Chance Available Next Round")
                st.markdown(f"Position Scarcity: **{scarcity_txt}**")
                st.caption(f"Decision Score: {decision_txt} · Draft Fit: {fit_txt}")
                st.info(explanation)
                st.markdown(f"**{action}**")
                with st.expander("Show Details", expanded=False):
                    detail_cols = [c for c in (
                        "Model Rank", "Market Rank", "Sleeper Score", "Positional Fit",
                        "Survival Label", "Trend Signal",
                    ) if c in rec_df.columns]
                    for col in detail_cols:
                        val = r.get(col)
                        if pd.notna(val):
                            st.text(f"{col}: {val}")
