"""Stage 1A-CORE split status model (harness only)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_harness_observability import build_stage1a_core_status_model  # noqa: E402


def test_functional_pass_ui_gap_not_functional_fail() -> None:
    status = build_stage1a_core_status_model(
        functional_verdict="PASS",
        observability_verdict="FAIL",
        timer_classification="T2_SERVER_TIMER_CREATED_COMPONENT_NOT_DECLARED",
        server_next_timer={
            "server_expected_token": "ROOM|1|200.0",
            "server_deadline": "200.0",
        },
        pick1_mount={"pick1_component_mount_proven": False},
        overall_classification="STAGE1A_CORE_PASS — WITH HARNESS OBSERVABILITY CORRECTIONS",
    )
    assert status["stage1a_core_functional_outcome"] == "PASS"
    assert status["stage1a_core_observability_outcome"] == "PICK1_COMPONENT_MOUNT_NOT_PROVEN"
    assert status["stage1a_core_overall"] == "PASS_WITH_OBSERVABILITY_GAP"
    assert status["ui_scrape_must_not_override_functional_pass"] is True
