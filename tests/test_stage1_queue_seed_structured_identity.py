"""Stage1A queue-seed structured player-identity repair regressions (CF12F158).

Local fixtures only. NO browser/network/production.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_add_to_queue_delivery import (  # noqa: E402
    enrich_seed_candidates_from_render_traces,
    extract_player_names_from_lines,
    has_structured_seed_identity,
    is_recommendation_badge_label,
    is_valid_seed_player_name,
    select_next_seed_candidate,
)


def _structured(
    name: str,
    *,
    gi: int = 0,
    player_id: str = "231",
    via: str = "ld_rec_card_meta",
    room: str = "CF12F158",
    pick: int = 0,
) -> dict[str, Any]:
    return {
        "global_index": gi,
        "player_name": name,
        "player_id": str(player_id),
        "binding_confidence": "unique",
        "binding_via": via,
        "visible": True,
        "widget_key": f"rec_card_queue_{room}_{pick}_{player_id}_rec_card",
        "structured_identity_source": (
            "ld_rec_card_meta+render_trace" if via == "ld_rec_card_meta" else "render_trace"
        ),
    }


def test_badge_labels_never_valid_seed_player_names() -> None:
    for label in ("Best Value", "Best Overall", "Second Best", "Third Best"):
        assert is_recommendation_badge_label(label) is True
        assert is_valid_seed_player_name(label) is False


def test_product_badge_vocabulary_rejected_when_name_like() -> None:
    for label in (
        "Market Discount",
        "ADP Bargain",
        "Power Upgrade",
        "Speed Upgrade",
        "Average Stabilizer",
        "Run Production Boost",
        "Runs Boost",
        "On-Base Boost",
        "Contact Boost",
        "Scarcity Rising",
        "SS Scarcity Rising",
        "Best Remaining SS",
        "Fills 2 OF Slots",
        "Fills SS Slot",
        "Category Boost: HR",
    ):
        assert is_recommendation_badge_label(label) is True, label
        assert is_valid_seed_player_name(label) is False, label


def test_historical_structured_players_still_valid() -> None:
    for name, pid in (
        ("Francisco Lindor", "231"),
        ("Ketel Marte", "414"),
        ("Pete Alonso", "592789"),
    ):
        assert is_valid_seed_player_name(name) is True
        cand = _structured(name, player_id=pid)
        assert has_structured_seed_identity(cand) is True
        pick, reason = select_next_seed_candidate([cand], exclude_player_names=set())
        assert reason == ""
        assert pick and pick["player_name"] == name
        assert pick["player_id"] == pid
        assert pick["widget_key"] == f"rec_card_queue_CF12F158_0_{pid}_rec_card"


def test_cf12f158_best_value_visible_text_only_ineligible() -> None:
    """CF12F158 shape: badge + Add to Queue + Why Recommended, no structured identity."""
    cand = {
        "global_index": 6,
        "player_name": "Best Value",
        "binding_confidence": "unique",
        "binding_via": "single_visible_add_ancestor",
        "visible": True,
        "container_sample": (
            "Best Value\n\n🔴 Draft Player\n\n⭐ Add to Queue\n\nkeyboard_arrow_right\n\nWhy Recommended"
        ),
        "button_text": "⭐ Add to Queue",
    }
    assert is_valid_seed_player_name("Best Value") is False
    assert has_structured_seed_identity(cand) is False
    pick, reason = select_next_seed_candidate([cand], exclude_player_names=set())
    assert pick is None
    assert reason in {"no_viable_candidate", "missing_structured_identity"}
    assert pick is None or pick.get("player_name") != "Best Value"


def test_shallow_ancestor_best_value_no_widget_key_no_auth_path() -> None:
    cand = {
        "global_index": 0,
        "player_name": "Best Value",
        "binding_confidence": "unique",
        "binding_via": "single_visible_add_ancestor",
        "visible": True,
        "player_id": "",
        "widget_key": "",
    }
    pick, _ = select_next_seed_candidate([cand], exclude_player_names=set())
    assert pick is None
    assert has_structured_seed_identity(cand) is False
    assert not str(cand.get("widget_key") or "").strip()


def test_mixed_badge_plus_structured_meta_prefers_real_player() -> None:
    """Same card: badge Best Value + structured Francisco Lindor meta/render-trace."""
    badge_noise = {
        "global_index": 0,
        "player_name": "Best Value",
        "binding_confidence": "unique",
        "binding_via": "single_visible_add_ancestor",
        "visible": True,
    }
    real = _structured("Francisco Lindor", gi=1, player_id="231", via="ld_rec_card_meta")
    pick, reason = select_next_seed_candidate(
        [badge_noise, real],
        exclude_player_names=set(),
    )
    assert reason == ""
    assert pick is not None
    assert pick["player_name"] == "Francisco Lindor"
    assert pick["player_id"] == "231"
    assert pick["binding_via"] == "ld_rec_card_meta"
    assert "Best Value" not in str(pick["player_name"])


def test_extract_names_skips_badge_keeps_player() -> None:
    lines = [
        "Best Value",
        "Best Overall",
        "Francisco Lindor",
        "SS — NYM",
        "⭐ Add to Queue",
        "Why Recommended",
    ]
    assert extract_player_names_from_lines(lines) == ["Francisco Lindor"]


def test_visible_text_only_real_name_without_player_id_ineligible() -> None:
    cand = {
        "global_index": 0,
        "player_name": "Francisco Lindor",
        "binding_confidence": "unique",
        "binding_via": "single_visible_add_ancestor",
        "visible": True,
    }
    assert is_valid_seed_player_name("Francisco Lindor") is True
    assert has_structured_seed_identity(cand) is False
    pick, reason = select_next_seed_candidate([cand], exclude_player_names=set())
    assert pick is None
    assert reason == "missing_structured_identity"


def test_render_trace_enrichment_can_authorize_meta_candidate() -> None:
    raw = {
        "global_index": 0,
        "player_name": "Ketel Marte",
        "binding_confidence": "unique",
        "binding_via": "ld_rec_card_meta",
        "visible": True,
    }
    traces = [
        {
            "player_name": "Ketel Marte",
            "player_id": "414",
            "widget_key": "rec_card_queue_CF12F158_0_414_rec_card",
        }
    ]
    enriched = enrich_seed_candidates_from_render_traces([raw], traces)
    assert enriched[0]["player_id"] == "414"
    assert enriched[0]["widget_key"].endswith("_414_rec_card")
    assert has_structured_seed_identity(enriched[0]) is True
    pick, reason = select_next_seed_candidate(enriched, exclude_player_names=set())
    assert reason == ""
    assert pick and pick["player_name"] == "Ketel Marte"
    assert pick["player_id"] == "414"


def test_best_value_cannot_become_player_name_even_with_fake_id() -> None:
    """Badge text remains invalid even if a bogus player_id is attached."""
    cand = {
        "global_index": 0,
        "player_name": "Best Value",
        "player_id": "999",
        "binding_confidence": "unique",
        "binding_via": "ld_rec_card_meta",
        "visible": True,
        "structured_identity_source": "ld_rec_card_meta+render_trace",
        "widget_key": "rec_card_queue_CF12F158_0_999_rec_card",
    }
    assert is_valid_seed_player_name("Best Value") is False
    assert has_structured_seed_identity(cand) is False
    pick, _ = select_next_seed_candidate([cand], exclude_player_names=set())
    assert pick is None
