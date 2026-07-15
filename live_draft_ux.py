"""Live Draft UX — canonical labels, tooltips, and presentation helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Historical Explorer scatter palette (streamlit_app._scatter_color_encoding)
POSITION_COLORS: dict[str, str] = {
    "1B": "#08306b",
    "2B": "#8c510a",
    "SS": "#238b45",
    "3B": "#ffd92f",
    "OF": "#e31a1c",
    "DH": "#756bb1",
    "C": "#000000",
    "P": "#bdbdbd",
    "Unknown": "#ffffff",
}

STRENGTH_DESCRIPTIONS: dict[str, str] = {
    "HR": "Elite Power",
    "RBI": "Excellent Run Production",
    "SB": "Above-Average Speed",
    "AVG": "Strong Batting Average",
    "Runs": "Strong Run Scoring",
    "R": "Strong Run Scoring",
    "OBP": "Elite On-Base Skills",
    "Contact": "Elite Contact",
    "Speed": "Above-Average Speed",
    "Power": "Elite Power",
    "Run Production": "Excellent Run Production",
    "Walks/OPS": "Strong On-Base & Power",
}

CATEGORY_NEED_STARS: dict[str, int] = {
    "HR": 5,
    "Home Runs": 5,
    "RBI": 4,
    "SB": 4,
    "Speed": 4,
    "AVG": 3,
    "Batting Average": 3,
    "BA": 3,
    "Runs": 3,
    "R": 3,
    "OBP": 3,
    "Contact": 2,
}

START_STEP_USER_LABELS: dict[str, str] = {
    "start_clicked": "Preparing Draft…",
    "room_created": "Preparing Draft…",
    "market_data_loaded": "Loading Draft Board…",
    "pool_build_start": "Loading Draft Board…",
    "pool_build_end": "Loading Draft Board…",
    "room_initialized": "Loading Draft Board…",
    "shared_write_start": "Preparing Draft…",
    "shared_write_end": "Preparing Draft…",
    "local_save_start": "Preparing Draft…",
    "local_save_end": "Preparing Draft…",
    "timer_deadline_set": "Round 1 Starting…",
    "pool_loaded": "Round 1 Starting…",
    "recommendations_loaded": "Round 1 Starting…",
    "first_render_ready": "Draft Live",
    "start_failed": "Could not start draft",
}

FANTASY_EDGE_TOOLTIP = "This compares our projection against current market value."
ROSTER_FIT_TOOLTIP = (
    "How well this player fits your open roster slots and category needs — "
    "including filling weak categories and balancing roster construction."
)

REC_TABLE_SORT_OPTIONS: dict[str, str] = {
    # label → actual dataframe column used by the recommendation engine
    "Decision Score": "Decision Score",
    "Player Grade": "Player Grade",
    "Fantasy Edge": "Fantasy Edge",
    "Roster Fit Score": "Roster Fit Score",
    "Market Rank": "Market Rank",
    "Primary Position": "Primary Position",
    "Risk Score": "Risk Score",
    "Survival Probability": "Survival Probability",
    "Category Need Bonus": "Category Need Bonus",
}


def position_color(pos: str) -> str:
    key = str(pos or "").strip().upper()
    if key in POSITION_COLORS:
        return POSITION_COLORS[key]
    if key.startswith("OF"):
        return POSITION_COLORS["OF"]
    return POSITION_COLORS["Unknown"]


def position_badge_html(pos: str, *, label: str = "") -> str:
    color = position_color(pos)
    text = str(label or pos or "—").strip()
    return (
        f'<span class="ld-pos-badge" style="background:{color};color:#fff;'
        f'padding:2px 8px;border-radius:999px;font-size:0.78rem;font-weight:700;">{text}</span>'
    )


def format_participant_identity(
    display_name: str,
    *,
    role: str = "",
    team: str = "",
) -> str:
    """Canonical: ``Donny (Commissioner) — Team A``."""
    name = str(display_name or "Guest").strip() or "Guest"
    role_label = str(role or "").strip()
    team_name = str(team or "").strip()
    if role_label:
        head = f"{name} ({role_label})"
    else:
        head = name
    if team_name:
        return f"{head} — {team_name}"
    return head


def format_your_fantasy_team(team: str) -> str:
    team_name = str(team or "").strip()
    if not team_name:
        return "Your Fantasy Team: —"
    return f"You are managing **{team_name}**"


def format_your_fantasy_team_caption(team: str) -> str:
    team_name = str(team or "").strip()
    if not team_name:
        return "Your Fantasy Team: —"
    return f"Your Fantasy Team: **{team_name}**"


def describe_strength(label: str) -> str:
    key = str(label or "").strip()
    return STRENGTH_DESCRIPTIONS.get(key, key or "Balanced profile")


def describe_strengths(labels: list[str] | None, *, max_count: int = 2) -> list[str]:
    out: list[str] = []
    for raw in labels or []:
        text = describe_strength(label=str(raw))
        if text and text not in out:
            out.append(text)
        if len(out) >= max_count:
            break
    return out


def star_rating(importance: int, *, label: str = "") -> str:
    stars = max(1, min(5, int(importance)))
    star_txt = "★" * stars + "☆" * (5 - stars)
    if label:
        return f"{star_txt} {label}"
    return star_txt


def category_need_stars(category: str) -> str:
    key = str(category or "").strip()
    importance = CATEGORY_NEED_STARS.get(key, CATEGORY_NEED_STARS.get(key.upper(), 3))
    return star_rating(importance, label=key)


def confidence_label_from_score(score: float | None) -> tuple[str, str]:
    """Return (label, star_html) for recommendation confidence."""
    if score is None or pd.isna(score):
        return "Moderate Confidence Recommendation", star_rating(3)
    val = float(score)
    if val >= 0.85:
        return "High Confidence Recommendation", star_rating(5)
    if val >= 0.70:
        return "Strong Confidence Recommendation", star_rating(4)
    if val >= 0.55:
        return "Moderate Confidence Recommendation", star_rating(3)
    return "Low Confidence Recommendation", star_rating(2)


def format_of_slot_eligibility(open_of: int) -> str:
    n = max(1, int(open_of))
    if n == 1:
        return "Eligible for your remaining OF position"
    return f"Eligible for any of your {n} remaining starting OF spots"


def format_scarcity_explanation(
    pos: str,
    *,
    tier1_remaining: int | None = None,
    picks_until_dropoff: int | None = None,
    scarcity_score: float | None = None,
) -> str:
    position = str(pos or "Position").strip() or "Position"
    if tier1_remaining is not None and int(tier1_remaining) > 0:
        text = f"Only {int(tier1_remaining)} Tier-1 {position} remain."
    elif scarcity_score is not None and float(scarcity_score) >= 0.55:
        text = f"{position} depth is tightening — quality options are fading."
    else:
        text = f"{position} pool is getting thinner."
    if picks_until_dropoff is not None and int(picks_until_dropoff) > 0:
        text += f" Expected position drop-off after the next {int(picks_until_dropoff)} picks."
    return text


def estimate_tier1_remaining(rec_df: Any, pos: str, *, tier_pct: float = 0.25) -> int:
    if rec_df is None or getattr(rec_df, "empty", True):
        return 0
    if "Primary Position" not in rec_df.columns:
        return 0
    subset = rec_df[rec_df["Primary Position"].astype(str) == str(pos)]
    if subset.empty:
        return 0
    n = max(1, int(len(subset) * tier_pct))
    return max(1, min(len(subset), n))


def user_facing_start_step(step: str) -> str:
    key = str(step or "").strip()
    return START_STEP_USER_LABELS.get(key, "Preparing Draft…")


def resolve_next_pick_for_survival(
    *,
    current_pick: int,
    next_user_pick: int | None,
    num_teams: int,
    room: dict[str, Any] | None = None,
    user_team: str = "",
) -> int:
    cur = max(1, int(current_pick or 1))
    if next_user_pick is not None and int(next_user_pick) > cur:
        return int(next_user_pick)
    if isinstance(room, dict) and str(user_team or "").strip():
        pick_order = room.get("pick_order") or []
        idx = int(room.get("current_pick_index") or 0)
        for entry in pick_order[idx + 1 :]:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("Team") or "") == str(user_team):
                pick_num = int(entry.get("Pick") or 0)
                if pick_num > cur:
                    return pick_num
    return cur + max(1, int(num_teams or 12))


def format_survival_probability(value: Any) -> str:
    prob = pd.to_numeric(value, errors="coerce")
    if pd.isna(prob):
        return "—"
    pct = int(round(float(prob) * 100))
    return f"{pct}%"


def apply_survival_display_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    if "Survival Probability" in out.columns:
        out["Survival Probability"] = out["Survival Probability"].apply(format_survival_probability)
    return out


def sort_recommendation_table(df: pd.DataFrame, sort_key: str, *, ascending: bool = False) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    col = str(sort_key or "Decision Score").strip()
    # Map legacy / display alias → live column when present.
    aliases = {
        "Roster Fit": "Roster Fit Score",
        "Draft Fit Score": "Roster Fit Score",
        "Expected Fantasy Value": "Player Grade",
        "Market Discount": "Market Rank",
        "Position": "Primary Position",
        "Risk": "Risk Score",
        "Category Need": "Category Need Bonus",
    }
    if col not in df.columns and col in aliases:
        col = aliases[col]
    if col == "Player Grade" and col not in df.columns and "Expected Fantasy Value" in df.columns:
        col = "Expected Fantasy Value"
    if col == "Roster Fit Score" and col not in df.columns and "Draft Fit Score" in df.columns:
        col = "Draft Fit Score"
    if col not in df.columns:
        return df
    # Rank-like fields sort ascending (lower is better); scores/probabilities descending.
    if ascending is False and col in {"Market Rank", "Primary Position"}:
        ascending = True if col == "Market Rank" else False
    return df.sort_values(col, ascending=ascending, na_position="last")


def inject_position_color_styles() -> str:
    rules = []
    for pos, color in POSITION_COLORS.items():
        if pos == "Unknown":
            continue
        rules.append(f".ld-pos-{pos.lower()} {{ color: {color}; font-weight: 700; }}")
        rules.append(
            f".ld-pos-chip-{pos.lower()} {{ background:{color};color:#fff;"
            f"padding:2px 8px;border-radius:999px;font-size:0.78rem; }}"
        )
    return "\n".join(rules)


def inject_draft_animation_styles() -> str:
    return """
    @keyframes ld-pick-flash {
        0% { box-shadow: 0 0 0 0 rgba(45, 140, 255, 0.55); background: rgba(45, 140, 255, 0.18); }
        70% { box-shadow: 0 0 0 12px rgba(45, 140, 255, 0); background: rgba(45, 140, 255, 0.08); }
        100% { box-shadow: 0 0 0 0 rgba(45, 140, 255, 0); background: rgba(45, 140, 255, 0.12); }
    }
    .ld-pick-flash {
        animation: ld-pick-flash 0.9s ease-out 1;
    }
    @keyframes ld-board-slide-in {
        from { opacity: 0; transform: translateY(-12px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .ld-board-new-pick {
        animation: ld-board-slide-in 0.45s ease-out 1;
    }
    @keyframes ld-on-clock-flash {
        0% { border-color: #1f6feb; box-shadow: 0 0 0 0 rgba(31, 111, 235, 0.45); }
        100% { border-color: rgba(11, 61, 110, 0.25); box-shadow: none; }
    }
    .ld-on-clock-flash {
        animation: ld-on-clock-flash 0.85s ease-out 1;
    }
    .ld-board-pick-notice {
        padding: 8px 12px;
        border-radius: 8px;
        background: rgba(45, 140, 255, 0.12);
        font-size: 0.88rem;
        margin-bottom: 8px;
        border: 1px solid rgba(45, 140, 255, 0.35);
    }
    .ld-board-row-highlight td {
        background: rgba(45, 140, 255, 0.14) !important;
        animation: ld-board-slide-in 0.45s ease-out 1;
    }
    """


def inject_draft_queue_sortable_styles() -> str:
    """Red sliding drag-queue styles for streamlit-sortables (Live Draft UX).

    Preserve this interaction model during performance work — do not replace with
    a static list. Drag handles stay visually loud and grab-friendly.
    """
    return """
    .sortable-item {
        padding: 10px 14px;
        margin: 6px 0;
        border-radius: 10px;
        border: 1px solid rgba(185, 28, 28, 0.35);
        background: linear-gradient(180deg, #fff5f5 0%, #fee2e2 100%);
        color: #7f1d1d;
        font-weight: 700;
        cursor: grab;
        box-shadow: 0 1px 4px rgba(127, 29, 29, 0.12);
        transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
    }
    .sortable-item:hover {
        border-color: rgba(185, 28, 28, 0.65);
        box-shadow: 0 2px 8px rgba(127, 29, 29, 0.18);
    }
    .sortable-item:active {
        cursor: grabbing;
        transform: translateX(4px) scale(1.01);
        border-color: #b91c1c;
        box-shadow: 0 4px 14px rgba(185, 28, 28, 0.28);
    }
    """


def record_live_draft_pick_posted(
    session: dict[str, Any],
    *,
    pick: int,
    round_no: int,
    team: str,
    player: str,
) -> None:
    """Store the latest pick for one-shot announcement + board animation."""
    player_s = str(player or "").strip()
    team_s = str(team or "").strip()
    sig = f"{int(pick)}|{team_s}|{player_s}"
    session["_ld_last_pick_announcement"] = {
        "pick": int(pick),
        "round": int(round_no),
        "team": team_s,
        "player": player_s,
        "sig": sig,
    }
    session.pop("_ld_shown_pick_announcement_sig", None)


def render_live_draft_pick_announcement(session: dict[str, Any], st: Any) -> bool:
    """Show pick-announcement card once per new pick signature."""
    ann = session.get("_ld_last_pick_announcement")
    if not isinstance(ann, dict):
        return False
    sig = str(ann.get("sig") or "").strip()
    if not sig or sig == str(session.get("_ld_shown_pick_announcement_sig") or ""):
        return False
    session["_ld_shown_pick_announcement_sig"] = sig
    player = str(ann.get("player") or "Player").strip()
    team = str(ann.get("team") or "").strip()
    pick = int(ann.get("pick") or 0)
    round_no = int(ann.get("round") or 0)
    st.markdown(
        f'<div class="ld-board-pick-notice ld-pick-flash ld-board-new-pick">'
        f"<strong>Pick {pick}</strong> (Round {round_no}) — "
        f"<strong>{player}</strong> → {team}"
        f"</div>",
        unsafe_allow_html=True,
    )
    return True


def on_clock_should_flash(session: dict[str, Any], pick_index: int) -> bool:
    """True once when the on-clock pick index advances."""
    idx = int(pick_index or 0)
    prev = session.get("_ld_on_clock_flash_index")
    if prev == idx:
        return False
    session["_ld_on_clock_flash_index"] = idx
    return True


def should_highlight_latest_board_row(session: dict[str, Any], pick_count: int) -> bool:
    """True once per new pick when the board row count advances."""
    count = max(0, int(pick_count or 0))
    prev = int(session.get("_ld_last_board_highlight_count") or 0)
    if count <= prev:
        return False
    session["_ld_last_board_highlight_count"] = count
    sig = f"board_row:{count}"
    if str(session.get("_ld_board_row_highlight_shown") or "") == sig:
        return False
    session["_ld_board_row_highlight_sig"] = sig
    return True


def consume_latest_board_row_highlight(session: dict[str, Any]) -> bool:
    """Mark the pending board-row highlight as shown for this run."""
    sig = str(session.get("_ld_board_row_highlight_sig") or "").strip()
    if not sig or str(session.get("_ld_board_row_highlight_shown") or "") == sig:
        return False
    session["_ld_board_row_highlight_shown"] = sig
    return True


def style_latest_board_row(df: pd.DataFrame) -> Any:
    """Highlight the newest board row with a one-shot slide-in animation.

    Returns a pandas ``Styler`` for ``st.dataframe`` display only.
    Never pass the result into ``render_output_table`` — Styler has no ``.copy()``.
    Empty / invalid input returns an empty DataFrame (never None).
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    last_idx = df.index[-1]

    def _row_style(row: pd.Series) -> list[str]:
        if row.name != last_idx:
            return [""] * len(row)
        return [
            "background-color: rgba(45, 140, 255, 0.14); animation: ld-board-slide-in 0.45s ease-out 1;"
        ] * len(row)

    return df.style.apply(_row_style, axis=1)


def note_live_draft_board_pick_flash(session: dict[str, Any], st: Any, pick_count: int) -> bool:
    """Flash board notice when pick count advances — uses announcement when available."""
    count = max(0, int(pick_count or 0))
    prev = int(session.get("_ld_last_board_pick_count") or 0)
    session["_ld_last_board_pick_count"] = count
    if count <= prev:
        return False
    should_highlight_latest_board_row(session, count)
    if render_live_draft_pick_announcement(session, st):
        return True
    st.markdown(
        '<div class="ld-board-pick-notice ld-pick-flash ld-board-new-pick">'
        "Latest pick posted to the draft board."
        "</div>",
        unsafe_allow_html=True,
    )
    return True
