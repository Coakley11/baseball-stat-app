"""Regression: always-on .ld-rec-card-meta must expose stable player_id.

Covers the AB206337 / e1c76d10 production failure mode where named cards
bound via ld_rec_card_meta had structured_eligible=0 because player_id was
dropped from card meta and render-trace enrichment never ran.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from live_draft_room_ui import build_ld_rec_card_meta_open_tag  # noqa: E402
from stage1_add_to_queue_delivery import (  # noqa: E402
    enrich_seed_candidates_from_render_traces,
    has_structured_seed_identity,
    select_next_seed_candidate,
)
from stage1_rec_queue_click_trace_scrape import (  # noqa: E402
    scrape_rec_queue_render_trace,
    scrape_rec_queue_render_trace_nodes,
)


def test_meta_open_tag_includes_stable_player_id_and_name() -> None:
    tag = build_ld_rec_card_meta_open_tag(player_id="231", player_name="Francisco Lindor")
    assert 'class="ld-rec-card-meta"' in tag
    assert 'data-player-id="231"' in tag
    assert 'data-player-name="Francisco Lindor"' in tag
    assert tag.startswith("<div ") and tag.endswith(">")


def test_meta_open_tag_escapes_attribute_quotes() -> None:
    tag = build_ld_rec_card_meta_open_tag(player_id='12"3', player_name='A "Quote"')
    assert "data-player-id=" in tag
    assert '"' not in tag.split("data-player-id=")[1].split()[0].strip('"') or "&quot;" in tag


def test_ld_rec_card_meta_with_player_id_is_structured_without_name_fallback() -> None:
    """Name alone is insufficient; player_id on meta authorizes deliberate seed."""
    name_only = {
        "global_index": 0,
        "player_name": "Francisco Lindor",
        "binding_confidence": "unique",
        "binding_via": "ld_rec_card_meta",
        "visible": True,
    }
    assert has_structured_seed_identity(name_only) is False

    with_id = {
        **name_only,
        "player_id": "231",
        "structured_identity_source": "ld_rec_card_meta",
        "widget_key": "rec_card_queue_AB206337_0_231_rec_card",
    }
    assert has_structured_seed_identity(with_id) is True
    pick, reason = select_next_seed_candidate([name_only, with_id], exclude_player_names=set())
    assert reason == ""
    assert pick is not None
    assert pick["player_id"] == "231"
    assert pick["player_name"] == "Francisco Lindor"


def test_e1c76d10_style_discovery_snapshot_would_count_structured_eligible() -> None:
    """Simulate post-fix discovery: named meta bindings + player_id => eligible > 0."""
    candidates = [
        {
            "global_index": i,
            "player_name": name,
            "player_id": pid,
            "binding_confidence": "unique",
            "binding_via": "ld_rec_card_meta",
            "structured_identity_source": "ld_rec_card_meta",
            "visible": True,
            "widget_key": f"rec_card_queue_AB206337_0_{pid}_rec_card",
        }
        for i, (name, pid) in enumerate(
            (
                ("Francisco Lindor", "231"),
                ("Ketel Marte", "414"),
                ("Pete Alonso", "592789"),
            )
        )
    ]
    structured_eligible = sum(
        1
        for c in candidates
        if c.get("binding_confidence") == "unique"
        and str(c.get("player_id") or "").strip().isdigit()
        and str(c.get("player_name") or "").strip()
        and has_structured_seed_identity(c)
    )
    assert structured_eligible == 3
    queued: set[str] = set()
    order: list[str] = []
    remaining = list(candidates)
    for _ in range(3):
        pick, reason = select_next_seed_candidate(remaining, exclude_player_names=queued)
        assert reason == ""
        assert pick is not None
        assert str(pick["player_id"]).isdigit()
        queued.add(str(pick["player_name"]).strip().lower())
        order.append(str(pick["player_id"]))
        remaining = [c for c in remaining if c["player_id"] != pick["player_id"]]
    assert order == ["231", "414", "592789"]


def test_scrape_rec_queue_render_trace_nodes_exists_and_collects_rows() -> None:
    class _Page:
        def evaluate(self, _script: str, _player_name: str = "") -> list[dict[str, Any]]:
            return [
                {
                    "player_name": "Francisco Lindor",
                    "player_id": "231",
                    "widget_key": "rec_card_queue_AB206337_0_231_rec_card",
                },
                {
                    "player_name": "Ketel Marte",
                    "player_id": "414",
                    "widget_key": "rec_card_queue_AB206337_0_414_rec_card",
                },
            ]

    nodes = scrape_rec_queue_render_trace_nodes(_Page(), player_name="")
    assert len(nodes) == 2
    assert {n["player_id"] for n in nodes} == {"231", "414"}
    one = scrape_rec_queue_render_trace(_Page(), player_name="Ketel Marte")
    assert one["player_id"] == "414"


def test_render_trace_enrichment_still_attaches_player_id_by_name() -> None:
    cands = [
        {
            "global_index": 0,
            "player_name": "Francisco Lindor",
            "binding_confidence": "unique",
            "binding_via": "ld_rec_card_meta",
            "visible": True,
        }
    ]
    traces = [
        {
            "player_name": "Francisco Lindor",
            "player_id": "231",
            "widget_key": "rec_card_queue_AB206337_0_231_rec_card",
        }
    ]
    enriched = enrich_seed_candidates_from_render_traces(cands, traces)
    assert enriched[0]["player_id"] == "231"
    assert has_structured_seed_identity(enriched[0]) is True
