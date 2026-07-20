"""Emergency Supabase egress hotfix regression coverage."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_room_shared_state import (
    LocalFileSharedRoomStore,
    bump_revision,
    shared_room_document,
    strip_shared_room_heavy_payload,
)
from live_draft_poll_ui import render_live_draft_poll_fragment
from suite_egress_policy import (
    SHARED_DRAFT_POLL_INTERVAL_SEC,
    SHARED_DRAFT_POLL_LOW_EGRESS_SEC,
    set_low_egress_mode,
    shared_draft_poll_interval_sec,
)


class TestPollIntervalNotCapped(unittest.TestCase):
    def test_low_egress_interval_is_about_eight_seconds(self) -> None:
        session: dict = {}
        set_low_egress_mode(session, True)
        self.assertGreaterEqual(shared_draft_poll_interval_sec(session), 7.5)
        self.assertEqual(shared_draft_poll_interval_sec(session), SHARED_DRAFT_POLL_LOW_EGRESS_SEC)

    def test_poll_ui_does_not_min_cap_to_one_second(self) -> None:
        src = Path(__file__).resolve().parents[1].joinpath("live_draft_poll_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("min(1.0, float(shared_draft_poll_interval_sec", src)
        self.assertIn("shared_draft_poll_interval_sec(session)", src)

    def test_timer_ui_does_not_min_cap_to_one_second(self) -> None:
        src = Path(__file__).resolve().parents[1].joinpath("live_draft_timer_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("min(1.0, float(shared_draft_poll_interval_sec", src)

    def test_poll_fragment_records_low_egress_interval_ms(self) -> None:
        st = MagicMock()
        # No fragment attribute → sync path, but still records interval before return.
        del st.fragment
        session: dict = {
            "active_shared_draft_room_code": "ABCD12",
            "live_draft_room": {"status": "in_progress", "timer_deadline": 9_999_999_999},
            "draft_room_shared_meta": {"revision": 1},
        }
        set_low_egress_mode(session, True)
        with patch("live_draft_poll_ui._poll_suppressed_reason", return_value=""):
            with patch("live_draft_poll_ui._run_shared_poll", return_value=False):
                with patch(
                    "draft_room_context.is_multiplayer_draft_active",
                    return_value=True,
                ):
                    render_live_draft_poll_fragment(st, session)
        diag = session.get("_live_draft_poll_diag") or {}
        self.assertGreaterEqual(int(diag.get("live_poll_interval_ms") or 0), 7500)


class TestSinglePollOwner(unittest.TestCase):
    def test_timer_skips_poll_when_fragment_active(self) -> None:
        src = Path(__file__).resolve().parents[1].joinpath("live_draft_timer_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if session.get("_live_draft_poll_fragment_active"):', src)
        self.assertIn("force=False", src)

    def test_on_clock_does_not_force_full_room_poll(self) -> None:
        src = Path(__file__).resolve().parents[1].joinpath("live_draft_on_clock_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("poll_shared_draft_room(session, force=True)", src)


class TestChatSidecarNoFullRoom(unittest.TestCase):
    def test_chat_refresh_uses_sidecar_not_full_load(self) -> None:
        from live_draft_chat import load_live_draft_chat, refresh_live_draft_chat_if_newer

        class _ChatOnlyStore:
            def __init__(self) -> None:
                self.full_loads = 0
                self.chat_loads = 0

            def load(self, _code: str):
                self.full_loads += 1
                raise AssertionError("full room load must not run for chat refresh")

            def load_chat_sidecar(self, code: str):
                self.chat_loads += 1
                return {
                    "room_code": code,
                    "revision": 3,
                    "chat": {
                        "chat_revision": 2,
                        "messages": [
                            {
                                "id": "m1",
                                "participant_id": "p1",
                                "text": "hi",
                                "ts": "2026-01-01T00:00:00Z",
                                "visibility": "public",
                            }
                        ],
                    },
                }

        store = _ChatOnlyStore()
        session = {
            "active_shared_draft_room_code": "ABCD12",
            "draft_room_participant_id": "p1",
            "draft_room_participant_team": "Team A",
            "room_your_team": "Team A",
        }
        with patch("draft_room_shared_state.get_shared_room_store", return_value=store):
            with patch(
                "draft_room_shared_state.load_shared_room",
                side_effect=AssertionError("no full room"),
            ):
                changed = refresh_live_draft_chat_if_newer(session)
                chat = load_live_draft_chat(session, force=False)
        self.assertTrue(changed)
        self.assertEqual(store.chat_loads, 1)
        self.assertEqual(store.full_loads, 0)
        self.assertEqual(len(chat.get("messages") or []), 1)

    def test_one_chat_refresh_does_not_duplicate_sidecar_reads(self) -> None:
        from live_draft_chat import refresh_live_draft_chat_if_newer

        class _CountStore:
            def __init__(self) -> None:
                self.chat_loads = 0
                self.full_loads = 0

            def load(self, _code: str):
                self.full_loads += 1
                raise AssertionError("full room load must not run")

            def load_chat_sidecar(self, code: str):
                self.chat_loads += 1
                return {
                    "room_code": code,
                    "revision": 1,
                    "chat": {"chat_revision": 1, "messages": []},
                }

        store = _CountStore()
        session = {
            "active_shared_draft_room_code": "ABCD12",
            "draft_room_participant_id": "p1",
            "draft_room_participant_team": "Team A",
        }
        with patch("draft_room_shared_state.get_shared_room_store", return_value=store):
            refresh_live_draft_chat_if_newer(session)
        self.assertEqual(store.chat_loads, 1)
        self.assertEqual(store.full_loads, 0)

    def test_chat_body_does_not_force_second_load(self) -> None:
        src = Path(__file__).resolve().parents[1].joinpath("live_draft_chat_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("load_live_draft_chat(session, force=False)", src)
        self.assertNotIn("load_live_draft_chat(session, force=True)", src)


class TestPoolStrippedFromSharedDocs(unittest.TestCase):
    def _room_with_pool(self) -> dict:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "a",
                    "fullName": "A",
                    "Primary Position": "SS",
                    "Model Rank": 1,
                    "Market Rank": 1,
                    "Expected Fantasy Value": 10.0,
                    "Fantasy Edge": 1.0,
                }
            ]
        )
        return {
            "draft_room_id": "d1",
            "status": "in_progress",
            "current_pick_index": 0,
            "draft_board": [],
            "rosters": {"Team A": []},
            "teams": ["Team A", "Team B"],
            "config": {"num_teams": 2, "teams": ["Team A", "Team B"], "timer_seconds": 60},
            "pool": pool,
            "recommendations": [{"x": 1}],
        }

    def test_create_and_bump_strip_pool_records(self) -> None:
        room = self._room_with_pool()
        doc = shared_room_document(
            room_code="ABCD12",
            host_participant_id="host",
            live_room=room,
        )
        blob = doc["room"]
        self.assertNotIn("pool", blob)
        self.assertNotIn("pool_records", blob)
        self.assertNotIn("pool_columns", blob)
        self.assertNotIn("recommendations", blob)

        bumped = bump_revision(doc, live_room={**room, "current_pick_index": 1})
        blob2 = bumped["room"]
        self.assertNotIn("pool", blob2)
        self.assertNotIn("pool_records", blob2)
        self.assertNotIn("pool_columns", blob2)

    def test_strip_helper_removes_heavy_keys(self) -> None:
        slim = strip_shared_room_heavy_payload(
            {"pool_records": [1], "pool_columns": ["a"], "draft_board": [], "status": "in_progress"}
        )
        self.assertEqual(slim.get("status"), "in_progress")
        self.assertNotIn("pool_records", slim)

    def test_local_store_roundtrip_without_pool(self) -> None:
        room = self._room_with_pool()
        doc = shared_room_document(room_code="ZZZZ99", host_participant_id="h", live_room=room)
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFileSharedRoomStore(root=Path(tmp))
            store.save(doc)
            loaded = store.load("ZZZZ99")
            assert loaded is not None
            self.assertNotIn("pool_records", (loaded.get("room") or {}))
            sidecar = store.load_chat_sidecar("ZZZZ99")
            assert sidecar is not None
            self.assertEqual(sidecar.get("_egress_kind"), "chat_sidecar")
            raw = json.loads((Path(tmp) / "ZZZZ99.json").read_text(encoding="utf-8"))
            size = len(json.dumps(raw).encode("utf-8"))
            # Without pool, a tiny room should stay well under 50 KB.
            self.assertLess(size, 50_000)


class TestPolicyConstants(unittest.TestCase):
    def test_normal_interval_is_two_point_five(self) -> None:
        self.assertEqual(SHARED_DRAFT_POLL_INTERVAL_SEC, 2.5)
        self.assertEqual(SHARED_DRAFT_POLL_LOW_EGRESS_SEC, 8.0)


if __name__ == "__main__":
    unittest.main()
