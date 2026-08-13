"""Timeout-path forensics retention for wait_bridge_auth_hydrated (harness-only)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from playwright_auth_bridge_restore_harness import (  # noqa: E402
    attach_hydration_timeout_forensics,
    build_auth_restore_boundary_at_timeout,
    sanitize_hydration_checkpoint_snapshot,
    wait_bridge_auth_hydrated,
)
from stage1_application_phase import AUTH_HYDRATE7_SETUP_START_TIMEOUT  # noqa: E402

ST_SID = "f17e7e32-5a38-4fd6-ba2a-a7847681554d"
RUN_ID = "426bd2a9291349bd"
SUITE = "2b45b1a3-cbca-407a-84ec-5fa7bc5f7497"


def _hydration_row(checkpoint: str, **extra: object) -> dict:
    base: dict = {
        "event": "production_stage1_auth_prestart_hydration",
        "checkpoint": checkpoint,
        "streamlit_session_id": ST_SID,
        "diagnostic_run_id": RUN_ID,
        "script_run_seq": 3,
        "event_index": 10,
        "event_id": f"{RUN_ID}:10:production_stage1_auth_prestart_hydration",
        "timestamp": 1786559100.0,
    }
    base.update(extra)
    return base


def _lookup_ok(**extra: object) -> dict:
    return _hydration_row(
        "load_browser_auth_tokens_lookup",
        rejection_reason="ok",
        access_token_present=True,
        refresh_token_present=True,
        production_row_found=True,
        suite_sid_prefix=SUITE[:8],
        environment_fingerprint="7a9c29308c1d979c",
        **extra,
    )


class SanitizeSnapshotTests(unittest.TestCase):
    def test_strips_token_values_keeps_presence_booleans(self) -> None:
        snap = sanitize_hydration_checkpoint_snapshot(
            {
                "event_id": "abc:1:x",
                "access_token_present": True,
                "refresh_token_present": True,
                "access_token": "SECRET_ACCESS_VALUE_SHOULD_NOT_LEAK",
                "refresh_token": "SECRET_REFRESH_VALUE_SHOULD_NOT_LEAK",
                "Authorization": "Bearer SECRET",
                "cookie": "session=SECRET",
                "rejection_reason": "ok",
            }
        )
        assert snap is not None
        self.assertTrue(snap["access_token_present"])
        self.assertTrue(snap["refresh_token_present"])
        self.assertEqual(snap["rejection_reason"], "ok")
        blob = json.dumps(snap)
        self.assertNotIn("SECRET", blob)
        self.assertNotIn("Bearer", blob)
        self.assertNotIn("access_token\":", blob.replace("access_token_present", ""))


class BoundaryHelperTests(unittest.TestCase):
    def test_missing_checkpoints_are_explicitly_false(self) -> None:
        boundary = build_auth_restore_boundary_at_timeout(
            load_ok=True,
            lookup_row={"access_token_present": True, "refresh_token_present": True},
            restore_entry=None,
            restore_exit=None,
            restore_exception=None,
            apply_exit=None,
            after_apply=None,
            bound={"is_authenticated": False, "auth_session_complete": False},
            start_enabled=False,
        )
        self.assertTrue(boundary["bridge_load_ok"])
        self.assertTrue(boundary["lookup_found"])
        self.assertFalse(boundary["restore_entry_seen"])
        self.assertFalse(boundary["restore_exit_seen"])
        self.assertFalse(boundary["restore_exception_seen"])
        self.assertFalse(boundary["apply_exit_seen"])
        self.assertFalse(boundary["restore_after_apply_seen"])
        self.assertFalse(boundary["authenticated_at_timeout"])
        self.assertFalse(boundary["auth_session_complete_at_timeout"])
        self.assertFalse(boundary["start_enabled_at_timeout"])


class TimeoutForensicsAttachTests(unittest.TestCase):
    def test_attach_preserves_restore_failure_rows(self) -> None:
        ledger = [
            _lookup_ok(),
            _hydration_row("load_browser_auth_tokens", browser_tokens_loaded=True, access_token_present=True, refresh_token_present=True),
            _hydration_row("restore_auth_session_entry", authenticated_before=False, hydration_attempted=True),
            _hydration_row(
                "restore_auth_session_exit",
                skip_or_failure_reason="user_missing",
                authenticated_after=False,
                restore_attempt_seq=1,
            ),
        ]
        out: dict = {}
        attach_hydration_timeout_forensics(
            out,
            ledger=ledger,
            streamlit_session_id=ST_SID,
            diagnostic_run_id=RUN_ID,
            bound={
                "session_flag_present": False,
                "is_authenticated": False,
                "auth_session_complete": False,
                "current_restore_blocked_reason": "auth_required",
                "apply_authenticated_user_ok": None,
                "field_sources": {"is_authenticated": "dom"},
            },
            load_ok=True,
            start_enabled=False,
            url_sid=SUITE,
            suite_sid=SUITE,
        )
        cps = (out["hydration_timeout_forensics"] or {})["checkpoints"]
        self.assertEqual(cps["restore_auth_session_exit"]["skip_or_failure_reason"], "user_missing")
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["restore_entry_seen"])
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["restore_exit_seen"])
        self.assertFalse(out["auth_restore_boundary_at_timeout"]["apply_exit_seen"])
        seq_names = [r["checkpoint"] for r in out["hydration_sequence"]]
        self.assertIn("load_browser_auth_tokens_lookup", seq_names)
        self.assertIn("restore_auth_session_exit", seq_names)
        self.assertIn("rerun_anomaly", out)

    def test_attach_preserves_apply_incomplete(self) -> None:
        ledger = [
            _lookup_ok(),
            _hydration_row("restore_auth_session_entry", authenticated_before=False),
            _hydration_row("restore_auth_session_exit", skip_or_failure_reason="ok", authenticated_after=True),
            _hydration_row(
                "apply_authenticated_user_exit",
                authenticated_before=True,
                authenticated_after=False,
                apply_authenticated_user_ok=False,
                skip_or_failure_reason="apply_incomplete",
            ),
        ]
        out: dict = {}
        attach_hydration_timeout_forensics(
            out,
            ledger=ledger,
            streamlit_session_id=ST_SID,
            diagnostic_run_id=RUN_ID,
            bound={
                "session_flag_present": True,
                "is_authenticated": False,
                "auth_session_complete": False,
                "current_restore_blocked_reason": "auth_required",
                "apply_authenticated_user_ok": False,
                "field_sources": {},
            },
            load_ok=True,
            start_enabled=False,
            suite_sid=SUITE,
        )
        apply_snap = out["hydration_timeout_forensics"]["checkpoints"]["apply_authenticated_user_exit"]
        self.assertFalse(apply_snap["apply_authenticated_user_ok"])
        self.assertEqual(apply_snap["skip_or_failure_reason"], "apply_incomplete")
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["restore_exit_seen"])
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["apply_exit_seen"])
        self.assertFalse(out["bound_current_auth_at_timeout"]["is_authenticated"])


def _mock_page(url: str = f"https://example.app/?suite_sid={SUITE}") -> MagicMock:
    page = MagicMock()
    page.url = url
    page.wait_for_timeout = MagicMock()
    return page


class WaitBridgeTimeoutIntegrationTests(unittest.TestCase):
    def _run_timeout(self, ledger: list[dict], *, bound: dict, start_enabled: bool = False) -> dict:
        page = _mock_page()
        st_sid = ST_SID
        run_id = RUN_ID
        obs = {
            "ledger_rows_for_eval": ledger,
            "checkpoint": {
                "streamlit_session_id": st_sid,
                "diagnostic_run_id": run_id,
                "start_enabled": start_enabled,
                "start_visible": True,
                "start_frame_index": 0,
                "probe_checkpoint": "early_script",
            },
            "start_surface": {"enabled": start_enabled, "visible": True, "frame_index": 0},
        }
        dom = {
            "streamlit_session_id": st_sid,
            "diagnostic_run_id": run_id,
            "session_flag_present": bound.get("session_flag_present"),
            "is_authenticated": bound.get("is_authenticated"),
            "auth_session_complete": bound.get("auth_session_complete"),
            "current_restore_blocked_reason": bound.get("current_restore_blocked_reason"),
            "apply_authenticated_user_ok": bound.get("apply_authenticated_user_ok"),
        }

        with (
            patch("playwright_auth_observability.gather_page_observability", return_value=obs),
            patch("playwright_auth_observability.probe_dom_current_auth_state", return_value=dom),
            patch("queueui_audit_protocol.scrape_deploy_marker_from_page", return_value=("91ab4a5", {})),
            patch("playwright_auth_preflight_strict.inspect_start_control", return_value=obs["start_surface"]),
            patch("playwright_auth_preflight_strict.suite_sid_from_url", return_value=SUITE),
            patch(
                "playwright_auth_current_state_eval.evaluate_bound_current_auth_state",
                return_value=bound,
            ),
            patch(
                "stage1_application_phase.classify_ldr_phase_from_page",
                return_value={"application_phase": "SETUP_LOBBY"},
            ),
        ):
            return wait_bridge_auth_hydrated(
                page,
                SUITE,
                scrape_ledger=lambda _p: ledger,
                timeout_s=0.01,
                poll_interval_s=0.01,
                preamble_mode="stage1",
            )

    def test_timeout_after_successful_load_and_restore_failure(self) -> None:
        ledger = [
            _lookup_ok(),
            _hydration_row("restore_auth_session_entry", authenticated_before=False),
            _hydration_row(
                "restore_auth_session_exit",
                skip_or_failure_reason="tokens_missing",
                authenticated_after=False,
                restore_attempt_seq=2,
                # soft failure — must NOT fail-fast AUTH_HYDRATE3/8
            ),
        ]
        bound = {
            "session_flag_present": False,
            "is_authenticated": False,
            "auth_session_complete": False,
            "current_restore_blocked_reason": "auth_required",
            "apply_authenticated_user_ok": None,
            "field_sources": {},
        }
        out = self._run_timeout(ledger, bound=bound)
        self.assertEqual(out["failure"], "bridge_hydration_timeout")
        self.assertEqual(out["failure_classification"], AUTH_HYDRATE7_SETUP_START_TIMEOUT)
        self.assertTrue(out["hydration_polls"][0]["load_ok"])
        exit_snap = out["hydration_timeout_forensics"]["checkpoints"]["restore_auth_session_exit"]
        self.assertEqual(exit_snap["skip_or_failure_reason"], "tokens_missing")
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["bridge_load_ok"])
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["restore_exit_seen"])
        self.assertFalse(out["auth_restore_boundary_at_timeout"]["apply_exit_seen"])

    def test_timeout_after_restore_ok_apply_incomplete(self) -> None:
        ledger = [
            _lookup_ok(),
            _hydration_row("restore_auth_session_entry", authenticated_before=False),
            _hydration_row("restore_auth_session_exit", skip_or_failure_reason="ok", authenticated_after=True),
            _hydration_row(
                "apply_authenticated_user_exit",
                authenticated_after=False,
                apply_authenticated_user_ok=False,
            ),
        ]
        bound = {
            "session_flag_present": True,
            "is_authenticated": False,
            "auth_session_complete": False,
            "current_restore_blocked_reason": "auth_required",
            "apply_authenticated_user_ok": False,
            "field_sources": {},
        }
        out = self._run_timeout(ledger, bound=bound)
        self.assertIn("AUTH_HYDRATE7", out["failure_classification"])
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["restore_exit_seen"])
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["apply_exit_seen"])
        self.assertFalse(out["bound_current_auth_at_timeout"]["auth_session_complete"])

    def test_timeout_auth_complete_start_disabled_retains_divergence(self) -> None:
        ledger = [
            _lookup_ok(),
            _hydration_row("restore_auth_session_entry", authenticated_before=False),
            _hydration_row("restore_auth_session_exit", skip_or_failure_reason="ok", authenticated_after=True),
            _hydration_row(
                "apply_authenticated_user_exit",
                authenticated_after=True,
                apply_authenticated_user_ok=True,
            ),
            _hydration_row("restore_auth_session_after_apply", apply_return_ok=True, authenticated_after=True),
        ]
        bound = {
            "session_flag_present": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "current_restore_blocked_reason": "",
            "apply_authenticated_user_ok": True,
            "field_sources": {"is_authenticated": "dom"},
        }
        out = self._run_timeout(ledger, bound=bound, start_enabled=False)
        # Existing classifier may re-label away from AUTH_HYDRATE7 when auth is complete.
        self.assertTrue(out["auth_complete_at_timeout"] or out.get("first_divergence_from_isolated"))
        self.assertTrue(out["bound_current_auth_at_timeout"]["is_authenticated"])
        self.assertTrue(out["bound_current_auth_at_timeout"]["auth_session_complete"])
        self.assertFalse(out["auth_restore_boundary_at_timeout"]["start_enabled_at_timeout"])
        self.assertTrue(out["auth_restore_boundary_at_timeout"]["restore_after_apply_seen"])

    def test_timeout_missing_restore_exit_stays_explicitly_absent(self) -> None:
        ledger = [_lookup_ok()]
        bound = {
            "session_flag_present": False,
            "is_authenticated": False,
            "auth_session_complete": False,
            "current_restore_blocked_reason": "auth_required",
            "apply_authenticated_user_ok": None,
            "field_sources": {},
        }
        out = self._run_timeout(ledger, bound=bound)
        self.assertIn("AUTH_HYDRATE7", out["failure_classification"])
        cps = out["hydration_timeout_forensics"]["checkpoints"]
        self.assertIsNotNone(cps["load_browser_auth_tokens_lookup"])
        self.assertIsNone(cps["restore_auth_session_entry"])
        self.assertIsNone(cps["restore_auth_session_exit"])
        self.assertIsNone(cps["apply_authenticated_user_exit"])
        boundary = out["auth_restore_boundary_at_timeout"]
        self.assertTrue(boundary["lookup_found"])
        self.assertFalse(boundary["restore_entry_seen"])
        self.assertFalse(boundary["restore_exit_seen"])
        self.assertFalse(boundary["apply_exit_seen"])

    def test_timeout_serialized_evidence_has_no_secrets(self) -> None:
        ledger = [
            _lookup_ok(
                access_token="LEAK_ACCESS_TOKEN_VALUE",
                refresh_token="LEAK_REFRESH_TOKEN_VALUE",
            ),
            _hydration_row(
                "restore_auth_session_exit",
                skip_or_failure_reason="ok",
                access_token="LEAK_ACCESS_TOKEN_VALUE",
                cookie="session=LEAK_COOKIE",
                Authorization="Bearer LEAK_HDR",
            ),
        ]
        bound = {
            "session_flag_present": False,
            "is_authenticated": False,
            "auth_session_complete": False,
            "current_restore_blocked_reason": "auth_required",
            "apply_authenticated_user_ok": None,
            "field_sources": {},
        }
        out = self._run_timeout(ledger, bound=bound)
        blob = json.dumps(out, default=str)
        for banned in (
            "LEAK_ACCESS_TOKEN_VALUE",
            "LEAK_REFRESH_TOKEN_VALUE",
            "LEAK_COOKIE",
            "Bearer LEAK_HDR",
            "LEAK_HDR",
        ):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
