"""Regression tests for Add-to-Queue delivery binding and seed selection."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_add_to_queue_delivery import (  # noqa: E402
    BINDING_AMBIGUOUS,
    BINDING_UNIQUE,
    classify_name_binding,
    extract_player_names_from_lines,
    select_next_seed_candidate,
)
from stage1_queue_seed_harness import (  # noqa: E402
    QUEUE1B,
    QUEUE1C,
    build_queue_seed_evidence,
    classify_queue_seed_boundary,
    parse_queue_players_from_block,
)


def test_extract_names_from_player_card_lines() -> None:
    lines = ["Francisco Lindor", "SS — UTIL", "⭐ Add to Queue"]
    assert extract_player_names_from_lines(lines) == ["Francisco Lindor"]


def test_classify_unique_vs_ambiguous_binding() -> None:
    conf, name = classify_name_binding(["Pete Alonso"])
    assert conf == BINDING_UNIQUE and name == "Pete Alonso"
    conf2, _ = classify_name_binding(["Pete Alonso", "Juan Soto"])
    assert conf2 == BINDING_AMBIGUOUS


def test_select_next_skips_already_queued() -> None:
    candidates = [
        {"global_index": 0, "player_name": "Francisco Lindor", "binding_confidence": "unique"},
        {"global_index": 1, "player_name": "Pete Alonso", "binding_confidence": "unique"},
        {"global_index": 2, "player_name": "Juan Soto", "binding_confidence": "unique"},
    ]
    pick, _ = select_next_seed_candidate(candidates, exclude_player_names={"francisco lindor"})
    assert pick and pick["player_name"] == "Pete Alonso"
    pick2, _ = select_next_seed_candidate(candidates, exclude_player_names=set(), exclude_global_indices={0, 1})
    assert pick2 and pick2["global_index"] == 2


def test_select_next_rejects_ambiguous_binding() -> None:
    candidates = [
        {
            "global_index": 0,
            "player_name": "",
            "binding_confidence": BINDING_AMBIGUOUS,
            "candidate_names": ["A", "B"],
        },
    ]
    pick, reason = select_next_seed_candidate(candidates, exclude_player_names=set())
    assert pick is None and reason == "ambiguous_binding"


def test_identical_add_labels_distinct_player_cards() -> None:
    candidates = [
        {"global_index": 0, "player_name": "Francisco Lindor", "binding_confidence": "unique", "button_text": "⭐ Add to Queue"},
        {"global_index": 1, "player_name": "Pete Alonso", "binding_confidence": "unique", "button_text": "⭐ Add to Queue"},
    ]
    first, _ = select_next_seed_candidate(candidates, exclude_player_names=set())
    second, _ = select_next_seed_candidate(candidates, exclude_player_names={first["player_name"].lower()})  # type: ignore[index]
    assert first["player_name"] == "Francisco Lindor"
    assert second["player_name"] == "Pete Alonso"


def test_three_mutations_produce_queue_seed_resolved() -> None:
    excerpt = "Draft queue\nFrancisco Lindor\nPete Alonso\nJuan Soto\nClear Draft Queue\n"
    meta = {
        "seed_steps": [
            {"click_dispatched": True, "mutation_proven": True, "mutation_observed": True, "player_name": "Francisco Lindor"},
            {"click_dispatched": True, "mutation_proven": True, "mutation_observed": True, "player_name": "Pete Alonso"},
            {"click_dispatched": True, "mutation_proven": True, "mutation_observed": True, "player_name": "Juan Soto"},
        ],
        "queue_order_established": True,
        "queue_container": {"excerpt": excerpt, "players": []},
        "add_actions": [],
        "pick_index_zero_after_setup": True,
        "paused_state_maintained": True,
    }
    ev = build_queue_seed_evidence(meta, min_players=3)
    assert ev["queue_seed_resolved"] is True


def test_click_without_mutation_is_not_resolved() -> None:
    meta = {
        "seed_steps": [
            {"click_dispatched": True, "mutation_proven": False, "player_name": "Francisco Lindor", "classification": QUEUE1C},
        ],
        "queue_order_established": False,
        "queue_container": {"excerpt": "Draft queue\n", "players": []},
        "add_actions": [],
        "pick_index_zero_after_setup": True,
        "paused_state_maintained": True,
    }
    ev = build_queue_seed_evidence(meta, min_players=3)
    assert ev["queue_seed_resolved"] is False


def test_ambiguous_binding_classified_queue1b() -> None:
    meta = {
        "seed_steps": [{"classification": QUEUE1B}],
        "surface_activation_queue_mutation": False,
    }
    assert classify_queue_seed_boundary(meta) == QUEUE1B


def test_rejects_why_recommended_as_player() -> None:
    from stage1_add_to_queue_delivery import is_valid_seed_player_name, select_next_seed_candidate

    assert is_valid_seed_player_name("Why Recommended") is False
    assert is_valid_seed_player_name("Francisco Lindor") is True
    candidates = [
        {"global_index": 0, "player_name": "Why Recommended", "binding_confidence": "unique"},
        {"global_index": 1, "player_name": "Pete Alonso", "binding_confidence": "unique"},
    ]
    pick, _ = select_next_seed_candidate(candidates, exclude_player_names=set())
    assert pick and pick["player_name"] == "Pete Alonso"


def test_name_only_queue_rows_still_parse() -> None:
    text = "Draft queue\nFrancisco Lindor\nPete Alonso\nClear Draft Queue\n"
    names = [p["name"] for p in parse_queue_players_from_block(text)]
    assert names == ["Francisco Lindor", "Pete Alonso"]
