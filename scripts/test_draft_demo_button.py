"""Smoke test: Load Portfolio Demo Draft button populates session state."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portfolio_demo import (
    DEMO_TEAM,
    PENDING_DRAFT_WIDGET_DEFAULTS_KEY,
    load_portfolio_demo_draft,
    request_draft_demo,
    apply_pending_draft_demo,
)


def test_load_portfolio_demo_draft_sets_expected_keys():
    state = {}

    class St:
        session_state = state

    load_portfolio_demo_draft(St())

    assert "draft_room_table" in state
    table = state["draft_room_table"]
    filled = table[table["Player"].astype(str).str.strip() != ""]
    assert len(filled) == 12
    assert state["room_your_team"] == DEMO_TEAM
    assert state["draft_assistant_synced_team"] == DEMO_TEAM
    assert state["draft_top_n"] == 10
    assert state["draft_use_ml_blend"] is True
    assert state["_pp_demo_applied_draft_assistant"] is True

    my_roster = filled[filled["Team"] == DEMO_TEAM]["Player"].tolist()
    assert my_roster == ["Mookie Betts", "Jose Altuve", "Kyle Tucker"]


def test_request_draft_demo_queues_widget_defaults():
    state = {}

    class St:
        session_state = state

    request_draft_demo(St())
    assert state[PENDING_DRAFT_WIDGET_DEFAULTS_KEY] is True
    assert "draft_room_table" in state
    assert "draft_assistant_synced_team" not in state

    apply_pending_draft_demo(St())
    assert state["draft_assistant_synced_team"] == DEMO_TEAM
    assert PENDING_DRAFT_WIDGET_DEFAULTS_KEY not in state


if __name__ == "__main__":
    test_load_portfolio_demo_draft_sets_expected_keys()
    test_request_draft_demo_queues_widget_defaults()
    print("OK: portfolio_demo draft helpers")
