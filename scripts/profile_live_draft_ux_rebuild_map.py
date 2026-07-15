#!/usr/bin/env python3
"""Static map: what Streamlit still rebuilds per Live Draft click after Phase 6A.

This does not measure wall-clock. It answers which DOM/widget regions must
re-execute for each user action — the usual reason UX still feels like an
analytics page even when engine timings are fast.

Run: python scripts/profile_live_draft_ux_rebuild_map.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Surfaces that dominate perceived latency when they re-execute.
SURFACES = (
    "queue_sortable",
    "queue_rows_buttons",
    "rec_cards",
    "board_table",
    "on_clock_banner",
    "timer_fragment",
    "rec_tables_x4",
    "decision_panels",
    "roster_tabs",
    "team_totals",
    "full_app_script",
)


# Post-6A rebuild map (from live_draft_queue_fragment + streamlit_app wiring).
# "widget_click" = Streamlit already re-runs fragment/app once for the widget.
# "explicit_rerun" = code calls st.rerun again after the widget pass.
REBUILD_MAP: dict[str, dict[str, object]] = {
    "add_to_queue (rec card)": {
        "scope": "fragment (queue + rec cards)",
        "rebuilds": ["queue_sortable", "queue_rows_buttons", "rec_cards"],
        "skips": [
            "board_table",
            "rec_tables_x4",
            "decision_panels",
            "roster_tabs",
            "team_totals",
            "full_app_script",
        ],
        "second_rerun_risk": (
            "Usually one fragment pass (on_click mutates before body). "
            "If panel_rerun flips True, an explicit fragment rerun adds a 2nd pass."
        ),
        "felt_risk": "HIGH — 6 rec cards + red sortable still rebuild on every Add",
    },
    "remove_from_queue": {
        "scope": "fragment (queue + rec cards)",
        "rebuilds": ["queue_sortable", "queue_rows_buttons", "rec_cards"],
        "skips": [
            "board_table",
            "rec_tables_x4",
            "decision_panels",
            "roster_tabs",
            "team_totals",
        ],
        "second_rerun_risk": (
            "YES by design today: widget-driven fragment pass + explicit "
            "st.rerun(scope='fragment') when queue_mutated — double paint of "
            "queue sortable + all rec cards."
        ),
        "felt_risk": "HIGH — double fragment pass + cards collocated with queue",
    },
    "reorder_queue (drag/buttons)": {
        "scope": "fragment (queue + rec cards)",
        "rebuilds": ["queue_sortable", "queue_rows_buttons", "rec_cards"],
        "skips": ["board_table", "rec_tables_x4", "roster_tabs", "team_totals"],
        "second_rerun_risk": "Same as remove — explicit fragment rerun after mutate",
        "felt_risk": "HIGH — streamlit_sortables remount is expensive",
    },
    "draft_from_queue": {
        "scope": "app (escalated)",
        "rebuilds": list(SURFACES),
        "skips": [],
        "second_rerun_risk": "App escalate; page_complete settles. Pending-pick paths may add extras.",
        "felt_risk": "CRITICAL — full analytics page rebuild",
    },
    "draft_from_recommendation": {
        "scope": "app (pending pick / optimistic path)",
        "rebuilds": list(SURFACES),
        "skips": [],
        "second_rerun_risk": "Historically double-rerun; Phase 2 reduced but full app still paints all surfaces",
        "felt_risk": "CRITICAL — full analytics page rebuild",
    },
    "board_update / on_clock / timer_reset": {
        "scope": "app or timer/on_clock fragments",
        "rebuilds": ["board_table", "on_clock_banner", "timer_fragment", "full_app_script?"],
        "skips": [],
        "second_rerun_risk": "Timer fragment ticks every 1s; expiry may full-app rerun",
        "felt_risk": "HIGH on pick — board+rosters+recs still main-script",
    },
    "recommendation_card_update": {
        "scope": "shares queue fragment (6A) OR full app on pick",
        "rebuilds": ["rec_cards"],
        "skips": [],
        "second_rerun_risk": "On queue mutate cards always rebuild with queue",
        "felt_risk": "HIGH — cards are on the queue hot path by 6A design",
    },
}


def main() -> int:
    print("=== Live Draft UX rebuild map (Phase 6A as deployed) ===\n")
    print(
        "Verdict framing: if Add/Remove still rebuilds rec_cards + sortable, "
        "users will not feel ESPN/Sleeper speed even when queue engine is <1ms.\n"
    )
    for action, info in REBUILD_MAP.items():
        print(f"## {action}")
        print(f"  scope: {info['scope']}")
        print(f"  rebuilds: {', '.join(info['rebuilds'])}")  # type: ignore[arg-type]
        skips = info.get("skips") or []
        if skips:
            print(f"  skips: {', '.join(skips)}")  # type: ignore[arg-type]
        print(f"  second_rerun_risk: {info['second_rerun_risk']}")
        print(f"  felt_risk: {info['felt_risk']}")
        print()

    print("=== Likely remaining bottleneck (pre-browser numbers) ===")
    print(
        "1. Phase 6A collocated recommendation CARDS inside the queue fragment.\n"
        "   Add/Remove/Reorder still repaints the expensive card tree — that alone\n"
        "   can erase the feel of isolation.\n"
        "2. Explicit st.rerun(scope='fragment') after queue_mutated causes a\n"
        "   second fragment pass on Remove/Reorder (widget already re-ran once).\n"
        "3. streamlit_sortables remount on every queue fragment pass.\n"
        "4. Draft actions still escalate to full-app (board+tables+rosters+totals).\n"
        "5. Cloud RTT / Streamlit WebSocket delta is unmeasured until UX panel runs.\n"
    )
    print(
        "Next measurement step: enable Developer Mode (or ?ux_latency=1), click\n"
        "Add/Remove/Draft, and read sidebar 'UX latency (click → paint)'.\n"
        "Compare first_visible_ms vs settled_ms and whether second_rerun=True."
    )
    return 0


if __name__ == "__main__":
    # Fix shebang typo if anyone copies — keep executable via python -m / python path.
    raise SystemExit(main())
