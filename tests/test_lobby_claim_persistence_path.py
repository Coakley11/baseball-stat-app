"""Two-session Shared Multiplayer claim path — catches host stale GET cache / CAS races."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import (
    join_shared_draft_room,
    poll_shared_draft_room,
    refresh_shared_lobby_authority,
    reset_shared_draft_sync_gate,
)
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    SHARED_ROOM_META_KEY,
    LocalFileSharedRoomStore,
    reset_shared_room_store_for_tests,
)
from live_draft_presence import (
    JOINED_PARTICIPANTS_KEY,
    count_required_joined,
    mark_participant_present,
    required_human_participant_rows,
)
from live_draft_setup_mode import SETUP_MODE_SHARED, can_start_live_draft, finalize_shared_room_create, set_live_draft_setup_mode
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "CLAIM1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_cloud_user_id": "cloud-daniel-alias",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        "participant_display_name": "daniel.cohen11",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        "_suite_cloud_user_id": "cloud-coakley-alias",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "participant_display_name": "coakley11",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


class CachingSharedRoomStore:
    """Wraps LocalFile with a per-session GET cache (reproduces pre-fix Supabase host bug)."""

    def __init__(self, inner: LocalFileSharedRoomStore, cache_bucket: dict) -> None:
        self.inner = inner
        self.cache_bucket = cache_bucket
        self.load_calls = 0
        self.cache_hits = 0

    def exists(self, room_code: str) -> bool:
        return self.inner.exists(room_code)

    def load(self, room_code: str) -> dict | None:
        self.load_calls += 1
        code = str(room_code or "").strip().upper()
        # Session-scoped cache — host/guest buckets are separate dicts.
        hit = self.cache_bucket.get(code)
        if isinstance(hit, dict):
            self.cache_hits += 1
            return copy.deepcopy(hit)
        doc = self.inner.load(code)
        if isinstance(doc, dict):
            self.cache_bucket[code] = copy.deepcopy(doc)
        return copy.deepcopy(doc) if isinstance(doc, dict) else None

    def load_head(self, room_code: str) -> dict | None:
        # Head must be fresh (lightweight revision probe).
        return self.inner.load_head(room_code)

    def save(self, document: dict) -> dict:
        saved = self.inner.save(document)
        code = str(saved.get("room_code") or "").strip().upper()
        # Writer invalidates only its own bucket (mirrors suite_storage_supabase).
        self.cache_bucket.pop(code, None)
        return saved

    def save_if_revision(self, document: dict, *, expected_revision: int | None):
        ok, saved = self.inner.save_if_revision(document, expected_revision=expected_revision)
        if ok and isinstance(saved, dict):
            code = str(saved.get("room_code") or "").strip().upper()
            self.cache_bucket.pop(code, None)
        return ok, saved


class TwoSessionLobbyClaimPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.disk = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host_cache: dict = {}
        self.guest_cache: dict = {}
        self.host_store = CachingSharedRoomStore(self.disk, self.host_cache)
        self.guest_store = CachingSharedRoomStore(self.disk, self.guest_cache)
        # Factory returns disk for reset helpers; tests pass store= explicitly.
        reset_shared_room_store_for_tests(self.disk)
        self._patches = [
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
            mock.patch("suite_auth.is_auth_enabled", return_value=True),
            mock.patch("suite_auth.is_authenticated", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_guest_claim_survives_host_stale_get_cache_and_presence(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(
            host, _sample_room(), host_team="Team A", store=self.host_store
        )
        self.assertFalse(err, err)
        host_rev_1 = int((host.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
        self.assertGreaterEqual(host_rev_1, 1)

        # Snapshot pre-claim document into the host-only GET cache.
        primed = self.disk.load(code)
        self.assertIsInstance(primed, dict)
        self.host_cache[code] = copy.deepcopy(primed)
        cached_rev = int(self.host_cache[code].get("revision") or 0)

        guest = _coakley()
        ok, msg, guest_doc = join_shared_draft_room(
            guest, code, requested_team="Team B", store=self.guest_store
        )
        self.assertTrue(ok, msg)
        self.assertIsInstance(guest_doc, dict)

        # Authoritative disk must show Team B → Coakley immediately.
        disk_doc = self.disk.load(code)
        self.assertIsInstance(disk_doc, dict)
        parts = dict(disk_doc.get("participants") or {})
        coakley_id = guest["draft_room_participant_id"]
        self.assertEqual(str((parts.get(coakley_id) or {}).get("assigned_team")), "Team B")
        disk_rev = int(disk_doc.get("revision") or 0)
        self.assertGreater(disk_rev, cached_rev)

        # Host session still on the older revision; host GET cache still pre-claim.
        self.assertEqual(int((host.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0), host_rev_1)
        self.assertEqual(int(self.host_cache[code].get("revision") or 0), cached_rev)
        stale = self.host_store.load(code)
        self.assertEqual(int(stale.get("revision") or 0), cached_rev)
        self.assertNotIn(coakley_id, dict(stale.get("participants") or {}))

        # Production fix: lobby invalidate drops GET cache, then host applies newer rev.
        from draft_room_shared_state import invalidate_shared_room_document_cache

        real_invalidate = invalidate_shared_room_document_cache

        def _invalidate_with_get_cache(session, room_code=""):
            real_invalidate(session, room_code)
            self.host_cache.clear()

        with mock.patch(
            "draft_room_shared_state.invalidate_shared_room_document_cache",
            side_effect=_invalidate_with_get_cache,
        ):
            reset_shared_draft_sync_gate(host)
            poll_shared_draft_room(host, force=True, store=self.host_store)
            authority = refresh_shared_lobby_authority(host, store=self.host_store, force_poll=True)
        self.assertIsInstance(authority, dict)
        self.assertEqual(int(authority.get("revision") or 0), disk_rev)
        self.assertIn(coakley_id, dict(authority.get("participants") or {}))

        joined, total, rows = count_required_joined(
            host, host.get("live_draft_room") or {}, document=authority
        )
        self.assertEqual((joined, total), (2, 2))
        teams = {
            str(r.get("team_name") or r.get("team") or r.get("Team") or "") for r in rows
        }
        self.assertIn("Team A", teams)
        self.assertIn("Team B", teams)

        # can_start_live_draft uses get_shared_room_store(); point it at disk for this test.
        reset_shared_room_store_for_tests(self.disk)
        self.host_cache.clear()
        ok_start, reason = can_start_live_draft(host)
        self.assertTrue(ok_start, reason)

        # Presence heartbeat on host must not erase Team B (CAS + fresh load).
        self.host_cache.clear()
        mark_participant_present(host, force_save=True, store=self.host_store)
        after = self.disk.load(code)
        parts_after = dict(after.get("participants") or {})
        self.assertEqual(str((parts_after.get(coakley_id) or {}).get("assigned_team")), "Team B")

        # Refresh both sessions — claims retained.
        guest2 = _coakley()
        guest2[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        self.guest_cache.clear()
        self.host_cache.clear()
        g_auth = refresh_shared_lobby_authority(guest2, store=self.guest_store, force_poll=True)
        h_auth = refresh_shared_lobby_authority(host, store=self.host_store, force_poll=True)
        for doc in (g_auth, h_auth):
            p = dict(doc.get("participants") or {})
            self.assertEqual(str((p.get(coakley_id) or {}).get("assigned_team")), "Team B")
    def test_shared_document_keys_match_for_host_and_guest(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(
            host, _sample_room(), host_team="Team A", store=self.disk
        )
        self.assertFalse(err, err)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.disk)
        self.assertTrue(ok, msg)
        host_key = f"local_file:{code}"
        guest_key = str((guest.get("_shared_join_claim_trace") or {}).get("storage_key") or "")
        # Join trace uses shared_room_backend_name(); under test reset store is local.
        self.assertTrue(guest_key.endswith(f":{code}") or guest_key == host_key or code in guest_key)
        refresh_shared_lobby_authority(host, store=self.disk, force_poll=True)
        host_trace = host.get("_shared_lobby_host_refresh_trace") or {}
        self.assertEqual(host_trace.get("room_code"), code)
        self.assertEqual(str(host_trace.get("storage_key") or "").split(":")[-1], code)


class SharedRoomGetCacheBypassTests(unittest.TestCase):
    def test_shared_draft_rooms_table_not_cached(self) -> None:
        from suite_storage_supabase import _NO_GET_CACHE_TABLES, _request

        self.assertIn("baseball_shared_draft_rooms", _NO_GET_CACHE_TABLES)
        calls = {"n": 0}

        class _Resp:
            status_code = 200
            content = b"[]"
            text = "[]"

            def json(self):
                return []

        def fake_request(*_a, **_k):
            calls["n"] += 1
            return _Resp()

        with mock.patch("suite_storage_supabase.get_cloud_config") as cfg, mock.patch(
            "requests.request", side_effect=fake_request
        ):
            cfg.return_value = mock.Mock(url="https://example.supabase.co", service_role_key="k", anon_key="a")
            # Even if a stale cache entry exists, shared rooms must bypass it.
            import suite_storage_supabase as mod

            bucket = {
                ("GET", "baseball_shared_draft_rooms", (("limit", "1"), ("room_code", "eq.ABC"), ("select", "room_code"))): (
                    2,
                    [{"room_code": "STALE"}],
                )
            }
            with mock.patch.object(mod, "_read_cache_bucket", return_value=bucket):
                out = _request(
                    "GET",
                    "baseball_shared_draft_rooms",
                    params={
                        "select": "room_code",
                        "room_code": "eq.ABC",
                        "limit": "1",
                    },
                    prefer="return=representation",
                )
            self.assertEqual(out, [])
            self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
