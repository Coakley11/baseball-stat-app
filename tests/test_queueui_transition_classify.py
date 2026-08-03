"""QUEUEUI transition classifier unit tests (harness only)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from queueui_transition_diagnostic import (  # noqa: E402
    QUEUEUI2,
    QUEUEUI9,
    build_room_identity_table,
    classify_queueui_boundary,
)


def test_identity_mismatch_server_vs_client_empty() -> None:
    snap = {
        "visible_room_id": "",
        "python_room_id": "",
        "key_ownership_last": {"live_draft_room_present": False},
        "text_head": "",
        "mount": {},
        "page_url": "https://example/?active_page=Live%20Draft%20Room",
        "has_start_new_text": True,
        "pause_draft_count": 0,
    }
    cls, side, _ = classify_queueui_boundary(
        server_latch={"ok": True, "server_room_id": "ABCD1234"},
        snap=snap,
        ledger_summary={"handler_exited": True},
        gate_eval={"passed": False, "checks": {"latched_room_visible_agrees": False}},
        console_errors=[],
        page_errors=[],
    )
    assert cls == QUEUEUI2
    assert side == "application_side"


def test_exception_classifies_queueui9() -> None:
    snap = {"text_head": "traceback (most recent call last)", "mount": {}, "key_ownership_last": {}}
    cls, _, _ = classify_queueui_boundary(
        server_latch={"ok": False},
        snap=snap,
        ledger_summary={},
        gate_eval={"passed": False, "checks": {}},
        console_errors=[],
        page_errors=[],
    )
    assert cls == QUEUEUI9


def test_identity_table_pairwise() -> None:
    snap = {
        "visible_room_id": "ROOM1111",
        "python_room_id": "ROOM1111",
        "key_ownership_last": {
            "live_draft_room_id": "ROOM1111",
            "page_filter_room_id": "ROOM1111",
            "live_draft_room_present": True,
        },
        "page_url": "https://x/?active_page=Live%20Draft%20Room",
        "mount": {"draft_id": "ROOM1111"},
    }
    table = build_room_identity_table(server_room_id="ROOM1111", snap=snap)
    assert table["pairwise"]["server_vs_visible"] == "equal"
