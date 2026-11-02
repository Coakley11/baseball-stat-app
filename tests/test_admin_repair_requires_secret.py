"""The URL-triggered admin Library repair runs only with the configured secret (security review)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import fantasy_admin_draft_archive_repair_ui as repair


def _st(query: str, secret: str | None):
    secrets = {"suite_activity": {"admin_draft_archive_repair_token": secret}} if secret is not None else {}
    return SimpleNamespace(query_params={"admin_draft_archive_repair": query}, secrets=secrets)


class AdminRepairSecretTests(unittest.TestCase):
    def test_without_the_secret_the_public_default_token_runs_nothing(self) -> None:
        for query in (repair.DEFAULT_REPAIR_LEAGUE_ID, f"{repair.DEFAULT_REPAIR_LEAGUE_ID}:force", "anything"):
            self.assertIsNone(repair._parse_repair_request(_st(query, None)), query)
            self.assertIsNone(repair._parse_repair_request(_st(query, "")), query)

    def test_with_the_secret_only_the_secret_runs_it(self) -> None:
        self.assertIsNone(repair._parse_repair_request(_st(repair.DEFAULT_REPAIR_LEAGUE_ID, "s3cret-token")))
        self.assertIsNotNone(repair._parse_repair_request(_st("s3cret-token", "s3cret-token")))


if __name__ == "__main__":
    unittest.main()
