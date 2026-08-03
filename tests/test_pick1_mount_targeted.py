"""Targeted PICK1MOUNT classification (harness only)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_harness_observability import PICK1MOUNT1, classify_pick1_mount  # noqa: E402


def test_pick1mount1_server_token_no_declaration() -> None:
    cls = classify_pick1_mount(
        expected_pick1_token="3BEEA6F2|1|1785728385.690",
        expected_room_id="3BEEA6F2",
        observation={
            "server_pick1_token_proven": True,
            "countdown_declaration_pre_pick1": {},
            "countdown_declaration_post_pick1": {},
            "pick1_component_mount_proven": False,
        },
        live_context={"room_id": "", "pick_index": None},
    )
    assert cls["pick1mount_classification"] == PICK1MOUNT1
