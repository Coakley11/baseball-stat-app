"""Stage 1 expiration audit helpers."""

from __future__ import annotations

from live_draft_stage1_expire_audit import (
    map_legacy_reject_reason,
    try_claim_token_delivery,
)


def test_map_legacy_reject_reason() -> None:
    assert map_legacy_reject_reason("duplicate_token") == "already_consumed"
    assert map_legacy_reject_reason("pick_mismatch") == "wrong_pick"
    assert map_legacy_reject_reason("already_consumed") == "already_consumed"


def test_try_claim_token_delivery_single_owner() -> None:
    session: dict = {}
    ok, code = try_claim_token_delivery(session, "ROOM|0|123.0", "native_component_on_change")
    assert ok is True
    assert code == ""
    ok2, code2 = try_claim_token_delivery(session, "ROOM|0|123.0", "late_page_flush")
    assert ok2 is False
    assert code2 == "callback_source_not_allowed"
