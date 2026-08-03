"""FOCUSGATE replay for focused run 4c7d5ee7."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from p8_focused_gate_replay import FOCUSGATE3, replay_4c7d5ee7  # noqa: E402
from live_draft_solo_p8_focused_binding import (  # noqa: E402
    SOLO_P8_AUTH_STATE_KEY,
    SOLO_P8_FOCUSED_TXN_KEY,
    bootstrap_solo_p8_focused_binding,
    get_effective_focused_binding_context,
    solo_p8_focused_binding_effective,
)
from unittest import mock


def test_4c7d5ee7_replay_classifies_focusgate3() -> None:
    art = ROOT / "data" / "production_p8_binding_diagnostic.json"
    if not art.is_file():
        return
    raw = json.loads(art.read_text(encoding="utf-8"))
    if raw.get("harness_run_id") != "4c7d5ee7b1324a8a":
        return
    replay = replay_4c7d5ee7(art)
    assert replay["focused_gate_classification"]["classification"] == FOCUSGATE3
    assert replay["invariants"].get("try_claim_call_count") == 1


def test_focused_txn_rehydrates_without_query_param() -> None:
    st = mock.MagicMock()
    st.query_params = {}
    session = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_streamlit_session_id": "sess-a",
        "_solo_stage1_run_id": "apprun123456789012345678901234567890",
        "_solo_stage1_deployment_sha": "cff25b8",
        SOLO_P8_AUTH_STATE_KEY: {
            "focused_authorized": True,
            "focused_effective": True,
            "authorization_result": "authorized",
        },
        SOLO_P8_FOCUSED_TXN_KEY: {
            "harness_run_id": "4c7d5ee7b1324a8a",
            "application_diagnostic_run_id": "apprun123456789012345678901234567890",
            "streamlit_session_id": "sess-a",
            "build_sha": "cff25b8",
            "created_ts": 1.0,
            "expires_ts": 9999999999.0,
            "terminal": False,
            "component_diag_armed": True,
            "focused_param_seen": True,
        },
        "_solo_p8_harness_transaction_id": "4c7d5ee7b1324a8a",
    }
    assert solo_p8_focused_binding_effective(st, session)
    assert get_effective_focused_binding_context(st, session).get("effective")


def test_query_param_alone_still_not_sufficient_without_txn() -> None:
    st = mock.MagicMock()
    st.query_params = {"solo_p8_focused_binding": "1", "solo_p8_harness_run_id": "abcd1234abcd1234"}
    session: dict = {}
    bootstrap_solo_p8_focused_binding(st, session)
    assert not solo_p8_focused_binding_effective(st, session)
