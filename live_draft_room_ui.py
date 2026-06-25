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


def render_draft_room_code_panel(st: Any, code: str) -> None:
    code = str(code or "").strip().upper()
    if not code:
        return
    st.markdown(
        f"""
        <div class="ld-room-code-panel">
            <div>
                <div class="ld-room-code-label">Draft Room Code</div>
                <div class="ld-room-code-value">{code}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Share this code so other managers can join your live draft.")


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


def render_live_draft_rec_cards(st: Any, rec_df: Any, *, max_cards: int = 6, fmt_rate_4=None, fmt_int=None) -> None:
    if rec_df is None or getattr(rec_df, "empty", True):
        st.caption("No recommendations available.")
        return

    def _fmt_rate(v):
        if fmt_rate_4:
            return fmt_rate_4(v)
        num = pd.to_numeric(v, errors="coerce")
        return f"{num:.1f}" if pd.notna(num) else "—"

    def _fmt_int(v):
        if fmt_int:
            return fmt_int(v)
        num = pd.to_numeric(v, errors="coerce")
        return f"{int(num)}" if pd.notna(num) else "—"

    rows = list(rec_df.head(max_cards).iterrows())
    if not rows:
        st.caption("No recommendations available.")
        return
    cols = st.columns(min(3, len(rows)))
    for i, (_, r) in enumerate(rows, start=1):
        name = str(r.get("fullName", "Player") or "Player")
        pos = str(r.get("Primary Position", "") or "—")
        efv = pd.to_numeric(r.get("Expected Fantasy Value", np.nan), errors="coerce")
        edge = pd.to_numeric(r.get("Fantasy Edge", np.nan), errors="coerce")
        surv = pd.to_numeric(r.get("Survival Probability", np.nan), errors="coerce")
        surv_lbl = str(r.get("Survival Label", "") or "")
        tier = "Top pick" if i == 1 else ("Strong fit" if i <= 3 else "Value option")
        surv_pct = f"{surv * 100:.0f}% survival at next pick" if pd.notna(surv) else ""
        with cols[(i - 1) % len(cols)]:
            with st.container(border=True):
                st.markdown(f"**#{i} · {tier}**")
                st.markdown(f"**{name}**")
                st.caption(f"{pos} · EFV {_fmt_rate(efv)} · Edge {_fmt_int(edge)}")
                if surv_pct or surv_lbl:
                    st.caption(f"{surv_pct}{(' · ' + surv_lbl) if surv_lbl else ''}")
