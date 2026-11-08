"""Manage Subscription / Checkout: the billing client wakes the Render service first, uses bounded
timeouts, and turns connection problems into plain messages instead of a raw HTTPSConnectionPool
exception (D4J review 2026-11-08). Same client as the separate billing candidate (c6c335e)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import requests

import baseball_billing_client as bc


def _cfg():
    return SimpleNamespace(billing_service_url="https://billing.test", rollout=None)


class BillingClientTests(unittest.TestCase):
    def _portal(self, get=None, post=None):
        with mock.patch.object(bc, "load_client_billing_config", return_value=_cfg()), \
                mock.patch.object(bc, "authenticated_subject", return_value=("u", True, "tok")), \
                mock.patch.object(bc.requests, "get", side_effect=get) as g, \
                mock.patch.object(bc.requests, "post", side_effect=post) as p:
            try:
                return bc.create_portal_url({}), g, p
            except RuntimeError as exc:
                return exc, g, p

    def test_a_cold_service_that_never_wakes_gives_a_plain_message_and_no_request(self) -> None:
        out, g, p = self._portal(get=requests.Timeout("Read timed out"))
        self.assertIsInstance(out, RuntimeError)
        self.assertIn("did not wake", str(out))
        self.assertNotIn("HTTPSConnectionPool", str(out))
        p.assert_not_called()

    def test_a_slow_portal_request_is_not_retried_and_says_so(self) -> None:
        ok = SimpleNamespace(ok=True)
        out, g, p = self._portal(get=lambda *a, **k: ok, post=requests.Timeout("Read timed out (read timeout=45)"))
        self.assertIsInstance(out, RuntimeError)
        self.assertIn("not retried", str(out))
        self.assertEqual(p.call_count, 1)

    def test_success_warms_then_posts_once_with_bounded_timeouts(self) -> None:
        ok = SimpleNamespace(ok=True)
        resp = SimpleNamespace(ok=True, json=lambda: {"url": "https://billing.stripe.com/p/session/x"})
        out, g, p = self._portal(get=lambda *a, **k: ok, post=lambda *a, **k: resp)
        self.assertEqual(out, "https://billing.stripe.com/p/session/x")
        self.assertEqual(g.call_args.kwargs["timeout"], bc._HEALTH_TIMEOUT)
        self.assertEqual(p.call_args.kwargs["timeout"], bc._POST_TIMEOUT)
        self.assertTrue(g.call_args.args[0].endswith("/billing/health"))

    def test_identical_to_the_billing_candidate_client(self) -> None:
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        try:
            cand = subprocess.run(["git", "show", "c6c335e:baseball_billing_client.py"], cwd=root,
                                  capture_output=True, text=True, encoding="utf-8", check=True).stdout
        except Exception:
            self.skipTest("billing candidate commit not available in this clone")
        self.assertEqual((root / "baseball_billing_client.py").read_text(encoding="utf-8").replace("\r\n", "\n"),
                         cand.replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()
