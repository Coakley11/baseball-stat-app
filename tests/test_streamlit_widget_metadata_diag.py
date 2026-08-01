"""Tests for Streamlit widget metadata / dispatch diagnostics (no token mutation)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from live_draft_streamlit_widget_metadata_diag import (
    CALLBACK_DISPATCH_EVALUATED,
    INTERNAL_METADATA_REGISTERED,
    evaluate_callback_dispatch,
    metadata_stores_callback,
    snapshot_widget_metadata,
)


def test_metadata_stores_callback_distinguishes_app_arg() -> None:
    empty = {"metadata_missing": True}
    assert metadata_stores_callback(empty) is False
    assert metadata_stores_callback({"metadata_callback_present": True}) is True
    assert metadata_stores_callback({"metadata_callbacks_present": True}) is True


def test_snapshot_widget_metadata_callback_fields() -> None:
    def _cb() -> None:
        pass

    meta = SimpleNamespace(
        callback=_cb,
        callbacks=None,
        callback_args=(),
        callback_kwargs={},
        value_type="json_value",
        deserializer=lambda x: x,
        serializer=lambda x: x,
        fragment_id="frag-1",
        id="$$ID-test-key",
    )
    ss = mock.MagicMock()
    ss._get_widget_metadata.return_value = meta
    snap = snapshot_widget_metadata(ss, "$$ID-test-key")
    assert snap["metadata_callback_present"] is True
    assert "live_draft_streamlit_widget_metadata_diag" in snap["metadata_callback_identity"] or "_cb" in snap[
        "metadata_callback_identity"
    ]
    assert snap["value_type"] == "json_value"


def test_evaluate_dispatch_skip_missing_callback() -> None:
    meta = SimpleNamespace(
        callback=None,
        callbacks=None,
        callback_args=(),
        callback_kwargs={},
        value_type="json_value",
    )
    ss = mock.MagicMock()
    ss._get_widget_metadata.return_value = meta
    ss._new_widget_state.get.return_value = {"value": "a"}
    ss._new_widget_state.states = {"wid": object()}
    ss._old_state.get.return_value = {"value": "b"}
    ss._widget_changed.return_value = True
    row = evaluate_callback_dispatch(ss, "wid")
    assert row["callback_selected"] is False
    assert row["skip_reason"] == "callback_missing_from_metadata"


def test_evaluate_dispatch_selects_single_callback_when_changed() -> None:
    def _cb() -> None:
        pass

    meta = SimpleNamespace(
        callback=_cb,
        callbacks=None,
        callback_args=(),
        callback_kwargs={},
        value_type="json_value",
    )
    ss = mock.MagicMock()
    ss._get_widget_metadata.return_value = meta
    ss._new_widget_state.get.return_value = "new"
    ss._old_state.get.return_value = "old"
    ss._widget_changed.return_value = True
    row = evaluate_callback_dispatch(ss, "wid")
    assert row["callback_selected"] is True
    assert row["skip_reason"] == "none"


def test_probe_after_declaration_emits_without_mutating_token() -> None:
    from live_draft_streamlit_widget_metadata_diag import probe_after_declaration

    session: dict = {"_solo_component_diag_enabled": True}
    st = mock.MagicMock()
    token = "ROOM|0|123.456"
    session["_solo_persistent_wake_last_token"] = token
    meta = SimpleNamespace(
        callback=lambda: None,
        callbacks=None,
        callback_args=(),
        callback_kwargs={},
        value_type="json_value",
        deserializer=lambda x: x,
        serializer=lambda x: x,
        fragment_id=None,
    )
    ss = mock.MagicMock()
    ss._get_widget_metadata.return_value = meta
    st.session_state = ss
    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=True,
    ), mock.patch(
        "live_draft_stage1_widget_identity.read_actual_registered_widget_id",
        return_value=("$$ID-wid", "test"),
    ), mock.patch(
        "live_draft_prod_on_change_observability._emit_row",
        return_value={"event": INTERNAL_METADATA_REGISTERED},
    ) as emit:
        probe_after_declaration(
            st,
            session,
            user_key="solo_countdown_wake_solo_persistent",
            component_name="solo_countdown_wake",
            application_on_change=lambda: None,
            surface="production",
        )
        assert session["_solo_persistent_wake_last_token"] == token
        assert emit.called
        extra = emit.call_args.kwargs.get("extra") or emit.call_args[1].get("extra")
        assert extra is None or emit.call_args[0][1] == INTERNAL_METADATA_REGISTERED


def test_evaluate_case_a_authority_passes_when_metadata_and_dispatch_complete() -> None:
    from scripts.p8_callback_metadata_classify import evaluate_case_a_metadata_authority

    token = "repro|3|1.0"
    peak = [
        {
            "event": "production_stage1_internal_widget_metadata_registered",
            "diagnostic_surface": "case_a",
            "widget_key": "minimal_wake_repro_3",
            "authoritative_widget_id": "wid-3",
            "application_on_change_argument_present": True,
            "metadata_missing": False,
            "metadata_callback_present": True,
            "metadata_callback_identity": "mod._on_change",
            "callback_registered_in_metadata": True,
        },
        {
            "event": "production_stage1_callback_dispatch_evaluated",
            "widget_key": "minimal_wake_repro_3",
            "new_state_present": True,
            "new_value_repr": token,
            "old_value_repr": "old",
            "widget_changed_result": True,
            "callback_selected": True,
        },
        {
            "event": "production_stage1_control_on_change_entered",
            "widget_key": "minimal_wake_repro_3",
            "expected_token": token,
            "callback_function_identity": "_on_change",
            "session_state_value_repr": repr(token),
        },
        {"event": "production_stage1_control_on_change_exited", "widget_key": "minimal_wake_repro_3"},
    ]
    out = evaluate_case_a_metadata_authority(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[peak[2]],
        control_exited=[peak[3]],
    )
    assert out["authoritative"] is True


def test_evaluate_case_a_authority_fails_when_metadata_missing() -> None:
    from scripts.p8_callback_metadata_classify import (
        INVALID_INTERNAL_METADATA_OBSERVABILITY,
        evaluate_case_a_metadata_authority,
    )

    peak = [
        {
            "event": "production_stage1_internal_widget_metadata_registered",
            "diagnostic_surface": "case_a",
            "widget_key": "minimal_wake_repro_0",
            "metadata_missing": True,
            "application_on_change_argument_present": True,
        },
        {
            "event": "production_stage1_control_on_change_entered",
            "widget_key": "minimal_wake_repro_0",
            "expected_token": "t",
            "callback_function_identity": "_on_change",
        },
    ]
    out = evaluate_case_a_metadata_authority(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[peak[1]],
        control_exited=[],
    )
    assert out["authoritative"] is False
    assert out["failure_boundary"] == INVALID_INTERNAL_METADATA_OBSERVABILITY

    from scripts.p8_callback_metadata_classify import classify_callback_metadata_boundary

    rows = [
        {
            "event": "production_stage1_internal_widget_metadata_registered",
            "diagnostic_surface": "production",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "application_on_change_argument_present": True,
            "callback_registered_in_metadata": False,
            "metadata_callback_present": False,
        }
    ]
    out = classify_callback_metadata_boundary(
        filtered_rows=rows,
        exact_token="R|0|1.0",
        production_widget_key="solo_countdown_wake_solo_persistent",
    )
    assert out["classification"].startswith("CM1")


def test_classify_cm4_unchanged_value() -> None:
    from scripts.p8_callback_metadata_classify import classify_callback_metadata_boundary

    rows = [
        {
            "event": "production_stage1_internal_widget_metadata_registered",
            "diagnostic_surface": "production",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "application_on_change_argument_present": True,
            "callback_registered_in_metadata": True,
            "authoritative_widget_id": "wid",
        },
        {
            "event": "production_stage1_backend_widget_state_after_backmsg",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "in_new_widget_state": True,
            "widget_changed": False,
            "deserialized_value_repr": "tok",
        },
        {
            "event": "production_stage1_callback_dispatch_evaluated",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "skip_reason": "widget_value_unchanged",
            "callback_selected": False,
            "new_value_repr": "tok",
            "old_value_repr": "tok",
        },
    ]
    out = classify_callback_metadata_boundary(
        filtered_rows=rows,
        exact_token="tok",
        production_widget_key="solo_countdown_wake_solo_persistent",
    )
    assert out["classification"].startswith("CM4")
