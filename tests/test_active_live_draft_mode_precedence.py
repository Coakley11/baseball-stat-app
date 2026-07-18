"""Active Live Draft mode must follow shared-room identity over setup prefs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    SHARED_ROOM_META_KEY,
    LocalFileSharedRoomStore,
    reset_shared_room_store_for_tests,
)
from live_draft_room_ui import render_live_draft_room_header
from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    can_start_live_draft,
    get_preferred_next_draft_mode,
    is_shared_multiplayer_intent,
    is_solo_draft_mode,
    resolve_active_live_draft_mode,
    set_live_draft_setup_mode,
)
from live_draft_setup_mode import finalize_shared_room_create
from live_draft_presence import count_required_joined
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "MODE1",
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
        # Preferred next mode is Solo — must not relabel an active shared room.
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,
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
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
    }


class ActiveModePrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
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

    def test_solo_preference_does_not_relabel_active_shared_room(self) -> None:
        host = _daniel()
        self.assertEqual(get_preferred_next_draft_mode(host), SETUP_MODE_SOLO)
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        # User preference snaps back to Solo (saved next-draft choice) while room stays.
        host[LIVE_DRAFT_SETUP_MODE_KEY] = SETUP_MODE_SOLO

        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        # Reload Daniel with Solo preference but authoritative room + code present.
        reloaded = _daniel()
        reloaded[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        reloaded[SHARED_ROOM_META_KEY] = dict(host.get(SHARED_ROOM_META_KEY) or {})
        reloaded["live_draft_room"] = dict(host.get("live_draft_room") or {})
        doc = self.store.load(code)
        reloaded["_shared_lobby_authority_doc"] = doc

        active = resolve_active_live_draft_mode(reloaded, document=doc, room=reloaded["live_draft_room"])
        self.assertEqual(active["mode"], SETUP_MODE_SHARED, active)
        self.assertEqual(active["room_code"], code)
        self.assertEqual(active["source"], "authoritative_shared_room")
        self.assertEqual(active["preferred_next_draft_mode"], SETUP_MODE_SOLO)
        self.assertTrue(is_shared_multiplayer_intent(reloaded, room=reloaded["live_draft_room"]))
        self.assertFalse(is_solo_draft_mode(reloaded, room=reloaded["live_draft_room"]))

        joined, total, _ = count_required_joined(
            reloaded, reloaded["live_draft_room"], document=doc
        )
        self.assertEqual((joined, total), (2, 2))
        ok_start, reason = can_start_live_draft(reloaded)
        self.assertTrue(ok_start, reason)

        st = mock.MagicMock()
        with mock.patch("draft_room_context.get_global_draft_context") as ctx:
            ctx.return_value = {
                "is_room_host": True,
                "participant_team": "Team A",
                "room_code": code,
            }
            render_live_draft_room_header(
                st,
                reloaded,
                reloaded["live_draft_room"],
                multiplayer=True,
                user_team="Team A",
                on_clock_team="Team A",
                pick_label="Pick 1 of 8",
                status_label="Not Started",
                draft_in_progress=False,
            )
        joined_md = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("Shared Multiplayer", joined_md)
        self.assertIn(code, joined_md)
        self.assertNotIn("Solo Draft", joined_md)
        self.assertNotIn("Code missing", joined_md)
        # No raw markdown/HTML leakage as visible text (unsafe_allow_html consumes tags).
        for frag in ("**Live**", "Your Fantasy Team: **"):
            self.assertNotIn(frag, joined_md)

        # Refresh must remain Shared.
        active2 = resolve_active_live_draft_mode(reloaded, document=doc)
        self.assertEqual(active2["mode"], SETUP_MODE_SHARED)

    def test_preferred_shared_true_solo_runtime_stays_solo(self) -> None:
        session = {
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
            "live_draft_room": {
                "status": "in_progress",
                "config": {"draft_setup_mode": SETUP_MODE_SOLO, "num_teams": 8},
                "teams": [f"Team {i}" for i in range(1, 9)],
            },
        }
        active = resolve_active_live_draft_mode(session, room=session["live_draft_room"])
        self.assertEqual(active["mode"], SETUP_MODE_SOLO, active)
        self.assertEqual(active["source"], "runtime_solo_stamp")
        self.assertTrue(is_solo_draft_mode(session, room=session["live_draft_room"]))
        self.assertFalse(is_shared_multiplayer_intent(session, room=session["live_draft_room"]))

    def test_header_html_has_no_markdown_bold_in_status(self) -> None:
        st = mock.MagicMock()
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "XYZ999",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,  # preference must lose
            "live_draft_room": {
                "status": "not_started",
                "config": {"draft_setup_mode": SETUP_MODE_SHARED, "your_team": "Team A"},
                "teams": ["Team A", "Team B"],
            },
            "_shared_lobby_authority_doc": {
                "room_code": "XYZ999",
                "status": "not_started",
                "revision": 2,
                "participants": {
                    "uuid-daniel": {"assigned_team": "Team A", "display_name": "daniel"},
                    "uuid-coak": {"assigned_team": "Team B", "display_name": "coakley11"},
                },
            },
        }
        with mock.patch("draft_room_context.get_global_draft_context") as ctx, mock.patch(
            "live_draft_team_ownership.team_claim_rows",
            return_value=[
                {
                    "team": "Team A",
                    "claimed": True,
                    "is_host": True,
                    "owner_label": "daniel",
                },
                {
                    "team": "Team B",
                    "claimed": True,
                    "is_host": False,
                    "owner_label": "coakley11",
                },
            ],
        ):
            ctx.return_value = {
                "is_room_host": True,
                "participant_team": "Team A",
                "room_code": "XYZ999",
            }
            render_live_draft_room_header(
                st,
                session,
                session["live_draft_room"],
                multiplayer=True,
                user_team="Team A",
                status_label="Not Started",
                draft_in_progress=True,
            )
        html = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("Shared Multiplayer", html)
        self.assertIn("XYZ999", html)
        self.assertIn("<strong>Live</strong>", html)
        self.assertNotIn("**Live**", html)
        self.assertNotIn("Your Fantasy Team: **", html)
        # Tags are inside unsafe_allow_html payloads (kwargs), not as escaped visible text.
        self.assertTrue(any(c.kwargs.get("unsafe_allow_html") for c in st.markdown.call_args_list))


if __name__ == "__main__":
    unittest.main()
