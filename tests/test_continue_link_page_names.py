"""Command Center Continue links must name pages that exist (hosted staging, 2026-10-24).

Hosted failure this pins: running the Draft Lab simulation wrote a "Continue roster
building" item whose link carried ``?suite_page=Draft Room``. "Draft Room" is not a page.
The resume launcher wrote it into ``active_page`` and scheduled it; the same-page guard in
``_consume_scheduled_navigation`` counted the alias as "already on the page" and dropped the
schedule; the sidebar radio, seeded from that raw value on a fresh session, fell back to
``PAGE_OPTIONS[0]`` — Historical Explorer.

End-to-end coverage through real app runs lives in ``test_draft_lab_continue_e2e.py``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DRAFT_LAB = "Draft Lab / Simulation"


def _app():
    import streamlit_app as app

    return app


class _FakeSt:
    def __init__(self, session: dict):
        self.session_state = session


class ContinueLinkPageNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()

    def test_every_activity_emitter_page_resolves_without_fallback(self) -> None:
        """A page name that is neither a page nor an alias silently opens Historical Explorer."""
        known = set(self.app.PAGE_OPTIONS) | set(self.app._PAGE_LEGACY_ALIASES)
        found = []
        for path in sorted(ROOT.glob("baseball*activity*.py")):
            for name in re.findall(r'\bpage="([^"]+)"', path.read_text(encoding="utf-8")):
                found.append(name)
                self.assertIn(name, known, f"{path.name}: page={name!r} is not a page")
                self.assertIn(self.app.normalize_page_key(name), self.app.PAGE_OPTIONS)
        self.assertIn(DRAFT_LAB, found)

    def test_names_stored_in_existing_continue_links_resolve(self) -> None:
        """Links already written to Command Center keep their old names."""
        expected = {
            "Draft Room": DRAFT_LAB,
            "Draft Simulation": DRAFT_LAB,
            "Draft Simulation Test Mode": DRAFT_LAB,
            "ML Projections": "ML Predictions",
            "Fantasy Market": "Fantasy Sleepers & Busts",
            "Trade Center": "Fantasy Lineup Assistant",
        }
        for name, page in expected.items():
            self.assertEqual(self.app.normalize_page_key(name), page, name)
        for page in self.app._PAGE_LEGACY_ALIASES.values():
            self.assertIn(page, self.app.PAGE_OPTIONS)

    def test_unknown_names_still_fall_back(self) -> None:
        self.assertEqual(self.app.normalize_page_key("Not A Real Page"), self.app.PAGE_OPTIONS[0])
        self.assertEqual(self.app.normalize_page_key(""), "")

    def _recorded(self, fn, **kwargs) -> dict:
        calls = []
        with mock.patch("suite_activity_client.record_activity", side_effect=lambda *a, **k: calls.append((a, k))):
            fn(**kwargs)
        self.assertEqual(len(calls), 1)
        (app_key, event), kw = calls[0][0], calls[0][1]
        self.assertEqual(app_key, "baseball")
        return {"event": event, **kw}

    def _continue_url(self, rec: dict) -> dict[str, str]:
        from urllib.parse import parse_qs, urlparse

        from suite_deep_links import build_resume_action_url

        url = build_resume_action_url(
            "baseball",
            resume_key=rec["resume_key"],
            page=rec["page"],
            metrics=rec["metrics"],
            base_url="https://baseball.example",
        )
        return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

    def test_draft_lab_simulation_continue_items_open_draft_lab(self) -> None:
        """Both items the Draft Lab simulation writes (streamlit_app: log_draft_prep +
        log_roster_build) must reopen Draft Lab, not Historical Explorer / Draft Room Simulator."""
        import baseball_activity

        roster = self._recorded(baseball_activity.log_roster_build, team="Team A")
        self.assertEqual(roster["resume_key"], "roster:Team A")
        qp = self._continue_url(roster)
        self.assertEqual(self.app.normalize_page_key(qp["suite_page"]), DRAFT_LAB)

        prep = self._recorded(baseball_activity.log_draft_prep, context="5x5 Roto", teams="4-team draft lab")
        qp = self._continue_url(prep)
        self.assertEqual(qp["suite_page"], DRAFT_LAB)
        # Its own resume item: it no longer overwrites the Draft Room Simulator's "Continue mock draft".
        self.assertNotEqual(prep["resume_key"], "bb:simulator_draft")
        # Not a room-scoped key: bb:draft_lab:<tail> would be parsed as a room id and fail restore.
        self.assertFalse(prep["resume_key"].startswith("bb:draft_lab:"))


class ConsumeAliasScheduleTests(unittest.TestCase):
    """_consume_scheduled_navigation on the exact state the resume launcher leaves."""

    def setUp(self) -> None:
        self.app = _app()
        self._real_st = self.app.st

    def tearDown(self) -> None:
        self.app.st = self._real_st

    def _consume(self, session: dict):
        self.app.st = _FakeSt(session)
        return self.app._consume_scheduled_navigation()

    def test_alias_written_into_active_page_is_not_the_same_page(self) -> None:
        """suite_resume_launch._apply_baseball writes the raw ?suite_page= into active_page,
        _navigate_to_page and _skip_page_restore_for. The schedule must still be applied."""
        session = {
            "active_page": "Draft Room",
            "_navigate_to_page": "Draft Room",
            "_skip_page_restore_for": "Draft Room",
            "_suite_page_user_nav": True,
        }
        self.assertEqual(self._consume(session), DRAFT_LAB)
        self.assertEqual(session["active_page"], DRAFT_LAB)
        self.assertEqual(session[self.app.MAIN_SIDEBAR_PAGE_KEY], DRAFT_LAB)
        self.assertEqual(session["_skip_page_restore_for"], DRAFT_LAB)
        self.assertNotIn(self.app.BAD_PAGE_LINK_NOTICE_KEY, session)

    def test_canonical_same_page_schedule_is_still_ignored(self) -> None:
        session = {"active_page": DRAFT_LAB, "_navigate_to_page": DRAFT_LAB}
        self.assertIsNone(self._consume(session))

    def test_unknown_scheduled_page_is_reported_not_silent(self) -> None:
        session = {"active_page": "Not A Real Page", "_navigate_to_page": "Not A Real Page"}
        target = self._consume(session)
        self.assertEqual(target, self.app.PAGE_OPTIONS[0])
        self.assertEqual(session[self.app.BAD_PAGE_LINK_NOTICE_KEY], target)

    def test_internal_sentinel_schedule_is_not_reported(self) -> None:
        session = {"_navigate_to_page": "__MONETIZATION_GATE__"}
        self._consume(session)
        self.assertNotIn(self.app.BAD_PAGE_LINK_NOTICE_KEY, session)

    def test_sidebar_radio_seed_is_canonicalized(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        start = src.index("_radio_seed_page = st.session_state.get(\"active_page\", \"Home\")")
        block = src[start:start + 400]
        self.assertIn("normalize_page_key(_radio_seed_page)", block)


if __name__ == "__main__":
    unittest.main()
