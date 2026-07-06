"""Tests for suite_app_current_state health probes."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_app_current_state_health import (
    classify_cloud_save_failure,
    estimate_json_bytes,
    probe_suite_app_current_state_health,
    _classify_supabase_error,
)
from suite_storage_supabase import is_transient_supabase_error


class TestSuiteAppCurrentStateHealth(unittest.TestCase):
    def test_upstream_reset_is_transient(self) -> None:
        err = RuntimeError(
            "Supabase POST suite_app_current_state failed (503): "
            "upstream connect error or disconnect/reset before headers"
        )
        self.assertTrue(is_transient_supabase_error(err))

    def test_classify_gateway_reset(self) -> None:
        self.assertEqual(
            _classify_supabase_error("upstream connect error or disconnect/reset before headers"),
            "gateway_upstream_reset",
        )

    def test_classify_save_failure_project_unhealthy(self) -> None:
        kind = classify_cloud_save_failure(
            error="upstream connect error",
            payload_bytes=900_000,
            minimal_write_ok=False,
        )
        self.assertEqual(kind, "supabase_project_unhealthy")

    def test_classify_save_failure_payload_when_minimal_ok(self) -> None:
        kind = classify_cloud_save_failure(
            error="upstream connect error or disconnect/reset before headers",
            payload_bytes=900_000,
            minimal_write_ok=True,
        )
        self.assertEqual(kind, "payload_too_large_or_slow")

    def test_estimate_json_bytes(self) -> None:
        self.assertGreater(estimate_json_bytes({"a": 1}), 0)

    @patch("suite_storage_supabase.ping", return_value=False)
    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_storage_config.get_cloud_config")
    def test_probe_reports_ping_failure(self, mock_cfg, _enabled, _ping) -> None:
        mock_cfg.return_value = type("Cfg", (), {"url": "https://x.supabase.co"})()
        out = probe_suite_app_current_state_health(run_write_probe=False)
        self.assertTrue(out["configured"])
        self.assertFalse(out["ping_ok"])


if __name__ == "__main__":
    unittest.main()
