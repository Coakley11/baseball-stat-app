"""Tests for native Streamlit RV control ledger."""

from __future__ import annotations

import base64
import json
from typing import Any

from live_draft_solo_rv_control_probe import (
    RV_LEDGER_B64_PREFIX,
    RV_LEDGERS_BY_RUN_KEY,
    append_control_event,
    decode_control_probe_text,
    encode_control_probe_payload,
    mount_with_rv_control_declaration,
    render_native_control_probe,
)


class _CodeCapture:
    def __init__(self) -> None:
        self.last: str = ""

    def code(self, body: str, language: Any = None) -> None:
        self.last = str(body)


class _EmptySlot:
    def __init__(self) -> None:
        self.capture = _CodeCapture()

    def code(self, body: str, language: Any = None) -> None:
        self.capture.code(body, language)


class _FakeSession(dict):
    pass


class _St:
    session_state: _FakeSession

    @staticmethod
    def empty() -> _EmptySlot:
        return _EmptySlot()


def test_decode_native_prefix_roundtrip() -> None:
    payload = {"run_id": "r1", "rows": [{"event": "script_begin"}]}
    line = encode_control_probe_payload(payload)
    assert line.startswith(RV_LEDGER_B64_PREFIX)
    decoded = decode_control_probe_text("noise\n" + line + "\nmore")
    assert decoded.get("run_id") == "r1"
    assert len(decoded.get("rows") or []) == 1


def test_ledger_persists_and_renders_native_probe() -> None:
    session: dict[str, Any] = _FakeSession()
    session["_solo_rv_run_id"] = "run-a"
    session["_solo_rv_ladder_step"] = "RV0"
    session["_solo_parity_expected_token"] = "TOK"
    _St.session_state = session  # type: ignore[misc]

    st = _St()
    slot = st.empty()

    append_control_event(st, session, "script_begin", control_name="RV0")
    render_native_control_probe(st, session, slot)
    assert RV_LEDGER_B64_PREFIX in slot.capture.last

    mount_with_rv_control_declaration(
        st,
        session,
        {"draft_id": "PARITY", "current_pick_index": 0},
        widget_key="solo_countdown_wake_solo_persistent",
        mount_fn=lambda: "TOK",
        control_name="RV0",
        location="test",
        probe_placeholder=slot,
    )
    store = session.get(RV_LEDGERS_BY_RUN_KEY) or {}
    events = {r.get("event") for r in store.get("run-a") or []}
    assert "declaration_attempt" in events
    assert "declaration_returned" in events
    decoded = decode_control_probe_text(slot.capture.last)
    assert len(decoded.get("rows") or []) >= 3
