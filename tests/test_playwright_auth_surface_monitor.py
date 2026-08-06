"""Tests for multi-surface headed login observation (harness)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from playwright_auth_capture_diag import (  # noqa: E402
    AUTH_LOGIN1,
    AUTH_LOGIN4,
    auth_prestart_hydration_seen,
    classify_auth_login,
    infer_timeout_failure_phase,
    login_transition_state,
)
from playwright_auth_surface_monitor import BrowserSurfaceMonitor  # noqa: E402


def _state(**kwargs: object) -> dict:
    defaults = dict(
        target_sid="aaaa-1111-2222-3333-444444444444",
        url_sid="aaaa-1111-2222-3333-444444444444",
        provider_seen=False,
        oauth_callback_seen=False,
        returned_to_app=False,
        storage={},
        signed_in_display=False,
        ledger_rows=[],
        strict_failure="streamlit_auth_incomplete",
        sign_in_initiated=False,
    )
    defaults.update(kwargs)
    return login_transition_state(**defaults)  # type: ignore[arg-type]


class SurfaceLoginObservationTests(unittest.TestCase):
    def test_misleading_signed_in_without_provider_is_login1(self) -> None:
        st = _state(signed_in_display=True, provider_seen=False)
        self.assertTrue(st["misleading_signed_in_only"])
        self.assertEqual(classify_auth_login(st), AUTH_LOGIN1)
        phase = infer_timeout_failure_phase(st, strict_failure="streamlit_auth_incomplete")
        self.assertEqual(phase, "timeout_signed_in_ui_without_provider_or_ledger")

    def test_popup_provider_same_tab_redirect_observed(self) -> None:
        st = _state(provider_seen=True, oauth_callback_seen=True, sign_in_initiated=True)
        self.assertTrue(st["steps"]["2_provider_surface_observed"])
        self.assertFalse(st["misleading_signed_in_only"])

    def test_same_tab_redirect_callback_step(self) -> None:
        st = _state(
            provider_seen=True,
            oauth_callback_seen=True,
            returned_to_app=True,
            storage={"supabase_storage_key_present": True},
            signed_in_display=True,
        )
        self.assertTrue(st["steps_legacy"]["2_oauth_callback_url_reached"])

    def test_ledger_hydration_step_requires_checkpoint(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "load_browser_auth_tokens",
            }
        ]
        self.assertTrue(auth_prestart_hydration_seen(rows))
        st = _state(ledger_rows=rows, provider_seen=True, sign_in_initiated=True)
        self.assertTrue(st["steps"]["6_auth_hydration_ledger_started"])

    def test_bridge_never_invoked_phase(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "load_browser_auth_tokens",
            }
        ]
        st = _state(
            ledger_rows=rows,
            provider_seen=True,
            oauth_callback_seen=True,
            storage={"access_token_value_present": True},
            signed_in_display=True,
        )
        phase = infer_timeout_failure_phase(st, strict_failure="streamlit_auth_incomplete")
        self.assertEqual(phase, "timeout_bridge_save_never_invoked")

    def test_provider_path_still_login4_without_bridge(self) -> None:
        st = _state(
            provider_seen=True,
            oauth_callback_seen=True,
            returned_to_app=True,
            storage={"supabase_storage_key_present": True},
            signed_in_display=True,
            sign_in_initiated=True,
        )
        self.assertEqual(classify_auth_login(st), AUTH_LOGIN4)

    def test_monitor_selects_cloud_app_page_by_suite_sid(self) -> None:
        collector = mock.Mock()
        collector.attach = mock.Mock()
        collector.note_url = mock.Mock()
        ctx = mock.Mock()
        good = mock.Mock()
        good.is_closed = mock.Mock(return_value=False)
        good.url = (
            "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
            "?suite_sid=aaaa-1111-2222-3333-444444444444"
        )
        good.frames = []
        good.evaluate = mock.Mock(return_value=False)
        ctx.pages = [good]
        mon = BrowserSurfaceMonitor(context=ctx, target_sid="aaaa-1111-2222-3333-444444444444", collector=collector)
        mon.wire(good)
        mon.poll()
        self.assertEqual(mon.app_page(good), good)
        blob = mon.diagnostic_blob()
        self.assertTrue(blob["selected_app_page_id"] or mon.cloud_app_page() is good)

    def test_provider_active_suppresses_app_page_selection(self) -> None:
        collector = mock.Mock()
        collector.attach = mock.Mock()
        collector.note_url = mock.Mock()
        ctx = mock.Mock()
        cloud = mock.Mock()
        cloud.is_closed = mock.Mock(return_value=False)
        cloud.url = (
            "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
            "?suite_sid=aaaa-1111-2222-3333-444444444444"
        )
        cloud.frames = []
        provider = mock.Mock()
        provider.is_closed = mock.Mock(return_value=False)
        provider.url = "https://accounts.google.com/o/oauth2/v2/auth"
        provider.frames = []
        ctx.pages = [cloud, provider]
        mon = BrowserSurfaceMonitor(context=ctx, target_sid="aaaa-1111-2222-3333-444444444444", collector=collector)
        mon.wire(cloud)
        self.assertTrue(mon.provider_login_in_progress())
        self.assertEqual(mon.cloud_app_page(), cloud)
        self.assertEqual(mon.app_page(cloud), cloud)


if __name__ == "__main__":
    unittest.main()
