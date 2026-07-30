"""Tests for Stage 1 boundary canaries (observability only)."""

from __future__ import annotations

from live_draft_stage1_boundary_canaries import (
    emit_production_global_script_run_canary,
    stage1_boundary_canaries_enabled,
)


class _FakeSessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def test_global_canary_emits_when_diag_enabled():
    session = {
        "_solo_component_diag_enabled": True,
        "active_page": "Live Draft Room",
        "live_draft_room": {"draft_room_id": "ABCD1234", "status": "in_progress", "current_pick_index": 0},
    }
    st = _FakeSessionState(session)
    assert stage1_boundary_canaries_enabled(st, session)
    row = emit_production_global_script_run_canary(st, session, active_page="Live Draft Room")
    assert row.get("event") == "production_global_script_run_canary"
    assert row.get("room_id") == "ABCD1234"
    ledger = session.get("_solo_stage1_production_ledger") or []
    assert any(r.get("event") == "production_global_script_run_canary" for r in ledger)
