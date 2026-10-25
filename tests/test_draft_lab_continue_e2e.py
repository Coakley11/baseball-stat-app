"""Hosted-staging Continue flows through real app runs (AppTest), staging-like startup.

Staging differs from a local run in its restore order: Supabase is configured, so the
workspace restore is cloud-first, it is skipped while resume params are in the URL, and the
first real cloud apply lands on a later rerun (after the resume has finalized and removed
its params), plus a post-login cold re-hydrate. These tests fake exactly that — cloud
storage on, a cloud ``full_session`` holding a stale saved page, cloud saves dropped, a
forced cold workspace sync before run 2 — with no network access.

Pins the hosted failure from 2026-10-24: the Draft Lab simulation's Continue item
(``?suite_resume=roster:Team A&suite_page=Draft Room``) opened Historical Explorer.
Unit coverage of the guard and page names is in ``test_continue_link_page_names.py``.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WS_ID = "guest"
WS_FILE = ROOT / "data" / "workspaces" / WS_ID / "baseball_user_state.json"
DRAFT_LAB = "Draft Lab / Simulation"
HISTORICAL = "Historical Explorer"


def _write_disk_workspace(page: str) -> None:
    WS_FILE.parent.mkdir(parents=True, exist_ok=True)
    WS_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "app": "baseball",
                "saved_at": "2026-01-01T00:00:00+00:00",
                "state": {"active_page": page, "main_sidebar_page": page, "_suite_last_persisted_page": page},
            }
        ),
        encoding="utf-8",
    )


def _state(at, key, default=None):
    try:
        return at.session_state[key]
    except Exception:
        return default


class HostedContinueEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._backup = WS_FILE.read_bytes() if WS_FILE.is_file() else None
        cls._dir_created = not WS_FILE.parent.exists()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._backup is not None:
            WS_FILE.write_bytes(cls._backup)
        elif WS_FILE.is_file():
            WS_FILE.unlink()
        if cls._dir_created and WS_FILE.parent.exists():
            shutil.rmtree(WS_FILE.parent, ignore_errors=True)

    def _cloud(self, saved_page: str) -> None:
        """Staging stand-in: cloud-first restore of a stale saved page; no network, no saves."""
        import suite_cloud_state as scs

        _write_disk_workspace(saved_page)
        state = {"active_page": saved_page, "main_sidebar_page": saved_page, "_suite_last_persisted_page": saved_page}
        ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
        for target, value in (
            ("suite_storage_config.cloud_storage_enabled", lambda *a, **k: True),
            ("suite_cloud_state.load_cloud_full_session_status",
             lambda app_id, force=False: scs.CloudRead(dict(state), ts, scs.CLOUD_READ_OK)),
            ("suite_cloud_state.load_cloud_full_session", lambda app_id, force=False: (dict(state), ts)),
            ("suite_cloud_state.save_cloud_full_session", lambda *a, **k: False),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _runs(self, query: dict[str, str], *, runs: int = 3):
        """Fresh session opened on ``query``; before run 2 a post-login cold workspace sync."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=400)
        for k, v in query.items():
            at.query_params[k] = v
        at.query_params["suite_workspace"] = WS_ID
        pages = []
        for i in range(runs):
            if i == 1:
                at.session_state["_suite_workspace_force_sync"] = True
                at.session_state["_suite_auth_just_logged_in"] = True
            at.run()
            self.assertEqual([str(e.value)[:200] for e in at.exception], [], f"run {i + 1}")
            pages.append((_state(at, "active_page"), _state(at, "main_sidebar_page")))
        return at, pages

    def test_hosted_draft_lab_simulation_continue_opens_draft_lab(self) -> None:
        """The exact hosted card: Continue roster building · Team A (QA suite_resume_items)."""
        self._cloud(HISTORICAL)
        at, pages = self._runs({"suite_resume": "roster:Team A", "suite_page": "Draft Room", "suite_my_team": "Team A"})
        self.assertEqual(pages, [(DRAFT_LAB, DRAFT_LAB)] * 3)

    def test_draft_lab_resume_link_wins_and_keeps_room_and_section(self) -> None:
        """bb:draft_lab Continue (Analyze Completed Draft) over a stale Historical Explorer save."""
        self._cloud(HISTORICAL)
        room = "DR-E2E-ROOM1"
        at, pages = self._runs(
            {
                "suite_resume": f"bb:draft_lab:team:{room}",
                "suite_page": DRAFT_LAB,
                "suite_draft_room": room,
                "suite_draft_section": "team_analysis",
            }
        )
        self.assertEqual(pages, [(DRAFT_LAB, DRAFT_LAB)] * 3)
        self.assertEqual(_state(at, "_suite_resume_draft_room"), room)
        self.assertEqual(_state(at, "_suite_resume_draft_section"), "team_analysis")
        self.assertEqual(_state(at, "draft_lab_preferred_tab"), "Team Analysis")
        # The room is not in any store here, so the resume finishes with a visible, room-specific
        # error on Draft Lab — never a silent hop to another page.
        self.assertIn(room, str((_state(at, "_draft_lab_resume_error") or {}).get("room_id")))

    def test_historical_continue_still_restores_its_filters(self) -> None:
        self._cloud("Leaderboards")
        at, pages = self._runs(
            {
                "suite_resume": "historical:H:1921-1975",
                "suite_page": HISTORICAL,
                "suite_trend_player": "Bill Terry",
                "suite_historical_stat": "H",
                "suite_historical_year_start": "1921",
                "suite_historical_year_end": "1975",
            }
        )
        self.assertEqual(pages, [(HISTORICAL, HISTORICAL)] * 3)
        filters = (_state(at, "historical_state") or {}).get("filters") or {}
        self.assertEqual(filters.get("historical_sort_stat_filter"), "H")
        self.assertEqual(tuple(filters.get("historical_year_range_filter") or ()), (1921, 1975))

    def test_without_a_continue_link_the_saved_page_is_restored(self) -> None:
        self._cloud("Leaderboards")
        _at, pages = self._runs({}, runs=2)
        self.assertEqual([sidebar for _active, sidebar in pages], ["Leaderboards", "Leaderboards"])


if __name__ == "__main__":
    unittest.main()
