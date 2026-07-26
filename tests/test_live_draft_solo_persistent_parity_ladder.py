"""Unit tests for production-parity ladder (query-param gated diagnostics)."""

from __future__ import annotations

from unittest import mock

from live_draft_solo_persistent_parity_ladder import (
    PARITY_STOP_KEY,
    SYNTHETIC_SECONDS,
    build_parity_token,
    parity_control,
    parity_ladder_active,
    parity_should_stop_page,
)


def test_parity_control_from_query() -> None:
    session: dict = {}
    st = mock.MagicMock()
    with mock.patch(
        "live_draft_solo_persistent_parity_ladder._qp_get",
        return_value="p3",
    ):
        assert parity_control(st, session) == "P3"
        assert session["_solo_parity_ladder_control"] == "P3"
        assert parity_ladder_active(st, session) is True


def test_parity_stop_page_by_control() -> None:
    for stopped in (True, False):
        session = {PARITY_STOP_KEY: stopped}
        assert parity_should_stop_page(session) is stopped


def test_build_parity_token_format() -> None:
    token, deadline = build_parity_token("P0")
    assert token.startswith("WIRING_P0|0|")
    assert abs(deadline - float(token.split("|")[-1])) < 0.01
    assert deadline > 0
    assert SYNTHETIC_SECONDS == 10


def test_p6_token_is_production_format() -> None:
    from live_draft_solo_persistent_parity_ladder import (
        PARITY_CONTROL_KEY,
        ensure_p6_latched_production_token,
    )

    session: dict = {PARITY_CONTROL_KEY: "P6"}
    token, room = ensure_p6_latched_production_token(session)
    assert token.startswith("PARITY|")
    assert "WIRING_" not in token
    assert str(room.get("draft_room_id")) == "PARITY"
    token2, _ = ensure_p6_latched_production_token(session)
    assert token2 == token
