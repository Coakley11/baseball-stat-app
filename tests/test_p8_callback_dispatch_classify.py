"""CM dispatch pass / CM3 suppression and VALUE1–VALUE10 harness classifiers."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.p8_callback_boundary_classify import classify_callback_boundary
from scripts.p8_callback_metadata_classify import (
    BACKEND_STATE,
    CALLBACK_DISPATCH_EVALUATED,
    CM_DISPATCH_PASS,
    PROD_ENTERED,
    classify_callback_metadata_boundary,
)
from scripts.p8_callback_value_loss_classify import (
    VALUE1,
    VALUE4,
    classify_value_loss_boundary,
)
from scripts.p8_expiration_token_raw import build_expiration_token_raw_report

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "data" / "production_callback_metadata_diagnostic.json"
EXACT = "12E729A7|0|1785630315.461"


def _dispatch_row(**extra: object) -> dict:
    base = {
        "event": CALLBACK_DISPATCH_EVALUATED,
        "widget_key": "solo_countdown_wake_solo_persistent",
        "callback_selected": True,
        "widget_changed_result": True,
        "new_value_repr": f"'{EXACT}'",
    }
    base.update(extra)
    return base


def _backend_row(**extra: object) -> dict:
    base = {
        "event": BACKEND_STATE,
        "widget_key": "solo_countdown_wake_solo_persistent",
        "in_new_widget_state": False,
        "widget_changed": True,
        "deserialized_value_repr": f"'{EXACT}'",
    }
    base.update(extra)
    return base


def _prod_entered(**extra: object) -> dict:
    base = {
        "event": PROD_ENTERED,
        "widget_key": "solo_countdown_wake_solo_persistent",
        "session_state_key_exists": True,
        "session_state_value_repr": f"'{EXACT}'",
    }
    base.update(extra)
    return base


def _prod_exited(**extra: object) -> dict:
    base = {
        "event": "production_stage1_prod_on_change_exited",
        "widget_key": "solo_countdown_wake_solo_persistent",
        "session_state_value_at_exit_repr": "None",
        "session_state_key_exists_at_exit": True,
    }
    base.update(extra)
    return base


def test_cm3_suppressed_when_callback_invoked_with_dispatch_proof() -> None:
    rows = [_dispatch_row(), _backend_row(), _prod_entered(), _prod_exited()]
    cm = classify_callback_metadata_boundary(
        filtered_rows=rows,
        exact_token=EXACT,
        production_widget_key="solo_countdown_wake_solo_persistent",
    )
    assert CM_DISPATCH_PASS.split(" ")[0] in cm["classification"]
    assert "CM3" not in cm["classification"]
    assert cm.get("cm3_suppressed") is True


def test_aa04920d_artifact_relabels_cm_dispatch_pass_without_cloud_rerun() -> None:
    if not ARTIFACT.is_file():
        return
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    exp = report.get("production_expiration") or {}
    rows = list(exp.get("filtered_ledger_rows") or [])
    token = str(report.get("production_exact_token") or EXACT).strip()
    if not rows:
        return
    cm = classify_callback_metadata_boundary(
        filtered_rows=rows,
        exact_token=token,
        production_widget_key="solo_countdown_wake_solo_persistent",
    )
    assert "CM3" not in str(cm.get("classification") or "")
    assert "CM_DISPATCH_PASS" in str(cm.get("classification") or "")
    cb = classify_callback_boundary(filtered_rows=rows, exact_token=token)
    assert str(cb.get("classification") or "").startswith("CB6")


def test_value1_explicit_pop_on_widget_key() -> None:
    rows = [
        _prod_entered(),
        _prod_exited(),
        {
            "event": "production_stage1_session_state_mutation",
            "key": "solo_countdown_wake_solo_persistent",
            "mutation_op": "pop",
            "previous_value_repr": f"'{EXACT}'",
        },
    ]
    out = classify_value_loss_boundary(exact_token=EXACT, filtered_rows=rows)
    assert out["classification"] == VALUE1


def test_value4_legacy_cb6_is_pending_not_authoritative() -> None:
    rows = [_prod_entered(), _prod_exited()]
    cb = classify_callback_boundary(filtered_rows=rows, exact_token=EXACT)
    raw = build_expiration_token_raw_report(expected_token=EXACT, filtered_rows=rows)
    out = classify_value_loss_boundary(
        exact_token=EXACT,
        filtered_rows=rows,
        callback_boundary=cb,
        token_raw=raw,
    )
    assert cb["classification"].startswith("CB6")
    assert out["classification"].startswith("VALUE_CLASSIFICATION_PENDING")
    assert VALUE4 in str(out.get("provisional_inference") or "")


def test_value4_with_lifecycle_handoffs_and_no_app_mutation() -> None:
    rows = [
        _prod_entered(),
        _prod_exited(),
        {
            "event": "production_stage1_prod_on_change_value_snapshot",
            "phase": "callback_entry",
            "raw_value_repr": f"'{EXACT}'",
        },
        {
            "event": "production_stage1_post_callback_handoff_boundary",
            "boundary": "post_callback_session_state",
            "value_raw": "None",
        },
    ]
    cb = classify_callback_boundary(filtered_rows=rows, exact_token=EXACT)
    out = classify_value_loss_boundary(
        exact_token=EXACT,
        filtered_rows=rows,
        callback_boundary=cb,
    )
    assert out["classification"] == VALUE4


def test_expiration_token_raw_equality_fields() -> None:
    rows = [_prod_entered(), _prod_exited()]
    raw = build_expiration_token_raw_report(
        expected_token=EXACT,
        filtered_rows=rows,
        expiration={"token_sent": EXACT},
    )
    assert raw["expected_token_raw"] == EXACT
    assert raw["callback_entry_equals_expected"] is True
    assert raw["callback_exit_equals_expected"] is False
