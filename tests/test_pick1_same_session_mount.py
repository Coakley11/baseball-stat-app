"""Same-session pick-1 mount bundle (harness only)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_harness_observability import (  # noqa: E402
    PICK1MOUNT_PASS,
    build_pick1_same_session_mount_bundle,
    persist_pick1_same_session_mount_capture,
)


def test_build_pick1_same_session_mount_pass_classification() -> None:
    ledger = [
        {
            "event": "production_stage1_token_action_complete",
            "ts": 100.0,
            "token": "ABC|0|1.0",
            "room_id": "ABC",
        },
        {
            "event": "production_countdown_declaration_post",
            "pick_index": 1,
            "expected_token": "ABC|1|200.0",
            "room_id": "ABC",
        },
        {
            "event": "production_stage1_cloud_ledger_pipeline_canary",
            "expected_token": "ABC|1|200.0",
            "pick_index": 1,
        },
    ]
    bundle = build_pick1_same_session_mount_bundle(
        next_timer_wait={"status": "observed", "new_token": "ABC|1|200.0"},
        merged_ledger=ledger,
        room_id="ABC",
        iframe_probe={"countdown_iframe": {"connected": True, "href": "solo_countdown"}},
        mount_diag={"expire_token": "ABC|1|200.0", "widget_id": "w1"},
    )
    assert bundle["captured_in_same_browser_session"] is True
    assert bundle["token_action_complete_row"]["event"] == "production_stage1_token_action_complete"
    assert bundle["pick1mount_classification"] == PICK1MOUNT_PASS


def test_persist_pick1_same_session_mount_capture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pick1_same_session_mount_capture.json"
        out = persist_pick1_same_session_mount_capture(path, {"pick1mount_classification": "x"})
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["pick1mount_classification"] == "x"
        assert "persisted_at" in payload
