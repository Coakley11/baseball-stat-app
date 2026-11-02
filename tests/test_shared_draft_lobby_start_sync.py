"""A guest left in the Shared lobby after the commissioner starts must reach the live draft.

Production defect (2026-11-02): the Supabase head probe returned no live-room fields, so the
same-revision safety net never fired, and the lobby refresh advanced the session revision even
when the newer room failed to apply. A guest whose revision already matched the stored one
stayed on "not_started" through polling and through a browser refresh. Local stores only; the
Supabase store's own ``load_head`` runs against a fake ``_request`` that answers the projection.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from draft_room_context import (
    HEAD_DIVERGE_RELOAD_SEC,
    create_and_host_shared_room,
    join_shared_draft_room,
    refresh_shared_lobby_authority,
    sync_shared_draft_room,
)
from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    SHARED_ROOM_META_KEY,
    LocalFileSharedRoomStore,
    bump_revision,
)
from draft_room_supabase_store import SupabaseSharedRoomStore, _head_live_fields
from live_draft_state import LIVE_DRAFT_ROOM_KEY
from tests.test_draft_room_context import _sample_live_room


def _projected_row(document: dict) -> dict:
    """What PostgREST returns for the head select: columns plus the JSON projections."""
    room = document.get("room") if isinstance(document.get("room"), dict) else {}
    legacy = document.get("live_room") if isinstance(document.get("live_room"), dict) else {}
    return {
        "room_code": document.get("room_code"),
        "revision": document.get("revision"),
        "status": document.get("status"),
        "updated_at": document.get("updated_at"),
        "room_status": room.get("status"),
        "room_pick_index": room.get("current_pick_index"),
        "room_timer_deadline": room.get("timer_deadline"),
        "legacy_status": legacy.get("status"),
        "legacy_pick_index": legacy.get("current_pick_index"),
        "legacy_timer_deadline": legacy.get("timer_deadline"),
    }


class SupabaseHeadStore(LocalFileSharedRoomStore):
    """Local file storage whose head probe is the real Supabase ``load_head``."""

    def __init__(self, root: Path) -> None:
        super().__init__(root=root)
        self.head_selects: list[str] = []
        self.full_loads = 0

    def load(self, room_code: str):
        self.full_loads += 1
        return super().load(room_code)

    def load_head(self, room_code: str):
        def fake_request(method, table, *, params=None, prefer=None, **_kw):
            self.head_selects.append(str((params or {}).get("select") or ""))
            raw = json.loads(self._path(room_code).read_text(encoding="utf-8"))
            return [_projected_row(raw)]

        with patch("draft_room_supabase_store._request", side_effect=fake_request):
            return SupabaseSharedRoomStore().load_head(room_code)


def _lobby_room() -> dict:
    room = _sample_live_room()
    room["status"] = "not_started"
    room["timer_deadline"] = None
    room["timer_started_at"] = None
    # A real lobby has no board rows yet. (The shared sample's placeholder rows are read as
    # picks by repair_stale_live_draft_progress, so its local pick index never matches the store.)
    room["draft_board"] = []
    return room


class _TwoBrowserBase(unittest.TestCase):
    store_cls = LocalFileSharedRoomStore

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = self.store_cls(root=Path(self._tmp.name))
        self.host = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        self.code, _ = create_and_host_shared_room(self.host, _lobby_room(), host_team="Team 1", store=self.store)
        self.guest = {ACTIVE_PARTICIPANT_ID_KEY: "guest-user"}
        ok, msg, _ = join_shared_draft_room(self.guest, self.code, requested_team="Team 2", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(self.guest[LIVE_DRAFT_ROOM_KEY].get("status"), "not_started")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _host_starts(self) -> int:
        started = copy.deepcopy(self.host[LIVE_DRAFT_ROOM_KEY])
        started["status"] = "in_progress"
        self.store.save(bump_revision(self.store.load(self.code), live_room=started))
        return int(self.store.load(self.code)["revision"])

    def _guest_revision_matches_store(self, rev: int) -> None:
        """The stuck state: session room still the lobby, session revision already current."""
        self.guest[LIVE_DRAFT_ROOM_KEY]["status"] = "not_started"
        self.guest[SHARED_ROOM_META_KEY] = {**dict(self.guest.get(SHARED_ROOM_META_KEY) or {}), "revision": rev}

    def _poll(self, session: dict) -> bool:
        session.pop("_shared_draft_sync_run", None)
        return sync_shared_draft_room(session, store=self.store)


class AutomaticPollingTests(_TwoBrowserBase):
    def test_guest_poll_enters_draft_when_revision_advances(self) -> None:
        self._host_starts()
        self.assertTrue(self._poll(self.guest))
        self.assertEqual(self.guest[LIVE_DRAFT_ROOM_KEY].get("status"), "in_progress")

    def test_guest_poll_enters_draft_when_revision_already_matches(self) -> None:
        self._guest_revision_matches_store(self._host_starts())
        self.assertTrue(self._poll(self.guest))
        self.assertEqual(self.guest[LIVE_DRAFT_ROOM_KEY].get("status"), "in_progress")


class AutomaticPollingSupabaseHeadTests(AutomaticPollingTests):
    store_cls = SupabaseHeadStore


class SupabaseHeadProbeTests(unittest.TestCase):
    def test_head_select_projects_live_room_fields_only(self) -> None:
        captured: dict = {}

        def fake_request(method, table, *, params=None, prefer=None, **_kw):
            captured.update(params or {})
            return [{
                "room_code": "ABC123", "revision": 8, "status": "in_progress", "updated_at": "t",
                "room_status": "in_progress", "room_pick_index": 4, "room_timer_deadline": 1700000000.5,
            }]

        with patch("draft_room_supabase_store._request", side_effect=fake_request):
            head = SupabaseSharedRoomStore().load_head("abc123")
        select = captured["select"]
        self.assertIn("room_status:shared_room_json->room->>status", select)
        self.assertNotIn("shared_room_json,", select + ",")  # never the whole document
        self.assertEqual(head["revision"], 8)
        self.assertEqual(head["room_status"], "in_progress")
        self.assertEqual(head["current_pick_index"], 4)
        self.assertEqual(head["timer_deadline"], 1700000000.5)

    def test_head_fields_fall_back_to_legacy_live_room_and_match_local_store_shape(self) -> None:
        legacy = _head_live_fields({"legacy_status": "paused", "legacy_pick_index": "2", "legacy_timer_deadline": None})
        self.assertEqual(legacy, {"room_status": "paused", "current_pick_index": 2, "timer_deadline": None})
        empty = _head_live_fields({})
        self.assertEqual(empty, {"room_status": "", "current_pick_index": 0, "timer_deadline": None})


class ManualRefreshTests(_TwoBrowserBase):
    store_cls = SupabaseHeadStore

    def test_fresh_session_with_restored_revision_enters_draft_on_first_poll(self) -> None:
        rev = self._host_starts()
        # A browser refresh: new session restored from the workspace, with the lobby copy of the
        # room and the persisted meta revision already equal to the stored one.
        restored = {
            ACTIVE_PARTICIPANT_ID_KEY: "guest-user",
            ACTIVE_SHARED_ROOM_CODE_KEY: self.code,
            SHARED_ROOM_META_KEY: {"room_code": self.code, "revision": rev},
            LIVE_DRAFT_ROOM_KEY: copy.deepcopy(self.guest[LIVE_DRAFT_ROOM_KEY]),
        }
        self.assertEqual(restored[LIVE_DRAFT_ROOM_KEY].get("status"), "not_started")
        self.assertTrue(self._poll(restored))
        self.assertEqual(restored[LIVE_DRAFT_ROOM_KEY].get("status"), "in_progress")


class FailedApplyTests(_TwoBrowserBase):
    store_cls = SupabaseHeadStore

    def _refresh_with_publish(self, **publish_kwargs) -> None:
        with patch("draft_room_context.publish_shared_room_runtime", **publish_kwargs):
            refresh_shared_lobby_authority(self.guest, store=self.store, force_poll=False)

    def test_lobby_refresh_does_not_advance_revision_when_publish_returns_none(self) -> None:
        before = int(self.guest[SHARED_ROOM_META_KEY]["revision"])
        self._host_starts()
        self._refresh_with_publish(return_value=None)
        self.assertEqual(int(self.guest[SHARED_ROOM_META_KEY]["revision"]), before)
        self.assertFalse(self.guest["_shared_lobby_host_refresh_trace"]["session_revision_advanced"])
        # The next ordinary poll still sees a newer revision and applies it.
        self.assertTrue(self._poll(self.guest))
        self.assertEqual(self.guest[LIVE_DRAFT_ROOM_KEY].get("status"), "in_progress")

    def test_lobby_refresh_does_not_advance_revision_when_publish_raises(self) -> None:
        before = int(self.guest[SHARED_ROOM_META_KEY]["revision"])
        self._host_starts()
        self._refresh_with_publish(side_effect=RuntimeError("pool rebuild failed"))
        self.assertEqual(int(self.guest[SHARED_ROOM_META_KEY]["revision"]), before)
        self.assertTrue(self._poll(self.guest))
        self.assertEqual(self.guest[LIVE_DRAFT_ROOM_KEY].get("status"), "in_progress")

    def test_lobby_refresh_advances_revision_when_newer_room_applies(self) -> None:
        rev = self._host_starts()
        refresh_shared_lobby_authority(self.guest, store=self.store, force_poll=False)
        self.assertEqual(int(self.guest[SHARED_ROOM_META_KEY]["revision"]), rev)
        self.assertEqual(self.guest[LIVE_DRAFT_ROOM_KEY].get("status"), "in_progress")


class EgressBoundTests(_TwoBrowserBase):
    store_cls = SupabaseHeadStore

    def _settle(self, session: dict) -> None:
        """Bring the session to the stored revision with nothing different."""
        session.pop("_shared_draft_sync_run", None)
        sync_shared_draft_room(session, store=self.store, force=True)

    def test_unchanged_room_polls_head_only(self) -> None:
        self._settle(self.guest)
        self.store.full_loads = 0
        for _ in range(5):
            self.assertFalse(self._poll(self.guest))
        self.assertEqual(self.store.full_loads, 0)

    def test_local_timer_drift_costs_at_most_one_full_load_per_window(self) -> None:
        self._settle(self.host)
        self.store.full_loads = 0
        clock = [1_000_000.0]
        with patch("draft_room_context.time.time", side_effect=lambda: clock[0]):
            for _ in range(10):
                # A clock armed locally and never written: the head keeps differing.
                self.host[LIVE_DRAFT_ROOM_KEY]["timer_deadline"] = clock[0] + 60.0
                self._poll(self.host)
                clock[0] += 2.5
        self.assertEqual(self.store.full_loads, 1)

    def test_new_remote_deadline_is_loaded_immediately_despite_the_window(self) -> None:
        rev = self._host_starts()
        self._settle(self.guest)
        self.store.full_loads = 0
        # Timer writes may keep the revision (see test_unchanged_revision_still_syncs_timer_deadline).
        for deadline in (1793627218.0, 1793627248.0):
            stored = self.store.load(self.code)
            stored["room"] = {**dict(stored.get("room") or {}), "timer_deadline": deadline}
            self.store.save(stored)
            self.store.full_loads = 0
            self.assertTrue(self._poll(self.guest))
            self.assertEqual(int(self.store.load(self.code)["revision"]), rev)
            self.assertAlmostEqual(float(self.guest[LIVE_DRAFT_ROOM_KEY]["timer_deadline"]), deadline, delta=0.01)

    def test_persistent_status_difference_reloads_at_most_once_per_window(self) -> None:
        self._guest_revision_matches_store(self._host_starts())
        self.store.full_loads = 0
        clock = [1_000_000.0]
        # The room never applies (publish keeps failing), so the head stays different.
        with patch("draft_room_context.publish_shared_room_runtime", side_effect=RuntimeError("x")), \
                patch("draft_room_context.time.time", side_effect=lambda: clock[0]):
            for _ in range(10):
                self._poll(self.guest)
                clock[0] += 2.5  # the normal poll interval
            loads_in_window = self.store.full_loads
            clock[0] += HEAD_DIVERGE_RELOAD_SEC
            self._poll(self.guest)
        self.assertEqual(loads_in_window, 1)
        self.assertEqual(self.store.full_loads, 2)


if __name__ == "__main__":
    unittest.main()
