"""Tests for RV declaration occurrence counter and post-delivery proof grading."""

from __future__ import annotations

from solo_countdown_wake_micro_core import MicroCycleResult

from live_draft_solo_rv_control_probe import mount_with_rv_control_declaration
from live_draft_solo_rv_declaration_ledger import (
    RV_DECLARATION_OCC_BY_RUN_KEY,
    current_declaration_occurrence,
    evaluate_post_delivery_proof,
    increment_declaration_occurrence,
    ledger_post_delivery_proof_satisfied,
    micro_cycle_to_ledger_fields,
)


class _Slot:
    def code(self, *_a, **_k):
        return None


class _St:
    session_state: dict


def test_declaration_occurrence_persists_across_reruns():
    session = {"_solo_rv_run_id": "run-x"}
    assert increment_declaration_occurrence(session, "run-x") == 1
    assert increment_declaration_occurrence(session, "run-x") == 2
    session["live_draft_room"] = None
    assert current_declaration_occurrence(session, "run-x") == 2
    assert int((session.get(RV_DECLARATION_OCC_BY_RUN_KEY) or {})["run-x"]) == 2


def test_component_return_exact_proves_post_delivery():
    micro = micro_cycle_to_ledger_fields(
        MicroCycleResult(
            widget_key="solo_countdown_wake_solo_persistent",
            token="R|0|1.0",
            delivered=False,
            raw_received=True,
            on_change_fired=False,
            stages=[],
            component_return="R|0|1.0",
        )
    )
    ok, src = evaluate_post_delivery_proof(
        expected_token="R|0|1.0",
        widget_key="solo_countdown_wake_solo_persistent",
        location="ldr_page_entry_early_persistent",
        occurrence=2,
        micro=micro,
        ss_after="missing",
        coalesced="",
        browser_send_observed=True,
    )
    assert ok is True
    assert src == "component_return_exact"


def test_session_state_alone_requires_later_occurrence():
    micro = micro_cycle_to_ledger_fields(
        MicroCycleResult(
            widget_key="solo_countdown_wake_solo_persistent",
            token="R|0|1.0",
            delivered=False,
            raw_received=False,
            on_change_fired=False,
            stages=[],
            component_return=None,
        )
    )
    ok, _ = evaluate_post_delivery_proof(
        expected_token="R|0|1.0",
        widget_key="solo_countdown_wake_solo_persistent",
        location="ldr_page_entry_early_persistent",
        occurrence=1,
        micro=micro,
        ss_after="'R|0|1.0'",
        coalesced="",
        browser_send_observed=True,
    )
    assert ok is False
    ok2, src2 = evaluate_post_delivery_proof(
        expected_token="R|0|1.0",
        widget_key="solo_countdown_wake_solo_persistent",
        location="ldr_page_entry_early_persistent",
        occurrence=2,
        micro=micro,
        ss_after="'R|0|1.0'",
        coalesced="",
        browser_send_observed=True,
    )
    assert ok2 is True
    assert src2 == "session_state_exact"


def test_ledger_proof_from_declaration_returned_metadata():
    rows = [
        {
            "event": "declaration_returned",
            "expected_token": "R|0|1.0",
            "extra": {
                "post_delivery_redeclaration_proven": True,
                "proof_source": "component_return_exact",
                "micro_cycle_component_return": "R|0|1.0",
            },
        }
    ]
    ok, src = ledger_post_delivery_proof_satisfied(rows, expected_token="R|0|1.0")
    assert ok is True
    assert src == "component_return_exact"


def test_mount_appends_post_delivery_before_probe_only():
    session = {
        "_solo_rv_run_id": "run-y",
        "_solo_rv_ladder_step": "RV3",
        "_solo_rv_browser_send_observed": True,
        "_solo_persistent_wake_last_token": "R|0|9.0",
        "live_draft_room": {"draft_room_id": "R", "current_pick_index": 0, "timer_deadline": 9.0},
    }
    _St.session_state = session  # type: ignore[misc]
    st = _St()
    slot = _Slot()
    from live_draft_solo_rv3_phase import RV3_PHASE_PRODUCTION_MOUNT, RV3_HYDRATED_KEY

    session["_solo_rv_rv3_phase"] = RV3_PHASE_PRODUCTION_MOUNT
    session["_solo_rv_rv3_phase_run_id"] = "run-y"
    session[RV3_HYDRATED_KEY] = True
    session["_solo_rv_rv3_mount_ok_this_run"] = True
    from live_draft_solo_rv_production_room_setup import RV1_SETUP_OWNER_KEY

    session[RV1_SETUP_OWNER_KEY] = {
        "setup_completed": True,
        "owner_run_id": "run-y",
        "room_id": "R",
        "initial_pick": 0,
        "expected_token": "R|0|9.0",
    }

    def _mount():
        return MicroCycleResult(
            widget_key="solo_countdown_wake_solo_persistent",
            token="R|0|9.0",
            delivered=False,
            raw_received=True,
            on_change_fired=False,
            stages=[],
            component_return="R|0|9.0",
        )

    mount_with_rv_control_declaration(
        st,
        session,
        session["live_draft_room"],
        widget_key="solo_countdown_wake_solo_persistent",
        mount_fn=_mount,
        control_name="RV3",
        location="ldr_page_entry_early_persistent",
        probe_placeholder=slot,
    )
    from live_draft_solo_rv_control_probe import RV_LEDGERS_BY_RUN_KEY

    events = [r.get("event") for r in (session.get(RV_LEDGERS_BY_RUN_KEY) or {}).get("run-y") or []]
    assert "post_delivery_redeclaration" in events
    assert events.index("declaration_returned") < events.index("post_delivery_redeclaration")
