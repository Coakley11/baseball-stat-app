"""Unit tests for Gate B production start proof harness."""

from __future__ import annotations

from scripts.p8_production_start_harness import (
    START1,
    START2,
    START3,
    START4,
    START8,
    START9,
    all_start_proof_true,
    classify_production_start_boundary,
    first_missing_start_proof,
    start_proof_from_state,
)


def _grade(**checks: bool) -> dict:
    base = {
        "nonempty_room_id": False,
        "room_in_progress": False,
        "pick_index_zero": False,
        "deadline_exists": False,
        "production_token": False,
        "fresh_room_id": True,
    }
    base.update(checks)
    passed = all(
        base[k]
        for k in (
            "nonempty_room_id",
            "room_in_progress",
            "pick_index_zero",
            "deadline_exists",
            "production_token",
            "fresh_room_id",
        )
    )
    return {"pass": passed, "checks": base}


def test_setup_visible_but_not_started_is_not_proof() -> None:
    state = {"setup_start_visible": True, "in_progress": False, "room_id": "", "url": "https://x/?active_page=Live+Draft+Room"}
    grade = _grade()
    proof = start_proof_from_state(state, grade)
    assert not all_start_proof_true(proof)
    assert first_missing_start_proof(proof) == "nonempty_room_id"


def test_setup_disappeared_without_in_progress_fails_proof() -> None:
    state = {"setup_start_visible": False, "in_progress": False, "room_id": "", "url": "https://x/?active_page=Live+Draft+Room"}
    grade = _grade()
    proof = start_proof_from_state(state, grade)
    assert not proof["room_in_progress"]


def test_room_created_but_pending_is_start8() -> None:
    state = {
        "room_id": "ABC123",
        "in_progress": False,
        "setup_start_visible": True,
        "url": "https://x/?active_page=Live+Draft+Room",
        "mount": {},
    }
    grade = _grade(nonempty_room_id=True, room_in_progress=False)
    proof = start_proof_from_state(state, grade)
    b = classify_production_start_boundary(
        ldr_surface={"setup_visible": True},
        click_result={"start_matches": [{"visible": True, "disabled": False}], "playwright_clicked": True},
        state=state,
        grade=grade,
        proof=proof,
        draft_legacy={},
    )
    assert b == START8


def test_in_progress_without_countdown_is_start9() -> None:
    state = {
        "room_id": "ABC123",
        "in_progress": True,
        "setup_start_visible": False,
        "pick_index": 0,
        "deadline": "123",
        "production_token": "R|0|123",
        "url": "https://x/?active_page=Live+Draft+Room",
        "mount": {},
        "ui": {},
    }
    grade = _grade(
        nonempty_room_id=True,
        room_in_progress=True,
        pick_index_zero=True,
        deadline_exists=True,
        production_token=True,
    )
    proof = start_proof_from_state(state, grade)
    assert proof["countdown_mounted"] is False
    b = classify_production_start_boundary(
        ldr_surface={"setup_visible": False, "live_draft_main_marker": True},
        click_result={"playwright_clicked": True, "start_matches": [{}]},
        state=state,
        grade=grade,
        proof=proof,
        draft_legacy={},
    )
    assert b == START9


def test_start_control_not_found() -> None:
    state = {"url": "https://x/?active_page=Live+Draft+Room", "in_progress": False, "setup_start_visible": True}
    b = classify_production_start_boundary(
        ldr_surface={"setup_visible": True},
        click_result={"start_matches": [], "playwright_clicked": False},
        state=state,
        grade=_grade(),
        proof=start_proof_from_state(state, _grade()),
        draft_legacy={},
    )
    assert b == START2


def test_start_disabled() -> None:
    state = {"url": "https://x/?active_page=Live+Draft+Room", "in_progress": False, "setup_start_visible": True}
    b = classify_production_start_boundary(
        ldr_surface={"setup_visible": True},
        click_result={"start_matches": [{"visible": True, "disabled": True}], "playwright_clicked": False},
        state=state,
        grade=_grade(),
        proof=start_proof_from_state(state, _grade()),
        draft_legacy={},
    )
    assert b == START3


def test_click_not_registered() -> None:
    state = {"url": "https://x/?active_page=Live+Draft+Room", "in_progress": False, "setup_start_visible": True}
    b = classify_production_start_boundary(
        ldr_surface={"setup_visible": True},
        click_result={"start_matches": [{"visible": True, "disabled": False}], "playwright_clicked": False},
        state=state,
        grade=_grade(),
        proof=start_proof_from_state(state, _grade()),
        draft_legacy={"start_success": False},
    )
    assert b == START4


def test_delayed_proof_all_true() -> None:
    state = {
        "room_id": "ABC123",
        "in_progress": True,
        "pick_index": 0,
        "deadline": "999",
        "production_token": "R|0|999",
        "mount": {"mounted": "1", "key": "solo_countdown_wake_solo_persistent", "token": "R|0|999"},
        "ui": {},
    }
    grade = _grade(
        nonempty_room_id=True,
        room_in_progress=True,
        pick_index_zero=True,
        deadline_exists=True,
        production_token=True,
    )
    proof = start_proof_from_state(state, grade)
    assert all_start_proof_true(proof)


def test_wrong_surface_start1() -> None:
    state = {"url": "https://x/", "in_progress": False, "setup_start_visible": False}
    b = classify_production_start_boundary(
        ldr_surface={"setup_visible": False, "live_draft_main_marker": False},
        click_result={},
        state=state,
        grade=_grade(),
        proof=start_proof_from_state(state, _grade()),
        draft_legacy={},
    )
    assert b == START1


def test_duplicate_start_click_blocked() -> None:
    import pytest

    from scripts.p8_production_start_harness import dispatch_start_single_authoritative_click

    checkpoints: list[dict] = [{"_start_click_count": 1}]
    with pytest.raises(RuntimeError, match="duplicate_start_click_blocked"):
        dispatch_start_single_authoritative_click(None, checkpoints)
