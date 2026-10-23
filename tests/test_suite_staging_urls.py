"""A staging Baseball deployment links to itself and to its own Command Center; unset, every URL is production's."""

from __future__ import annotations

import os
import unittest
from unittest import mock
from urllib.parse import urlparse

from suite_command_center_link import _HOMEPAGE_DEV_URL, command_center_url
from suite_deep_links import APP_BASE_URLS, build_resume_action_url

STAGING_BASEBALL = "https://baseball-staging.example"
STAGING_CC = "https://command-center-staging.example"


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SUITE_APP_URL_") and k != "SUITE_COMMAND_CENTER_URL"}
    env.update(extra)
    return env


def _host(url: str) -> str:
    return urlparse(url).netloc


class StagingUrlTests(unittest.TestCase):
    def test_unset_links_are_production(self) -> None:
        with mock.patch.dict(os.environ, _env(), clear=True):
            card = build_resume_action_url("baseball", resume_key="historical:SB:2002-2025")
            analysis = build_resume_action_url("applied_intelligence", resume_key="ai:question:abc", page="Solve a Problem")
            home = command_center_url(workspace_id="qa")
        self.assertEqual(_host(card), _host(APP_BASE_URLS["baseball"]))
        self.assertEqual(_host(analysis), _host(APP_BASE_URLS["applied_intelligence"]))
        self.assertEqual(_host(home), _host(_HOMEPAGE_DEV_URL))

    def test_staging_overrides_move_only_what_they_name(self) -> None:
        with mock.patch.dict(os.environ, _env(SUITE_APP_URL_BASEBALL=STAGING_BASEBALL,
                                              SUITE_COMMAND_CENTER_URL=STAGING_CC + "/"), clear=True):
            card = build_resume_action_url("baseball", resume_key="historical:SB:2002-2025")
            analysis = build_resume_action_url("applied_intelligence", resume_key="ai:question:abc", page="Solve a Problem")
            home = command_center_url(workspace_id="qa")
        self.assertEqual(_host(card), _host(STAGING_BASEBALL))
        self.assertIn("suite_historical_stat=SB", card)
        self.assertEqual(_host(analysis), _host(APP_BASE_URLS["applied_intelligence"]))
        self.assertEqual(_host(home), _host(STAGING_CC))
        self.assertIn("suite_workspace=qa", home)


if __name__ == "__main__":
    unittest.main()
