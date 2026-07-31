"""Tests for production _prod_on_change durable observability (no claim/mutate)."""

from __future__ import annotations

from unittest import mock

from live_draft_prod_on_change_observability import (
    CALLBACK_REGISTRATION,
    PROD_ON_CHANGE_ENTERED,
    PROD_ON_CHANGE_EXITED,
    emit_callback_registration,
    emit_prod_on_change_entered,
    emit_prod_on_change_exited,
    safe_session_state_inventory,
)


def test_safe_session_state_inventory_filters_related_keys() -> None:
    class _SS(dict):
        def keys(self):  # type: ignore[override]
            return super().keys()

    st = mock.MagicMock()
    st.session_state = _SS(
        {
            "solo_countdown_wake_solo_persistent": "ROOM|0|1.0",
            "unrelated_user_pref": "secret",
            "solo_persistent_wake_token": "x",
        }
    )
    inv = safe_session_state_inventory(st, "solo_countdown_wake_solo_persistent")
    keys = {item["key"] for item in inv["related_keys"]}
    assert "solo_countdown_wake_solo_persistent" in keys
    assert "unrelated_user_pref" not in keys


def test_prod_on_change_enter_exit_durable_when_ledger_enabled() -> None:
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": None}
    session: dict = {"_solo_stage1_script_run_seq": 3}
    room = {"draft_room_id": "ABCD1234", "current_pick_index": 0, "status": "in_progress"}

    def _noop(*args, **kwargs):
        return {}

    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=True,
    ), mock.patch(
        "live_draft_stage1_production_ledger.note_stage1_event",
        side_effect=lambda sess, event, **kw: {"event": event, **(kw.get("extra") or {})},
    ) as note:
        inv, existed = emit_prod_on_change_entered(
            st,
            session,
            room=room,
            widget_key="solo_countdown_wake_solo_persistent",
            expected_token="ABCD1234|0|9.0",
            on_change_fn=lambda: None,
        )
        assert inv
        assert existed
        emit_prod_on_change_exited(
            st,
            session,
            room=room,
            widget_key="solo_countdown_wake_solo_persistent",
            callback_invocation_id=inv,
            key_existed_at_entry=existed,
            t0=0.0,
        )
        events = [c.args[1] for c in note.call_args_list]
        assert PROD_ON_CHANGE_ENTERED in events
        assert PROD_ON_CHANGE_EXITED in events


def test_callback_registration_links_declaration_id() -> None:
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {}
    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=True,
    ), mock.patch("live_draft_stage1_production_ledger.note_stage1_event") as note:
        emit_callback_registration(
            st,
            session,
            room={"draft_room_id": "R1"},
            widget_key="solo_countdown_wake_solo_persistent",
            declaration_invocation_id="decl-abc",
            on_change_fn=lambda: None,
            on_change_registered=True,
            direct_raw_return=None,
            session_state_before="missing",
            session_state_after="None",
            first_mount=True,
            mount_guard_result="mounted",
            cached_raw_return=None,
            delivery_only=False,
        )
        assert note.call_args.args[1] == CALLBACK_REGISTRATION
        assert session["_solo_stage1_last_declaration_invocation_id"] == "decl-abc"


def test_prod_on_change_wrapper_does_not_call_claim_from_observability_module() -> None:
    """Observability module has no claim/autopick imports."""
    import live_draft_prod_on_change_observability as mod

    src = open(mod.__file__, encoding="utf-8").read()
    assert "try_claim_token_delivery" not in src
    assert "process_production_expire_token" not in src
