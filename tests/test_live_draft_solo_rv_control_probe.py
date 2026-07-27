"""Session-state persistence for RV control ledger."""

from __future__ import annotations

from typing import Any

from live_draft_solo_rv_control_probe import (
    RV_LEDGERS_BY_RUN_KEY,
    append_control_event,
    mount_with_rv_control_declaration,
)


class _FakeSession(dict):
    pass


def test_ledger_persists_across_appends() -> None:
    session: dict[str, Any] = _FakeSession()
    session["_solo_rv_run_id"] = "run-a"
    session["_solo_rv_ladder_step"] = "RV0"
    session["_solo_parity_expected_token"] = "TOK"

    class St:
        session_state = session

        @staticmethod
        def empty():
            return None

        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)

    st = St()

    append_control_event(st, session, "script_begin", control_name="RV0")
    store = session.get(RV_LEDGERS_BY_RUN_KEY) or {}
    assert "run-a" in store
    assert len(store["run-a"]) >= 1

    mount_with_rv_control_declaration(
        st,
        session,
        {"draft_id": "PARITY", "current_pick_index": 0},
        widget_key="solo_countdown_wake_solo_persistent",
        mount_fn=lambda: "TOK",
        control_name="RV0",
        location="test",
    )
    store2 = session.get(RV_LEDGERS_BY_RUN_KEY) or {}
    events = {r.get("event") for r in store2.get("run-a") or []}
    assert "declaration_attempt" in events
    assert "declaration_returned" in events
