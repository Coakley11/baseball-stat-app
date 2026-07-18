"""Live Draft Room presentation — styles, badges, cards (no draft logic)."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

LIVE_DRAFT_REC_DIAG_KEY = "_live_draft_rec_diag"
VISIBLE_REC_RENDER_INPUT_KEY = "_live_draft_visible_rec_render_input"


def record_rec_card_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    diag = dict(session.get(LIVE_DRAFT_REC_DIAG_KEY) or {})
    diag.update(fields)
    session[LIVE_DRAFT_REC_DIAG_KEY] = diag
    return diag


def build_visible_rec_render_input(
    *,
    rec_df: Any,
    available_df: Any = None,
    on_clock_team: str = "",
    max_cards: int = 6,
    defer_recs: bool = False,
    skip_for_setup: bool = False,
    expensive_ok: bool = True,
    cache_key: Any = None,
    rec_cache_entry: Any = None,
    room_status: str = "",
) -> dict[str, Any]:
    """Final paint-pass inputs for recommendation cards (not an earlier sidebar snapshot)."""
    avail_n = 0
    if available_df is not None and not getattr(available_df, "empty", True):
        try:
            avail_n = int(len(available_df))
        except Exception:
            avail_n = 0
    names: list[str] = []
    rec_n = 0
    if rec_df is not None and not getattr(rec_df, "empty", True):
        try:
            rec_n = int(len(rec_df))
            col = "fullName" if "fullName" in rec_df.columns else ("Player" if "Player" in rec_df.columns else None)
            if col:
                names = [str(x).strip() for x in rec_df[col].head(max_cards).tolist() if str(x).strip()]
        except Exception:
            names = []
    cache_state = "missing"
    if isinstance(rec_cache_entry, dict):
        cached_top = rec_cache_entry.get("top_rec")
        cached_n = 0
        if cached_top is not None and not getattr(cached_top, "empty", True):
            try:
                cached_n = int(len(cached_top))
            except Exception:
                cached_n = 0
        key_match = rec_cache_entry.get("key") == cache_key if cache_key is not None else None
        if cached_n <= 0:
            cache_state = "empty"
        elif key_match is True:
            cache_state = f"hit({cached_n})"
        elif key_match is False:
            cache_state = f"stale({cached_n})"
        else:
            cache_state = f"present({cached_n})"
    elif defer_recs:
        cache_state = "deferred_no_entry"
    return {
        "available_player_count": avail_n,
        "recommendation_count": rec_n,
        "top_recommendation_names": names,
        "card_render_input": list(names),
        "on_clock_team": str(on_clock_team or "").strip() or "—",
        "scoring_cache_state": cache_state,
        "defer_recs": bool(defer_recs),
        "skip_for_setup": bool(skip_for_setup),
        "expensive_ok": bool(expensive_ok),
        "room_status": str(room_status or "").strip() or "—",
        "cache_key": str(cache_key)[:120] if cache_key is not None else "",
    }


def render_visible_rec_render_input_diagnostic(
    st: Any,
    session: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """On-page banner: exact recommendation-card render input (Developer Mode only)."""
    session[VISIBLE_REC_RENDER_INPUT_KEY] = dict(payload)
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        if not developer_mode_checkbox_enabled(st=st):
            return
    except ImportError:
        if not (
            bool(session.get("app_developer_mode"))
            or bool(session.get("_suite_developer_mode_user"))
        ):
            return
    names = list(payload.get("card_render_input") or payload.get("top_recommendation_names") or [])
    st.markdown(
        f"**VISIBLE REC RENDER INPUT:** `{names}`  \n"
        f"available=`{payload.get('available_player_count', 0)}` · "
        f"recs=`{payload.get('recommendation_count', 0)}` · "
        f"on_clock=`{payload.get('on_clock_team', '—')}` · "
        f"scoring_cache=`{payload.get('scoring_cache_state', '—')}` · "
        f"status=`{payload.get('room_status', '—')}` · "
        f"defer=`{payload.get('defer_recs')}` · "
        f"skip_setup=`{payload.get('skip_for_setup')}` · "
        f"expensive_ok=`{payload.get('expensive_ok')}`"
    )
    if not names:
        st.caption(
            "Card paint input is empty this pass — cards will not appear until "
            "recommendation rows are non-empty at this banner."
        )


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
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 8px;
            margin-bottom: 8px;
        }
        .live-rec-card {
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #dbe3ee;
            border-radius: 12px;
            padding: 10px 12px 8px 12px;
            box-shadow: 0 1px 4px rgba(15,23,42,0.04);
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
        .ld-rec-badge-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 6px 0; }
        .ld-rec-badge {
            display: inline-block;
            padding: 3px 9px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 800;
            background: #dbeafe;
            color: #1e40af;
            border: 1px solid #93c5fd;
            line-height: 1.2;
        }
        .ld-rec-badge.rank { font-size: 10px; opacity: 0.88; font-weight: 700; }
        .ld-rec-badge.gold { background: #fef3c7; color: #92400e; border-color: #fcd34d; }
        .ld-rec-badge.need { background: #ede9fe; color: #5b21b6; border-color: #c4b5fd; }
        .ld-rec-badge.fire { background: #ffedd5; color: #c2410c; border-color: #fdba74; }
        .ld-rec-badge.safe { background: #f0fdf4; color: #166534; border-color: #86efac; }
        .ld-rec-card-reason {
            font-size: 0.9rem; font-weight: 700; color: #1e40af;
            margin: 2px 0 4px 0; line-height: 1.4;
        }
        .ld-rec-card-caption {
            font-size: 0.82rem; color: #64748b; line-height: 1.45;
            margin-bottom: 6px;
        }
        .ld-rec-detail-grid { margin-top: 2px; }
        .ld-rec-detail-row {
            display: flex;
            flex-wrap: wrap;
            gap: 6px 14px;
            margin-bottom: 8px;
        }
        .ld-rec-detail-cell { flex: 1 1 150px; min-width: 130px; }
        .ld-rec-detail-label {
            font-size: 0.72rem;
            font-weight: 800;
            color: #334155;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .ld-rec-detail-value {
            font-size: 0.86rem;
            color: #1e293b;
            line-height: 1.45;
            margin-top: 2px;
        }
        .ld-rec-detail-grid { margin-top: 4px; max-width: 100%; }
        .ld-rec-detail-cell { flex: 1 1 180px; min-width: 160px; }

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
            .ld-rec-summary-banner { font-size: 13px; padding: 10px 12px; margin-bottom: 10px; }
            .ld-rec-card-header { gap: 10px; margin-bottom: 4px; }
            .ld-rec-card-photo img { width: 52px; height: 52px; }
            .ld-rec-badge-row { gap: 4px; margin: 6px 0 4px 0; }
            .ld-rec-card-reason { font-size: 0.85rem; }
            .ld-roster-tracker-panel,
            .ld-category-outlook-panel { padding: 10px 12px; margin-bottom: 10px; }
            .ld-pos-heat-grid { grid-template-columns: repeat(auto-fill, minmax(72px, 1fr)); gap: 6px; }
            div[data-testid="stDataFrame"] { font-size: 12px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    try:
        from live_draft_ux import inject_draft_animation_styles, inject_position_color_styles

        extra = inject_position_color_styles() + inject_draft_animation_styles()
        if extra.strip():
            st.markdown(f"<style>{extra}</style>", unsafe_allow_html=True)
    except ImportError:
        pass


def render_draft_room_code_panel(
    st: Any,
    code: str,
    *,
    join_url: str | None = None,
    show_copy: bool = True,
    context_label: str | None = None,
    key_prefix: str = "live_draft_room_code",
) -> None:
    """Prominent shareable room code — waiting room and active draft.

    ``key_prefix`` must be unique per call site in a single page run so Copy /
    code widgets never collide (StreamlitDuplicateElementKey).
    """
    code = str(code or "").strip().upper()
    if not code:
        return
    prefix = str(key_prefix or "live_draft_room_code").strip() or "live_draft_room_code"
    del show_copy, context_label, join_url  # retained for call-site compatibility
    value_dom_id = f"{prefix}_value_{code}"
    st.markdown(
        f"""
        <div class="ld-room-code-panel" id="{prefix}_panel_{code}">
            <div>
                <div class="ld-room-code-label">ROOM CODE</div>
                <div class="ld-room-code-value" id="{value_dom_id}">{code}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    # Intentionally no duplicate st.code, no Copy button, no share caption —
    # the large boxed code is the single source of truth.


def render_live_draft_room_code_header(
    st: Any,
    session: dict[str, Any],
    *,
    multiplayer: bool,
    join_url: str = "",
    draft_in_progress: bool = False,
    key_prefix: str | None = None,
) -> None:
    """Show room code, copy affordance, and missing-code warning near draft header.

    Visible in the waiting room and after the draft starts (not invitation-only).
    Canonical room-code panel for Shared Multiplayer — call at most once per page state.
    """
    code = ""
    try:
        from draft_room_context import resolve_shared_room_code

        code = resolve_shared_room_code(session)
    except ImportError:
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()

    if code:
        label = (
            "Share this code so other managers can join"
            if not draft_in_progress
            else "Room code (same for commissioner and all participants)"
        )
        prefix = str(key_prefix or "").strip() or (
            "live_draft_active_header" if draft_in_progress else "live_draft_waiting_header"
        )
        render_draft_room_code_panel(
            st,
            code,
            join_url=join_url or None,
            context_label=label,
            key_prefix=prefix,
        )
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
        from live_draft_setup_mode import resolve_active_live_draft_mode

        auth_doc = session.get("_shared_lobby_authority_doc")
        active = resolve_active_live_draft_mode(
            session,
            room=room if isinstance(room, dict) else None,
            document=auth_doc if isinstance(auth_doc, dict) else None,
        )
        solo = bool(active.get("is_solo"))
        code = str(active.get("room_code") or "").strip().upper()
        if solo:
            mode_label = "Solo Draft"
            teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
            mode_detail = (
                f"You control all teams ({len(teams)} teams)" if len(teams) > 1 else "You control all teams"
            )
        else:
            mode_label = "Shared Multiplayer"
            mode_detail = ""
            from draft_room_context import get_global_draft_context, resolve_shared_room_code

            ctx = get_global_draft_context(session)
            if not code:
                code = str(resolve_shared_room_code(session) or "").strip().upper()
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
    # Pure HTML only — never inject markdown **bold** into unsafe_allow_html blocks.
    live_badge = " · <strong>Live</strong>" if draft_in_progress else ""
    status_txt = str(status_label or room.get("status") or "—").replace("_", " ").title()

    if solo:
        st.markdown(
            f"""
            <div class="ld-room-header">
                <div class="ld-rh-title">Live Draft Room · {mode_label}</div>
                <div class="ld-rh-meta">
                    <strong>Teams:</strong> {teams_txt}<br/>
                    {mode_detail}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    code_block = (
        f'<div class="ld-rh-code">Room Code: <strong>{code}</strong></div>'
        if code
        else '<span style="color:#b45309;">Code missing</span>'
    )
    role_txt = f"<strong>Your role:</strong> {role} · " if role else ""
    team_line = f"<strong>Your Fantasy Team:</strong> {assigned_team or '—'}"
    st.markdown(
        f"""
        <div class="ld-room-header">
            <div class="ld-rh-title">Live Draft Room · {mode_label}</div>
            {code_block}
            <div class="ld-rh-meta">
                {role_txt}
                {team_line} ·
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
        # Canonical copyable panel during active (and non-lobby) shared drafts.
        render_draft_room_code_panel(
            st,
            code,
            context_label=(
                "Room code (same for commissioner and all participants)"
                if draft_in_progress
                else "Share this code so other managers can join"
            ),
            key_prefix="live_draft_active_header" if draft_in_progress else "live_draft_room_header",
        )
    else:
        st.error("Could not create shared room. This draft cannot be joined by others.")


def render_live_draft_league_header(
    st: Any,
    *,
    league_name: str,
    teams: list[str],
    solo: bool = True,
    pick_label: str = "",
    round_no: str = "",
    on_clock_team: str = "",
    live: bool = False,
) -> None:
    """Compact page header — league line + single status line (no duplicate badges)."""
    league = str(league_name or "League").strip()
    team_names = [str(t).strip() for t in (teams or []) if str(t).strip()]
    if solo and len(team_names) >= 2:
        subtitle = f"Solo Draft · {' vs '.join(team_names[:4])}"
    elif solo:
        subtitle = "Solo Draft"
    else:
        subtitle = " · ".join(team_names[:4]) if team_names else "Multiplayer Draft"
    st.markdown(f"### {league}")
    st.caption(subtitle)
    status_parts: list[str] = []
    if pick_label:
        status_parts.append(str(pick_label).replace("Pick ", "Pick ").replace(" / ", " of "))
    if round_no and str(round_no) != "—":
        status_parts.append(f"Round {round_no}")
    if on_clock_team and str(on_clock_team) != "—":
        status_parts.append(f"On Clock: {on_clock_team}")
    if live:
        status_parts.append("Live")
    if status_parts:
        st.caption(" · ".join(status_parts))


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
    bar_html_parts: list[str] = []
    for b in bars:
        cat = str(b.get("category") or "")
        level_num = max(0, min(5, int(b.get("level_num") or 0)))
        level = str(b.get("level") or "")
        # Always show roster-derived strength (not static category importance stars).
        if level_num > 0:
            stars = "★" * level_num + "☆" * (5 - level_num)
            bar_html_parts.append(f'<div class="ld-cat-bar-row">{cat}  {stars}  {level}</div>')
        else:
            bar_html_parts.append(
                f'<div class="ld-cat-bar-row">{cat}  {b.get("bar", "")}  {level}</div>'
            )
    bar_html = "".join(bar_html_parts)
    needs = outlook.get("needs_attention") or []
    strengths = outlook.get("strengths") or []
    insight_parts = []
    if outlook.get("pre_draft_neutral"):
        insight_parts.append("Neutral baseline — outlook updates after the first pick.")
    else:
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
    strengths: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Return (label, css_class) badge tuples for a recommendation card."""
    try:
        from live_draft_rec_badges import build_smart_recommendation_badges

        return build_smart_recommendation_badges(
            rank,
            row,
            rec_df,
            gaps=gaps,
            category_needs=category_needs,
            strengths=strengths,
        )
    except ImportError:
        pass
    return []


def _rec_tier_badge(rank: int, row: Any, *, badges: list[tuple[str, str]] | None = None) -> tuple[str, str]:
    if badges:
        label, css = badges[0]
        css_map = {"gold": "ld-rec-tier-best", "fire": "ld-rec-tier-value", "need": "ld-rec-tier-need", "safe": "ld-rec-tier-safe"}
        return label, css_map.get(css, "ld-rec-tier-strong")
    fit = pd.to_numeric(row.get("Positional Fit", np.nan), errors="coerce")
    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    if rank == 1:
        return "Best Pick", "ld-rec-tier-best"
    if pd.notna(edge) and float(edge) >= 8:
        return "High Value", "ld-rec-tier-value"
    if pd.notna(fit) and float(fit) >= 0.65:
        return "Strong Fit", "ld-rec-tier-strong"
    return "Safe Pick", "ld-rec-tier-safe"


def build_rec_card_detail_body(
    row: Any,
    *,
    badges: list[tuple[str, str]] | None = None,
    strengths: list[str] | None = None,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    rank: int = 0,
) -> str:
    """Expanded analytics for Why Recommended — compact grid without repeating card facts."""
    cells: list[tuple[str, str]] = []
    pos = str(row.get("Primary Position") or "—")

    if category_needs:
        cells.append(("Team needs", ", ".join(str(c) for c in category_needs[:4])))

    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    if pd.notna(scarcity) and float(scarcity) >= 0.5:
        cells.append(("Scarcity", f"{pos} tier thinning ({float(scarcity):.2f})"))

    mkt = pd.to_numeric(row.get("Market Rank", np.nan), errors="coerce")
    mdl = pd.to_numeric(row.get("Model Rank", np.nan), errors="coerce")
    if pd.notna(mkt) and pd.notna(mdl):
        cells.append(
            ("Market value", f"Model {int(round(float(mdl)))} vs market {int(round(float(mkt)))}")
        )

    dfs = pd.to_numeric(row.get("Draft Fit Score", np.nan), errors="coerce")
    if gaps and pos in gaps and pd.notna(dfs):
        cells.append(("Roster fit", f"Fills an open {pos} position<br/>Fit Score: {float(dfs):.2f}"))
    elif pd.notna(dfs):
        cells.append(("Roster fit", f"Fit Score: {float(dfs):.2f}"))

    risk = pd.to_numeric(row.get("Risk Penalty", np.nan), errors="coerce")
    conf = pd.to_numeric(row.get("Projection Confidence", np.nan), errors="coerce")
    if pd.notna(risk) or pd.notna(conf):
        risk_txt = "lower" if pd.notna(risk) and float(risk) <= 0.35 else "moderate"
        if pd.notna(conf) and float(conf) >= 0.65:
            risk_txt = "low"
        cells.append(("Risk level", f"{risk_txt} projection volatility"))

    if not cells:
        return "Balanced upside and availability at this pick."

    row_html: list[str] = []
    for i in range(0, len(cells), 3):
        chunk = cells[i : i + 3]
        row_cells = "".join(
            f'<div class="ld-rec-detail-cell"><div class="ld-rec-detail-label">{label}</div>'
            f'<div class="ld-rec-detail-value">{value}</div></div>'
            for label, value in chunk
        )
        row_html.append(f'<div class="ld-rec-detail-row">{row_cells}</div>')
    return f'<div class="ld-rec-detail-grid">{"".join(row_html)}</div>'


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
    skip_survival: bool = False,
) -> str:
    """Non-redundant guidance below badges — never restates badge labels."""
    badge_labels = " ".join(label for label, _css in (badges or []))
    pos = str(row.get("Primary Position") or "")
    parts: list[str] = []

    if strengths:
        parts.append(f"Strengthens {' and '.join(strengths)}.")

    surv = pd.to_numeric(row.get("Survival Probability", np.nan), errors="coerce")
    if not skip_survival and pd.notna(surv):
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
    skip_survival: bool = False,
) -> str:
    """Longer draft guidance for the Draft Insight expander (no duplicate stats)."""
    lead = build_draft_insight_text(
        row, badges=badges, strengths=strengths, gaps=gaps, rank=rank, skip_survival=skip_survival
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
        parts.append(f"helps your {weak} outlook")

    if strengths:
        parts.append(f"adds {'/'.join(strengths[:2])} production")

    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    if pd.notna(edge) and abs(float(edge)) >= 5:
        sign = "+" if float(edge) > 0 else ""
        parts.append(f"{sign}{int(round(float(edge)))} vs market")

    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    if pd.notna(scarcity) and float(scarcity) >= 0.6:
        parts.append(f"{pos} pool thinning")

    if include_position_need:
        fit = pd.to_numeric(row.get("Positional Fit", np.nan), errors="coerce")
        if gaps and str(pos) in gaps and pd.notna(fit) and float(fit) >= 0.5:
            open_of = sum(1 for g in gaps if g == "OF")
            if str(pos) == "OF" and open_of >= 2:
                parts.append(f"fills {open_of} OF slots")
            else:
                parts.append(f"fills open {pos}")

    if not parts:
        return "Balanced upside, roster fit, and availability."
    return " · ".join(parts[:4]) + "."


def build_rec_card_why_bullets(
    rank: int,
    row: Any,
    rec_df: Any,
    *,
    badges: list[tuple[str, str]] | None = None,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    strengths: list[str] | None = None,
) -> list[str]:
    """Deduped Why Recommended bullets — each idea appears once."""
    bullets: list[str] = []
    seen: set[str] = set()
    pos = str(row.get("Primary Position") or "").strip()
    badge_labels = {str(label) for label, _css in (badges or [])}

    def _add(text: str, *, key: str = "") -> None:
        t = str(text or "").strip()
        if not t:
            return
        dedupe_key = (key or t).lower()
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        bullets.append(t)

    if gaps and pos in gaps:
        open_of = sum(1 for g in gaps if g == "OF")
        if pos == "OF" and open_of >= 2:
            try:
                from live_draft_ux import format_of_slot_eligibility

                _add(format_of_slot_eligibility(open_of), key="fills_position")
            except ImportError:
                _add(f"Fills {open_of} of your remaining OF slots", key="fills_position")
        else:
            _add(f"Fills one of your remaining {pos} slots", key="fills_position")

    if category_needs:
        labels = [str(c).strip() for c in category_needs[:2] if str(c).strip()]
        if labels:
            if len(labels) == 1:
                _add(f"Helps address {labels[0]} deficit", key="category_need")
            else:
                _add(f"Helps address {' and '.join(labels)} deficits", key="category_need")
    elif strengths:
        _add(f"Strong {'/'.join(strengths[:2])} profile", key="category_strength")

    scarcity = pd.to_numeric(row.get("Scarcity Score", np.nan), errors="coerce")
    if pd.notna(scarcity) and float(scarcity) >= 0.55:
        try:
            from live_draft_ux import estimate_tier1_remaining, format_scarcity_explanation

            tier1 = estimate_tier1_remaining(rec_df, pos) if pos else 0
            _add(
                format_scarcity_explanation(
                    pos or "Position",
                    tier1_remaining=tier1,
                    picks_until_dropoff=3,
                    scarcity_score=float(scarcity),
                ),
                key="scarcity",
            )
        except ImportError:
            if pos:
                _add(f"{pos} depth is thinning rapidly", key="scarcity")
            else:
                _add("Position depth is thinning rapidly", key="scarcity")

    mkt = pd.to_numeric(row.get("Market Rank", np.nan), errors="coerce")
    mdl = pd.to_numeric(row.get("Model Rank", np.nan), errors="coerce")
    if pd.notna(mkt) and pd.notna(mdl):
        _add(
            f"Model rank {int(round(float(mdl)))} vs market rank {int(round(float(mkt)))}",
            key="rank_edge",
        )

    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    if pd.notna(edge) and float(edge) >= 8 and "rank_edge" not in seen:
        _add(f"Strong market edge (+{int(round(float(edge)))})", key="market_edge")

    surv = pd.to_numeric(row.get("Survival Probability", np.nan), errors="coerce")
    if pd.notna(surv) and float(surv) < 0.4 and "scarcity" not in seen:
        pct = int(round(float(surv) * 100))
        _add(f"Only {pct}% likely available next round", key="availability")

    if rank == 1 and not bullets:
        _add("Best overall pick on the board", key="best_overall")
    elif not bullets:
        _add("Balanced upside, roster fit, and availability", key="default")
    return bullets[:3]


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
) -> pd.DataFrame:
    """Add a single ``Why this pick`` column to a recommendation table."""
    if rec_df is None or not isinstance(rec_df, pd.DataFrame):
        return pd.DataFrame()
    if rec_df.empty:
        return rec_df.copy()
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
        val = val * 100.0
    return f"{round(val, 1):.1f}"


def render_live_draft_rec_summary_banner(st: Any, rec_df: Any, *, gaps: list[str] | None = None) -> None:
    if rec_df is None or getattr(rec_df, "empty", True):
        return
    top_name = str(rec_df.iloc[0].get("fullName", "") or "")
    try:
        from draft_needs import display_position_needs_label

        need = display_position_needs_label(gaps)
    except ImportError:
        try:
            from live_draft_roster_slots import format_open_position_needs

            need = format_open_position_needs(gaps)
        except ImportError:
            need = ", ".join(gaps or []) or "All Positions"
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
        pool_df = room.get("pool")
        cfg = dict(room.get("config") or {})
        try:
            from live_draft_category_outlook import player_top_category_strengths
            from live_draft_ux import describe_strengths

            raw_strengths = player_top_category_strengths(r, pool_df, config=cfg, max_count=2)
            strengths = describe_strengths(raw_strengths, max_count=2)
        except ImportError:
            strengths = []
        badges = _rec_card_badges(
            i, r, rec_df, gaps=gaps, category_needs=category_needs, strengths=strengths
        )
        tier_lbl, _tier_css = _rec_tier_badge(i, r, badges=badges)
        edge_txt, _edge_css = _display_edge(edge if pd.notna(edge) else None)
        action = _rec_action_guidance(float(surv) if pd.notna(surv) else None, i)
        try:
            from live_draft_rec_badges import primary_recommendation_reason

            headline = primary_recommendation_reason(
                i, r, badges=badges, strengths=strengths, gaps=gaps
            )
        except ImportError:
            headline = tier_lbl
        explanation = build_draft_insight_text(
            r, badges=badges, strengths=None, gaps=gaps, rank=i
        )
        badge_html = "".join(
            f'<span class="ld-rec-badge {css}{" rank" if label in ("Best Overall", "Second Best", "Third Best") else ""}">{label}</span>'
            for label, css in badges
        )
        surv_pct = f"{int(round(float(surv) * 100))}% avail next round" if pd.notna(surv) else "—"
        player_id = str(r.get("playerID") or r.get("player_id") or "").strip()
        stable_key = player_id or f"name_{name.replace(' ', '_')[:32]}"

        player_available = True
        avail_reason = ""
        draft_gate: dict[str, Any] = {}
        try:
            from draft_actions import resolve_player_draft_gate

            draft_gate = resolve_player_draft_gate(session, name)
            player_available = bool(draft_gate.get("allowed"))
            avail_reason = str(draft_gate.get("disable_message") or "")
        except ImportError:
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
                    show_market_rank=False,
                    show_model_rank=False,
                    show_fantasy_edge=True,
                )
                strength_txt = ""
                if strengths:
                    strength_txt = (
                        f'<div style="font-size:0.82rem;color:#475569;margin-top:4px;">'
                        f"Top strengths: {', '.join(strengths)}</div>"
                    )
                try:
                    from live_draft_ux import confidence_label_from_score, position_color

                    decision = pd.to_numeric(r.get("Decision Score", np.nan), errors="coerce")
                    conf_label, conf_stars = confidence_label_from_score(
                        float(decision) if pd.notna(decision) else None
                    )
                    confidence_txt = (
                        f'<div style="font-size:0.8rem;color:#334155;margin-top:6px;">'
                        f"<strong>{conf_label}</strong> {conf_stars}</div>"
                    )
                except ImportError:
                    confidence_txt = ""
                pos_color = "#475569"
                try:
                    from live_draft_ux import position_color

                    pos_color = position_color(pos)
                except ImportError:
                    pass
                meta_line = f'<span style="color:{pos_color};font-weight:700;">{pos}</span>{team_line}' if not badges else f'<span style="color:{pos_color};font-weight:700;">{pos}</span>{team_line}'
                st.markdown(
                    f'<div class="ld-rec-card-header">{photo_html}<div class="ld-rec-card-meta">'
                    f'<div style="font-size:1.05rem;font-weight:800;line-height:1.25;">{name}</div>'
                    f'<div style="font-size:0.88rem;color:#475569;">{meta_line}</div>'
                    f"{stat_html}{metrics_html}{strength_txt}{confidence_txt}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
            except ImportError:
                st.markdown(f"**{name}**")
                st.caption(f"{pos}")
            if badge_html:
                st.markdown(f'<div class="ld-rec-badge-row">{badge_html}</div>', unsafe_allow_html=True)
            btn_col, queue_col, detail_col = st.columns([2, 1, 1])
            queued_names = {
                str(x).strip().lower()
                for x in (session.get("draft_queue") or [])
                if str(x).strip()
            }
            already_queued = name.strip().lower() in queued_names
            with btn_col:
                btn_label = "🔴 Draft Player"
                btn_key = f"rec_card_draft_{pick_idx}_{stable_key}"

                def _on_rec_draft_click(
                    _session: dict[str, Any] = session,
                    _name: str = name,
                    _pid: str = player_id,
                    _stable: str = stable_key,
                ) -> None:
                    try:
                        from live_draft_ux_latency import ACTION_DRAFT_REC, note_ux_action

                        note_ux_action(
                            _session,
                            ACTION_DRAFT_REC,
                            source="rec_card_draft",
                            detail=_name,
                        )
                    except ImportError:
                        pass
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
                    before = [str(x).strip() for x in (_session.get("draft_queue") or []) if str(x).strip()]
                    try:
                        from live_draft_queue_survival import begin_queue_action

                        begin_queue_action(_session, name=_name)
                    except ImportError:
                        pass
                    try:
                        from live_draft_ux_latency import ACTION_ADD_QUEUE, note_ux_action

                        note_ux_action(
                            _session,
                            ACTION_ADD_QUEUE,
                            source="rec_card_add",
                            detail=f"{_name}|before={len(before)}",
                        )
                    except ImportError:
                        pass
                    added = False
                    after = list(before)
                    try:
                        from draft_state import add_player_to_draft_queue
                        from live_draft_rerun_scope import mark_live_draft_queue_tick

                        # Mutate session immediately; skip recommendation rebuild on the follow-up paint.
                        mark_live_draft_queue_tick(_session)
                        after, added = add_player_to_draft_queue(_session, _name)
                    except ImportError:
                        try:
                            from draft_state import add_player_to_draft_queue

                            after, added = add_player_to_draft_queue(_session, _name)
                        except ImportError:
                            pass
                    after = [str(x).strip() for x in (_session.get("draft_queue") or []) if str(x).strip()]
                    try:
                        from live_draft_queue_fragment import record_queue_add_diag

                        record_queue_add_diag(
                            _session,
                            name=_name,
                            before=before,
                            after=after,
                            added=bool(added),
                        )
                    except ImportError:
                        _session["_live_draft_queue_add_diag"] = {
                            "name": _name,
                            "before_len": len(before),
                            "after_len": len(after),
                            "added": bool(added),
                            "mutated": before != after,
                        }
                    try:
                        from live_draft_queue_survival import note_queue_survival

                        note_queue_survival(
                            _session,
                            "A",
                            detail=f"after rec_card_add name={_name} added={bool(added)}",
                        )
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
                        "⭐ Add to Queue",
                        key=f"rec_card_queue_{pick_idx}_{stable_key}",
                        use_container_width=True,
                        on_click=_on_rec_queue_click,
                        help=f"Add {name} to your draft queue.",
                    )
            with detail_col:
                with st.expander("Why Recommended", expanded=False):
                    st.markdown(
                        build_rec_card_detail_body(
                            r,
                            badges=badges,
                            strengths=strengths,
                            gaps=gaps,
                            category_needs=category_needs,
                            rank=i,
                        ),
                        unsafe_allow_html=True,
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
