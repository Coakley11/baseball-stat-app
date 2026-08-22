"""Browser-free regression for pick0 evidence-rebuild / stale-classification abort.

Historical defect (room 6D002864):
  finalize → resolved=true, classification=QUEUE_SEED_RESOLVED
  provisional pick0=false → evidence false, classification STALE success retained
  final pick0=true without rebuild → queue_contains_player still false → abort
  first_boundary incorrectly reported QUEUE_SEED_RESOLVED
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage1_queue_seed_harness import (  # noqa: E402
    QUEUE_SEED_RESOLVED,
    apply_queue_seed_evidence,
    build_queue_seed_evidence,
    queue_seed_unresolved_boundary,
)


def _q3_meta(
    *,
    pick0: bool = True,
    paused: bool = True,
    order: bool = True,
    names: list[str] | None = None,
    duplicate_third: bool = False,
) -> dict:
    players = names or ["Francisco Lindor", "Ketel Marte", "Pete Alonso"]
    if duplicate_third:
        players = [players[0], players[1], players[0]]
    steps = [
        {
            "click_dispatched": True,
            "mutation_proven": True,
            "player_name": n,
        }
        for n in players
    ]
    return {
        "seed_steps": steps,
        "add_actions": steps,
        "proven_queue_order": list(dict.fromkeys(players)),
        "queue_order": list(dict.fromkeys(players)),
        "queue_order_established": order,
        "pick_index_zero_after_setup": pick0,
        "paused_state_maintained": paused,
        # Stale visible UI must not drive resolved.
        "queue_container": {
            "excerpt": "Draft queue\nQueue empty — add from Live Draft Room.\nClear Draft Queue\n",
            "players": [],
            "empty": True,
            "found": True,
        },
        "queue_excerpt_before": "Draft queue\nQueue empty — add from Live Draft Room.\n",
    }


def _runner_precondition_from_final_pick0(meta: dict, *, final_pick0: bool) -> dict:
    """Mirror production gate: set final pick0 authority then rebuild evidence once."""
    out = copy.deepcopy(meta)
    out["pick_index_zero_after_setup"] = bool(final_pick0)
    out["pick_index_zero_observation_provisional"] = False
    out["paused_state_maintained"] = True
    apply_queue_seed_evidence(out, min_players=3)
    resolved = bool((out.get("queue_evidence") or {}).get("queue_seed_resolved"))
    abort = not resolved
    first_boundary = ""
    if abort:
        first_boundary = queue_seed_unresolved_boundary(out, min_players=3)
        if first_boundary == QUEUE_SEED_RESOLVED:
            first_boundary = "queue_seed_evidence_unresolved"
    return {
        "meta": out,
        "abort": abort,
        "first_boundary": first_boundary,
        "queue_seed_resolved": resolved,
        "queue_contains_player": bool(out.get("queue_contains_player")),
        "classification": out.get("classification"),
        "ok": bool(out.get("ok")),
    }


def test_historical_stale_classification_without_final_rebuild_would_abort() -> None:
    """Document the pre-repair failure mode (provisional false evidence left in place)."""
    meta = _q3_meta(pick0=True)
    apply_queue_seed_evidence(meta)
    assert meta["classification"] == QUEUE_SEED_RESOLVED
    meta["pick_index_zero_after_setup"] = False
    # Pre-repair pattern: rebuild evidence but keep success classification.
    ev = build_queue_seed_evidence(meta, min_players=3)
    meta["queue_evidence"] = ev
    meta["queue_contains_player"] = bool(ev.get("queue_seed_resolved"))
    # Intentionally leave classification=QUEUE_SEED_RESOLVED (historical bug).
    assert ev["queue_seed_resolved"] is False
    assert meta["classification"] == QUEUE_SEED_RESOLVED
    assert meta["queue_contains_player"] is False
    # Later pick0 true WITHOUT rebuild → still abort on stale boolean.
    meta["pick_index_zero_after_setup"] = True
    assert meta["queue_contains_player"] is False
    assert meta["classification"] == QUEUE_SEED_RESOLVED


def test_full_path_provisional_false_then_final_true_rebuilds_resolved() -> None:
    meta = _q3_meta(pick0=True)
    apply_queue_seed_evidence(meta)
    assert meta["classification"] == QUEUE_SEED_RESOLVED

    meta["pick_index_zero_after_setup"] = False
    apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"]["queue_seed_resolved"] is False
    assert meta["queue_contains_player"] is False
    assert meta["classification"] != QUEUE_SEED_RESOLVED
    assert meta["classification"] == "pick_index_zero_after_setup"
    assert meta["ok"] is False

    gate = _runner_precondition_from_final_pick0(meta, final_pick0=True)
    assert gate["abort"] is False
    assert gate["queue_seed_resolved"] is True
    assert gate["queue_contains_player"] is True
    assert gate["classification"] == QUEUE_SEED_RESOLVED
    assert gate["ok"] is True
    assert gate["first_boundary"] == ""


def test_room_6d002864_replay_lindor_marte_alonso() -> None:
    meta = _q3_meta(
        pick0=True,
        names=["Francisco Lindor", "Ketel Marte", "Pete Alonso"],
    )
    apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"]["proven_queue_identities"] == [
        "Francisco Lindor",
        "Ketel Marte",
        "Pete Alonso",
    ]
    meta["pick_index_zero_after_setup"] = False
    apply_queue_seed_evidence(meta)
    assert meta["classification"] == "pick_index_zero_after_setup"
    gate = _runner_precondition_from_final_pick0(meta, final_pick0=True)
    assert gate["abort"] is False
    assert gate["classification"] == QUEUE_SEED_RESOLVED
    assert gate["queue_contains_player"] is True
    # Visible empty excerpt must not override authoritative identities.
    assert gate["meta"]["queue_evidence"]["visible_queue_player_names"] == []
    assert gate["meta"]["queue_evidence"]["proven_identity_count"] == 3


def test_final_pick0_false_fails_closed_and_boundary_is_pick0() -> None:
    meta = _q3_meta(pick0=True)
    apply_queue_seed_evidence(meta)
    gate = _runner_precondition_from_final_pick0(meta, final_pick0=False)
    assert gate["abort"] is True
    assert gate["queue_seed_resolved"] is False
    assert gate["queue_contains_player"] is False
    assert gate["classification"] != QUEUE_SEED_RESOLVED
    assert gate["classification"] == "pick_index_zero_after_setup"
    assert gate["first_boundary"] == "pick_index_zero_after_setup"


def test_two_players_unresolved() -> None:
    meta = _q3_meta(names=["Francisco Lindor", "Ketel Marte"])
    # Only two deliberate steps.
    meta["seed_steps"] = meta["seed_steps"][:2]
    meta["add_actions"] = meta["seed_steps"]
    apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"]["queue_seed_resolved"] is False
    assert meta["classification"] != QUEUE_SEED_RESOLVED
    assert meta["classification"] in {
        "insufficient_deliberate_seed_clicks",
        "insufficient_distinct_seed_players",
    }


def test_duplicate_identity_unresolved() -> None:
    meta = _q3_meta(duplicate_third=True)
    apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"]["proven_identity_count"] == 2
    assert meta["queue_evidence"]["queue_seed_resolved"] is False
    assert meta["classification"] != QUEUE_SEED_RESOLVED


def test_order_not_established_unresolved() -> None:
    meta = _q3_meta(order=False)
    apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"]["queue_seed_resolved"] is False
    assert meta["classification"] == "queue_order_not_established"


def test_paused_false_unresolved() -> None:
    meta = _q3_meta(paused=False)
    apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"]["queue_seed_resolved"] is False
    assert meta["classification"] == "paused_state_maintained"


def test_rebuild_false_clears_prior_success_classification() -> None:
    meta = _q3_meta(pick0=True)
    apply_queue_seed_evidence(meta)
    assert meta["classification"] == QUEUE_SEED_RESOLVED
    meta["pick_index_zero_after_setup"] = False
    apply_queue_seed_evidence(meta)
    assert meta["classification"] != QUEUE_SEED_RESOLVED
    assert (meta.get("queue_evidence") or {}).get("queue_seed_resolved") is False


def test_rebuild_true_restores_success_after_prior_false() -> None:
    meta = _q3_meta(pick0=False)
    apply_queue_seed_evidence(meta)
    assert meta["classification"] != QUEUE_SEED_RESOLVED
    meta["pick_index_zero_after_setup"] = True
    apply_queue_seed_evidence(meta)
    assert meta["classification"] == QUEUE_SEED_RESOLVED
    assert meta["ok"] is True
    assert meta["queue_contains_player"] is True


def test_derived_fields_same_evidence_generation() -> None:
    meta = _q3_meta(pick0=True)
    ev = apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"] is ev
    assert meta["queue_contains_player"] is True
    assert meta["ok"] is True
    assert meta["classification"] == QUEUE_SEED_RESOLVED
    assert ev["queue_seed_resolved"] is True
    meta["pick_index_zero_after_setup"] = False
    ev2 = apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"] is ev2
    assert meta["queue_contains_player"] is False
    assert meta["ok"] is False
    assert meta["classification"] != QUEUE_SEED_RESOLVED
    assert ev2["queue_seed_resolved"] is False


def test_visible_queue_empty_cannot_override_authoritative_q3() -> None:
    meta = _q3_meta(pick0=True)
    apply_queue_seed_evidence(meta)
    ev = meta["queue_evidence"]
    assert ev["visible_queue_player_names"] == []
    assert ev["proven_identity_count"] == 3
    assert ev["queue_seed_resolved"] is True


def test_classification_resolved_invariant_at_precondition() -> None:
    meta = _q3_meta(pick0=True)
    gate = _runner_precondition_from_final_pick0(meta, final_pick0=True)
    if gate["classification"] == QUEUE_SEED_RESOLVED:
        assert gate["queue_seed_resolved"] is True
        assert (gate["meta"].get("queue_evidence") or {}).get("queue_seed_resolved") is True
    gate2 = _runner_precondition_from_final_pick0(meta, final_pick0=False)
    if gate2["queue_seed_resolved"] is False:
        assert gate2["classification"] != QUEUE_SEED_RESOLVED


def test_first_boundary_not_success_label_when_pick0_fails() -> None:
    meta = _q3_meta(pick0=True)
    gate = _runner_precondition_from_final_pick0(meta, final_pick0=False)
    assert gate["abort"] is True
    assert gate["first_boundary"] == "pick_index_zero_after_setup"
    assert gate["first_boundary"] != QUEUE_SEED_RESOLVED


def test_first_boundary_order_predicate() -> None:
    meta = _q3_meta(order=False)
    apply_queue_seed_evidence(meta)
    assert queue_seed_unresolved_boundary(meta) == "queue_order_not_established"
    assert meta["classification"] != QUEUE_SEED_RESOLVED


def test_sequential_three_player_seed_regression() -> None:
    names = ["A Player", "B Player", "C Player"]
    meta = _q3_meta(names=names)
    apply_queue_seed_evidence(meta)
    assert meta["queue_evidence"]["proven_queue_identities"] == names
    assert meta["classification"] == QUEUE_SEED_RESOLVED
