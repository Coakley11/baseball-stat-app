"""Queue seed harness: parser fixtures, evidence hierarchy, surface activation safety."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_active_queue_surface import (  # noqa: E402
    QUEUE_SURFACE_NAV_LABELS,
    surface_activation_labels_are_navigation_only,
)
from stage1_queue_seed_harness import (  # noqa: E402
    QUEUE1C,
    QUEUE1D,
    QUEUE1E,
    build_queue_seed_evidence,
    classify_queue_seed_boundary,
    parse_queue_players_from_block,
)


def _room79407528_queue_excerpt() -> str:
    """Visible Draft queue block from production room 79407528 (name-only rows)."""
    return (
        "Draft queue\n"
        "Francisco Lindor\n"
        "Pete Alonso\n"
        "Clear Draft Queue\n"
        "Watchlist\n"
        "Recommendations\n"
    )


def test_parse_queue_players_name_only_room_79407528() -> None:
    players = parse_queue_players_from_block(_room79407528_queue_excerpt())
    names = [p["name"] for p in players]
    assert names == ["Francisco Lindor", "Pete Alonso"]


def test_parse_queue_skips_navigation_headings() -> None:
    text = "Draft queue\nWatchlist\nClear Draft Queue\n"
    assert parse_queue_players_from_block(text) == []


def test_surface_activation_labels_never_match_add_to_queue() -> None:
    assert surface_activation_labels_are_navigation_only()
    assert "Add to Queue" not in " ".join(QUEUE_SURFACE_NAV_LABELS)
    assert all("Add" not in lbl or "Available" in lbl for lbl in QUEUE_SURFACE_NAV_LABELS)


def test_three_clicks_two_visible_names_is_not_queue_seed_resolved() -> None:
    meta = {
        "seed_steps": [
            {"click_dispatched": True, "mutation_proven": True, "player_name": "Francisco Lindor"},
            {"click_dispatched": True, "mutation_proven": True, "player_name": "Pete Alonso"},
            {"click_dispatched": True, "mutation_proven": False, "player_name": "Mike Trout"},
        ],
        "queue_order_established": False,
        "queue_container": {"excerpt": _room79407528_queue_excerpt(), "players": []},
        "add_actions": [],
        "pick_index_zero_after_setup": True,
        "paused_state_maintained": True,
    }
    ev = build_queue_seed_evidence(meta, min_players=3)
    assert ev["queue_seed_resolved"] is False
    assert ev["deliberate_add_click_count"] == 3
    assert ev["proven_identity_count"] == 2
    assert classify_queue_seed_boundary(meta, min_players=3) in (QUEUE1C, QUEUE1E, QUEUE1D)


def test_queue_seed_resolved_requires_three_mutation_proven_identities() -> None:
    meta = {
        "seed_steps": [
            {"click_dispatched": True, "mutation_proven": True, "player_name": "Francisco Lindor"},
            {"click_dispatched": True, "mutation_proven": True, "player_name": "Pete Alonso"},
            {"click_dispatched": True, "mutation_proven": True, "player_name": "Juan Soto"},
        ],
        "queue_order_established": True,
        "queue_container": {
            "excerpt": "Draft queue\nFrancisco Lindor\nPete Alonso\nJuan Soto\nClear Draft Queue\n",
            "players": [],
        },
        "add_actions": [],
        "pick_index_zero_after_setup": True,
        "paused_state_maintained": True,
    }
    ev = build_queue_seed_evidence(meta, min_players=3)
    assert ev["queue_seed_resolved"] is True
    assert ev["proven_identity_count"] == 3


def test_classify_queue1d_when_visible_but_parser_empty() -> None:
    """Room 79407528: two visible names; parser must not invent a third."""
    excerpt = _room79407528_queue_excerpt()
    players = parse_queue_players_from_block(excerpt)
    assert len(players) == 2
    meta = {
        "surface_activation_queue_mutation": False,
        "seed_steps": [
            {"click_dispatched": True, "mutation_proven": True, "player_name": "Francisco Lindor"},
            {"click_dispatched": True, "mutation_proven": True, "player_name": "Pete Alonso"},
            {"click_dispatched": True, "mutation_proven": False, "classification": QUEUE1C},
        ],
        "proven_queue_order": ["Francisco Lindor", "Pete Alonso"],
        "queue_order_established": False,
        "queue_container": {"excerpt": excerpt, "players": []},
        "add_actions": [],
        "pick_index_zero_after_setup": True,
        "paused_state_maintained": True,
    }
    ev = build_queue_seed_evidence(meta, min_players=3)
    assert ev["queue_seed_resolved"] is False
    assert ev["visible_queue_player_names"] == ["Francisco Lindor", "Pete Alonso"]
    assert ev["structured_scraper_names"] == ["Francisco Lindor", "Pete Alonso"]
