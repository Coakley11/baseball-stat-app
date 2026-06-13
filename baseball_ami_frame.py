"""Baseball AMI analyst framing — answer structure, page questions, decision variables."""

from __future__ import annotations

from typing import Any

# Six-level answer structure sent to solvers (teaching + decision support).
AMI_ANSWER_TEMPLATE: list[dict[str, str]] = [
    {"level": 1, "name": "direct_answer", "instruction": "Lead with a clear recommendation (player/action) in one sentence."},
    {"level": 2, "name": "why_roster_fit", "instruction": "Explain why it fits the user's roster, category needs, and positional gaps."},
    {"level": 3, "name": "scarcity", "instruction": "Analyze positional/category scarcity and replacement value at this pick."},
    {"level": 4, "name": "risk_upside", "instruction": "Cover risk, upside, volatility, and projection edge vs market/ADP."},
    {"level": 5, "name": "alternatives", "instruction": "Name 2–3 alternative picks with tradeoffs."},
    {"level": 6, "name": "what_if", "instruction": "Show how the recommendation changes if prioritizing power, speed, pitching, safety, or upside."},
]

AMI_DECISION_VARIABLES: list[str] = [
    "power",
    "speed",
    "pitching",
    "positional_scarcity",
    "roster_construction",
    "risk",
    "upside",
    "replacement_value",
    "category_needs",
    "adp_market_value",
    "projection_edge",
    "draft_position_value",
]

PAGE_ACCEPTANCE_QUESTIONS: dict[str, list[str]] = {
    "Draft Assistant Simulator": [
        "Who should I draft next?",
        "What does my roster need?",
        "Who are the best values left?",
        "How risky is this pick?",
        "What changes if I prioritize power, speed, saves, or pitching?",
    ],
    "Live Draft Room": [
        "I'm on the clock. Who should I take?",
        "Should I reach for this player?",
        "Will this player make it back to me?",
        "What is the safest pick?",
        "What is the highest-upside pick?",
    ],
    "Fantasy Sleepers & Busts": [
        "Should I take this sleeper?",
        "Which sleeper fits my roster?",
        "Which sleeper has the highest upside?",
        "Which sleeper is the safest?",
    ],
    "Trend Value": [
        "Is this player overvalued?",
        "Is this player undervalued?",
        "Is now the right time to draft him?",
        "What is his risk profile?",
    ],
    "Valuation": [
        "Is this player overvalued?",
        "Is this player undervalued?",
        "Is now the right time to draft him?",
        "What is his risk profile?",
    ],
}

PAGE_CONTEXT_REQUIREMENTS: dict[str, list[str]] = {
    "Draft Assistant Simulator": [
        "canonical_draft_board",
        "canonical_drafted_players",
        "available_players",
        "draft_queue",
        "watchlist_focus",
        "tracked_players",
        "user_roster",
        "needed_positions",
        "category_needs",
        "position_scarcity",
        "recommended_players",
        "best_available_players",
        "scoring_settings",
    ],
    "Live Draft Room": [
        "draft_round",
        "current_pick",
        "my_next_pick",
        "latest_picks",
        "user_roster",
        "draft_queue",
        "watchlist_focus",
        "available_players",
        "recommended_players",
        "scoring_settings",
    ],
    "Fantasy Sleepers & Busts": [
        "sleeper_candidates",
        "bust_risks",
        "drafted_exclusions",
        "synced_roster",
        "roster_needs",
        "canonical_draft_board",
    ],
    "Trend Value": [
        "trend_summary",
        "player",
        "metrics",
        "draft_status",
        "canonical_drafted_players",
    ],
    "Valuation": [
        "valuation_snapshot",
        "selected_player",
        "top_valuation_players",
        "draft_status",
        "canonical_drafted_players",
    ],
}


def attach_baseball_ami_frame(ctx: dict[str, Any], page: str) -> dict[str, Any]:
    """Merge analyst framing into solver context. Never use generic baseball knowledge alone."""
    p = str(page or "").strip()
    ctx["ami_answer_template"] = list(AMI_ANSWER_TEMPLATE)
    ctx["ami_decision_variables"] = list(AMI_DECISION_VARIABLES)
    if p in PAGE_ACCEPTANCE_QUESTIONS:
        ctx["ami_acceptance_questions"] = list(PAGE_ACCEPTANCE_QUESTIONS[p])
    if p in PAGE_CONTEXT_REQUIREMENTS:
        ctx["ami_context_requirements"] = list(PAGE_CONTEXT_REQUIREMENTS[p])
    ctx["ami_quality_rule"] = (
        "Use ONLY the structured context in this payload (draft_snapshot, draft_projection, "
        "sleepers_snapshot, trend_summary, valuation_snapshot, roster, queue, watchlist). "
        "Do not give generic fantasy advice. Behave as a quantitative fantasy analyst and strategist."
    )
    return ctx


def player_draft_status(session: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Whether a player is drafted on the canonical board."""
    name = str(player_name or "").split(" (")[0].strip()
    if not name:
        return {"player": "", "is_drafted": False, "on_user_roster": False}
    drafted: list[str] = []
    try:
        from draft_room_state import get_all_drafted_player_names, get_canonical_draft_board

        drafted = get_all_drafted_player_names(session)
        board = get_canonical_draft_board(session)
        team = session.get("room_your_team") or session.get("sleeper_sync_team")
        on_roster = False
        if board is not None and hasattr(board, "columns") and team and "Team" in board.columns:
            mine = board[
                (board["Team"].astype(str) == str(team))
                & (board["Player"].astype(str).str.strip() == name)
            ]
            on_roster = not mine.empty
    except Exception:
        drafted = []
        on_roster = False
    base_names = {str(d).split(" (")[0].strip().lower() for d in drafted}
    is_drafted = name.lower() in base_names
    return {
        "player": name,
        "is_drafted": is_drafted,
        "on_user_roster": on_roster,
        "drafted_player_count": len(drafted),
    }
