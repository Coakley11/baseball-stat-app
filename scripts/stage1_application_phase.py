"""Live Draft Room application phase vs auth phase (harness-only)."""

from __future__ import annotations

from typing import Any

SETUP_LOBBY = "SETUP_LOBBY"
ACTIVE_DRAFT = "ACTIVE_DRAFT"
UNKNOWN_PHASE = "UNKNOWN_PHASE"

QUEUE_HARNESS_SEQUENCE1 = (
    "QUEUE_HARNESS_SEQUENCE1 — prior Start-only proof consumed the setup state required by the following queue run."
)
APP_PHASE_ACTIVE_DRAFT = "APP_PHASE_ACTIVE_DRAFT — authenticated active draft; Start disabled is expected"
AUTH_HYDRATE7_SETUP_START_TIMEOUT = (
    "AUTH_HYDRATE7 — bridge hydration timeout waiting for setup Start while auth incomplete"
)

EXPECTED_PHASE_SETUP_LOBBY = "setup_lobby"
EXPECTED_PHASE_AUTH_ONLY = "auth_only"


def classify_ldr_phase_from_state(state: dict[str, Any], *, start_inspect: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify SETUP_LOBBY vs ACTIVE_DRAFT from authoritative scrape + optional Start inspect."""
    start = start_inspect or {}
    room = str(state.get("room_id") or "").strip().upper()
    in_progress = bool(state.get("in_progress"))
    start_visible = bool(start.get("visible") if "visible" in start else state.get("setup_start_visible"))
    start_enabled = bool(start.get("enabled") if "enabled" in start else False)
    if not start_enabled and state.get("setup_start_visible"):
        start_enabled = True
    pause_count = int(state.get("pause_draft_count") or 0)
    if in_progress and room:
        phase = ACTIVE_DRAFT
    elif start_visible and start_enabled and not in_progress and not room:
        phase = SETUP_LOBBY
    elif room and (in_progress or pause_count >= 1):
        phase = ACTIVE_DRAFT
    elif start_visible and not start_enabled and room:
        phase = ACTIVE_DRAFT
    else:
        phase = UNKNOWN_PHASE
    return {
        "application_phase": phase,
        "room_id": room,
        "in_progress": in_progress,
        "start_visible": start_visible,
        "start_enabled": start_enabled,
        "pause_draft_count": pause_count,
    }


def classify_ldr_phase_from_page(page) -> dict[str, Any]:
    from production_draft_start_authoritative import scrape_authoritative_start_state
    from playwright_auth_preflight_strict import inspect_start_control

    state = scrape_authoritative_start_state(page) or {}
    start = inspect_start_control(page) or {}
    return classify_ldr_phase_from_state(state, start_inspect=start)


def auth_poll_complete(poll: dict[str, Any]) -> bool:
    return bool(
        poll.get("is_authenticated")
        and poll.get("auth_session_complete")
        and not str(poll.get("restore_block") or "").strip()
    )


def classify_hydration_timeout(
    *,
    expected_application_phase: str,
    hydration_polls: list[dict[str, Any]],
    application_phase: str,
    standalone_start_consumed: bool = False,
) -> dict[str, Any]:
    """Separate auth failure from application-phase mismatch after timeout."""
    last = hydration_polls[-1] if hydration_polls else {}
    auth_complete = auth_poll_complete(last)
    if expected_application_phase == EXPECTED_PHASE_AUTH_ONLY:
        return {
            "failure_classification": "AUTH_HYDRATE7",
            "root_cause": "auth_only_hydration_timeout",
            "auth_complete_at_timeout": auth_complete,
        }
    if auth_complete and application_phase == ACTIVE_DRAFT and expected_application_phase == EXPECTED_PHASE_SETUP_LOBBY:
        code = QUEUE_HARNESS_SEQUENCE1 if standalone_start_consumed else APP_PHASE_ACTIVE_DRAFT
        return {
            "failure_classification": code,
            "root_cause": "setup_lobby_expected_but_active_draft",
            "auth_complete_at_timeout": True,
            "mislabeled_as_auth_hydrate7": True,
        }
    if auth_complete and not last.get("start_enabled"):
        return {
            "failure_classification": APP_PHASE_ACTIVE_DRAFT,
            "root_cause": "auth_complete_start_not_enabled",
            "auth_complete_at_timeout": True,
            "mislabeled_as_auth_hydrate7": True,
        }
    return {
        "failure_classification": AUTH_HYDRATE7_SETUP_START_TIMEOUT,
        "root_cause": "bridge_hydration_timeout",
        "auth_complete_at_timeout": auth_complete,
    }


def harness_end_live_draft_room(page, *, room_id: str = "") -> dict[str, Any]:
    """Harness-only: end/delete live draft so setup lobby can return (focused Start tests)."""
    from run_production_solo_soak import click_btn

    out: dict[str, Any] = {"room_id": room_id, "end_delete_clicked": False, "setup_restored": False}
    try:
        click_btn(page, "End/Delete Draft", wait_ms=6000)
        out["end_delete_clicked"] = True
        page.wait_for_timeout(3000)
        click_btn(page, "Confirm End/Delete", wait_ms=6000)
        page.wait_for_timeout(5000)
        phase = classify_ldr_phase_from_page(page)
        out["post_cleanup_phase"] = phase.get("application_phase")
        out["setup_restored"] = phase.get("application_phase") == SETUP_LOBBY
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out
