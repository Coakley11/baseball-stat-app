"""Ledger pipeline canary classification."""

from __future__ import annotations

from typing import Any

from live_draft_stage1_ledger_pipeline import (
    PIPELINE_CANARY_EVENT,
    STAGE_P5,
    classify_first_ledger_pipeline_failure,
    emit_cloud_ledger_pipeline_canary,
)


def test_pipeline_canary_stores_in_session_ledger() -> None:
    session: dict[str, Any] = {"_solo_component_diag_enabled": True}
    emit_cloud_ledger_pipeline_canary(None, session)
    rows = list(session.get("_solo_stage1_production_ledger") or [])
    assert any(r.get("event") == PIPELINE_CANARY_EVENT for r in rows)


def test_classify_ledgers6_when_p5_missing() -> None:
    ev = classify_first_ledger_pipeline_failure(
        pipeline_dom={"p1": 1, "p2": 1, "p3": 1, "p4": 1, "p5": 0},
        ledger_rows=[],
        artifact_has_canary=False,
    )
    assert ev.get("first_missing_stage") == STAGE_P5
    assert "LEDGER6" in str(ev.get("classification"))
