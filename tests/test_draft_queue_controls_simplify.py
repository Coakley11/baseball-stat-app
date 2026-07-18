"""Draft Queue UX: drag-only reorder, X remove, no Up/Down arrows, shared canonical state."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_participant_state import (
    load_participant_workflow_into_session,
    save_participant_workflow_from_session,
)
from draft_room_shared_state import LocalFileSharedRoomStore, reset_shared_room_store_for_tests
from draft_state import (
    DRAFT_QUEUE_KEY,
    add_player_to_draft_queue,
    remove_player_from_draft_queue,
    reorder_user_draft_queue,
)
from draft_ui import render_draft_queue_panel
from live_draft_autopick import _try_queue_auto_pick
from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create, set_live_draft_setup_mode
from live_draft_ui_cache import REC_CACHE_KEY
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


class _TrackingStreamlit:
    """Minimal Streamlit stub that records button labels/keys."""

    def __init__(self, *, button_clicks: set[str] | None = None) -> None:
        self.button_labels: list[str] = []
        self.button_keys: list[str] = []
        self.captions: list[str] = []
        self._button_clicks = button_clicks or set()
        self.sidebar = self
        self.session_state = {}

    def subheader(self, *_a, **_k) -> None:
        return None

    def markdown(self, *_a, **_k) -> None:
        return None

    def caption(self, text: str = "", *_a, **_k) -> None:
        self.captions.append(str(text))

    def info(self, *_a, **_k) -> None:
        return None

    def write(self, *_a, **_k) -> None:
        return None

    def button(self, label: str = "", **kwargs) -> bool:
        self.button_labels.append(str(label))
        key = str(kwargs.get("key") or "")
        self.button_keys.append(key)
        return key in self._button_clicks or str(label) in self._button_clicks

    def columns(self, spec: object) -> list["_TrackingStreamlit"]:
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        kids = [_TrackingStreamlit(button_clicks=self._button_clicks) for _ in range(n)]
        for kid in kids:
            kid.button_labels = self.button_labels
            kid.button_keys = self.button_keys
            kid.captions = self.captions
        return kids


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Francisco Lindor", "Primary Position": "SS"},
            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p3", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "p4", "fullName": "Shohei Ohtani", "Primary Position": "UTIL"},
        ]
    )
    return {
        "draft_room_id": "QCTRL1",
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
        AUTH_USER_EMAIL_KEY: "daniel.cohen11@yahoo.com",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        AUTH_USER_EMAIL_KEY: "coakley11@aol.com",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


ARROW_LABELS = {"↑", "↓", "⤒", "Up", "Down", "Top", "Move Up", "Move Down"}


class NoArrowRenderTests(unittest.TestCase):
    def _render(self, *, key_prefix: str, use_sidebar: bool, compact: bool) -> _TrackingStreamlit:
        st = _TrackingStreamlit()
        session = {
            DRAFT_QUEUE_KEY: ["Francisco Lindor", "Aaron Judge"],
            "draft_state": {"queue": ["Francisco Lindor", "Aaron Judge"]},
        }
        with mock.patch("draft_ui.render_draft_button", return_value=False), mock.patch(
            "draft_actions._prune_drafted_from_queue", return_value=None
        ), mock.patch(
            "draft_actions.draft_action_context",
            return_value={},
        ), mock.patch.dict("sys.modules", {"streamlit_sortables": mock.MagicMock()}):
            import sys

            sortables = sys.modules["streamlit_sortables"]
            sortables.sort_items = mock.Mock(side_effect=lambda items, **_k: list(items))
            render_draft_queue_panel(
                st,
                session,
                key_prefix=key_prefix,
                use_sidebar=use_sidebar,
                compact=compact,
                show_subheader=True,
            )
        return st

    def test_no_arrows_in_sidebar_queue(self) -> None:
        st = self._render(key_prefix="sidebar_queue", use_sidebar=True, compact=True)
        self.assertFalse(ARROW_LABELS.intersection(st.button_labels))
        self.assertFalse(any("_up_" in k or "_dn_" in k or "_top_" in k for k in st.button_keys))
        self.assertIn("✕", st.button_labels)

    def test_no_arrows_in_live_draft_queue(self) -> None:
        st = self._render(key_prefix="live_queue", use_sidebar=False, compact=False)
        self.assertFalse(ARROW_LABELS.intersection(st.button_labels))
        self.assertFalse(any("_up_" in k or "_dn_" in k or "_top_" in k for k in st.button_keys))

    def test_no_arrows_in_simulator_queue(self) -> None:
        st = self._render(key_prefix="sim_queue", use_sidebar=False, compact=False)
        self.assertFalse(ARROW_LABELS.intersection(st.button_labels))
        self.assertFalse(any("_up_" in k or "_dn_" in k or "_top_" in k for k in st.button_keys))

    def test_source_has_no_arrow_button_literals(self) -> None:
        path = Path(__file__).resolve().parents[1] / "draft_ui.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"↑", "↓", "⤒", "Up", "Down", "Top"}
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr != "button" or not node.args:
                    continue
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    if arg0.value in forbidden:
                        found.append(arg0.value)
        self.assertEqual(found, [], f"arrow button literals still in draft_ui.py: {found}")


class CanonicalReorderTests(unittest.TestCase):
    def test_drag_reorder_updates_canonical_queue(self) -> None:
        session = {DRAFT_QUEUE_KEY: ["Lindor", "Judge", "Soto"]}
        q, changed = reorder_user_draft_queue(session, ["Soto", "Lindor", "Judge"])
        self.assertTrue(changed)
        self.assertEqual(q, ["Soto", "Lindor", "Judge"])
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Soto", "Lindor", "Judge"])
        ds = session.get("draft_state") or {}
        self.assertEqual(ds.get("queue"), ["Soto", "Lindor", "Judge"])

    def test_sidebar_and_main_share_same_canonical_reorder(self) -> None:
        session = {DRAFT_QUEUE_KEY: ["A", "B", "C"]}
        reorder_user_draft_queue(session, ["C", "A", "B"], reason="drag_reorder_queue")
        # Both sidebar and main paint from DRAFT_QUEUE_KEY / draft_state — same list.
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["C", "A", "B"])
        self.assertEqual((session.get("draft_state") or {}).get("queue"), ["C", "A", "B"])

        st_side = _TrackingStreamlit()
        st_main = _TrackingStreamlit()
        with mock.patch("draft_ui.render_draft_button", return_value=False), mock.patch(
            "draft_actions._prune_drafted_from_queue"
        ), mock.patch("draft_actions.draft_action_context", return_value={}), mock.patch.dict(
            "sys.modules", {"streamlit_sortables": mock.MagicMock()}
        ):
            import sys

            sys.modules["streamlit_sortables"].sort_items = mock.Mock(
                side_effect=lambda items, **_k: list(items)
            )
            render_draft_queue_panel(
                st_side, session, key_prefix="sidebar_queue", use_sidebar=True, compact=True
            )
            render_draft_queue_panel(
                st_main, session, key_prefix="live_queue", use_sidebar=False, compact=False
            )
        # Visible order is the same canonical list for both surfaces.
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["C", "A", "B"])

    def test_main_reorder_updates_sidebar_source(self) -> None:
        session = {DRAFT_QUEUE_KEY: ["A", "B"]}
        reorder_user_draft_queue(session, ["B", "A"], reason="drag_reorder_queue")
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["B", "A"])

    def test_x_removes_correct_player(self) -> None:
        session = {DRAFT_QUEUE_KEY: ["Lindor", "Judge", "Soto"]}
        st = _TrackingStreamlit(button_clicks={"sidebar_queue_rm_1"})
        with mock.patch("draft_ui.render_draft_button", return_value=False), mock.patch(
            "draft_actions._prune_drafted_from_queue"
        ), mock.patch("draft_actions.draft_action_context", return_value={}), mock.patch.dict(
            "sys.modules", {"streamlit_sortables": mock.MagicMock()}
        ):
            import sys

            sys.modules["streamlit_sortables"].sort_items = mock.Mock(
                side_effect=lambda items, **_k: list(items)
            )
            rerun = render_draft_queue_panel(
                st, session, key_prefix="sidebar_queue", use_sidebar=True, compact=True
            )
        self.assertTrue(rerun)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Lindor", "Soto"])

    def test_reorder_persists_after_refresh_and_new_session_load(self) -> None:
        import copy

        from draft_room_participant_state import PARTICIPANT_STATE_KEY

        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFileSharedRoomStore(root=Path(tmp))
            reset_shared_room_store_for_tests(store)
            auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
            auth.start()
            try:
                host = _daniel()
                set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
                code, err = finalize_shared_room_create(
                    host, _sample_room(), host_team="Team A", store=store
                )
                self.assertFalse(err, err)
                add_player_to_draft_queue(host, "Francisco Lindor")
                add_player_to_draft_queue(host, "Aaron Judge")
                reorder_user_draft_queue(host, ["Aaron Judge", "Francisco Lindor"])
                save_participant_workflow_from_session(host, code)

                # Refresh: wipe widget cache, reload from participant-private slot.
                host[DRAFT_QUEUE_KEY] = []
                host["draft_state"] = {"queue": []}
                load_participant_workflow_into_session(host, code)
                self.assertEqual(
                    host.get(DRAFT_QUEUE_KEY),
                    ["Aaron Judge", "Francisco Lindor"],
                )

                # New session carrying durable participant state (workspace restore).
                restored = _daniel()
                restored[PARTICIPANT_STATE_KEY] = copy.deepcopy(host.get(PARTICIPANT_STATE_KEY))
                load_participant_workflow_into_session(restored, code)
                self.assertEqual(
                    restored.get(DRAFT_QUEUE_KEY),
                    ["Aaron Judge", "Francisco Lindor"],
                )
            finally:
                auth.stop()
                reset_shared_room_store_for_tests(None)

    def test_wipe_guard_rejects_empty_drag(self) -> None:
        session = {DRAFT_QUEUE_KEY: ["A", "B"]}
        q, changed = reorder_user_draft_queue(session, [])
        self.assertFalse(changed)
        self.assertEqual(q, ["A", "B"])


class IsolationAndAutopickTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_daniel_and_coakley_queues_remain_isolated_on_reorder(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        add_player_to_draft_queue(host, "Francisco Lindor")
        add_player_to_draft_queue(host, "Aaron Judge")
        reorder_user_draft_queue(host, ["Aaron Judge", "Francisco Lindor"])
        save_participant_workflow_from_session(host, code)

        add_player_to_draft_queue(guest, "Juan Soto")
        add_player_to_draft_queue(guest, "Shohei Ohtani")
        reorder_user_draft_queue(guest, ["Shohei Ohtani", "Juan Soto"])
        save_participant_workflow_from_session(guest, code)

        load_participant_workflow_into_session(host, code)
        load_participant_workflow_into_session(guest, code)
        self.assertEqual(host.get(DRAFT_QUEUE_KEY), ["Aaron Judge", "Francisco Lindor"])
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Shohei Ohtani", "Juan Soto"])

    def test_simulator_and_live_scopes_do_not_leak(self) -> None:
        live = {
            AUTH_USER_ID_KEY: "uuid-daniel",
            "active_shared_draft_room_code": "LIVE99",
            DRAFT_QUEUE_KEY: ["Live One", "Live Two"],
            "draft_state": {"queue": ["Live One", "Live Two"]},
        }
        sim = {
            AUTH_USER_ID_KEY: "uuid-daniel",
            "active_shared_draft_room_code": "",
            DRAFT_QUEUE_KEY: ["Sim One", "Sim Two"],
            "draft_state": {"queue": ["Sim One", "Sim Two"]},
        }
        reorder_user_draft_queue(live, ["Live Two", "Live One"], room_or_draft_id="LIVE99")
        reorder_user_draft_queue(sim, ["Sim Two", "Sim One"], room_or_draft_id="sim")
        self.assertEqual(live[DRAFT_QUEUE_KEY], ["Live Two", "Live One"])
        self.assertEqual(sim[DRAFT_QUEUE_KEY], ["Sim Two", "Sim One"])
        self.assertNotEqual(live[DRAFT_QUEUE_KEY], sim[DRAFT_QUEUE_KEY])

    def test_autopick_respects_each_participant_private_order(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        add_player_to_draft_queue(host, "Francisco Lindor")
        add_player_to_draft_queue(host, "Aaron Judge")
        reorder_user_draft_queue(host, ["Aaron Judge", "Francisco Lindor"])
        save_participant_workflow_from_session(host, code)

        add_player_to_draft_queue(guest, "Juan Soto")
        add_player_to_draft_queue(guest, "Shohei Ohtani")
        reorder_user_draft_queue(guest, ["Shohei Ohtani", "Juan Soto"])
        save_participant_workflow_from_session(guest, code)

        load_participant_workflow_into_session(host, code)
        load_participant_workflow_into_session(guest, code)

        available = pd.DataFrame(
            [
                {"fullName": "Francisco Lindor", "playerID": "p1"},
                {"fullName": "Aaron Judge", "playerID": "p2"},
                {"fullName": "Juan Soto", "playerID": "p3"},
                {"fullName": "Shohei Ohtani", "playerID": "p4"},
            ]
        )
        picked: list[str] = []

        def _pick(room, chosen, **_kwargs):
            name = str(chosen.get("fullName") or "")
            picked.append(name)
            return True, "ok"

        room_a = {"your_team": "Team A", "config": {"your_team": "Team A"}, "status": "in_progress"}
        room_b = {"your_team": "Team B", "config": {"your_team": "Team B"}, "status": "in_progress"}
        with mock.patch("live_draft_autopick.live_draft_make_pick", side_effect=_pick):
            ok_d, _ = _try_queue_auto_pick(room_a, host, available, "Team A")
            ok_c, _ = _try_queue_auto_pick(room_b, guest, available, "Team B")
        self.assertTrue(ok_d)
        self.assertTrue(ok_c)
        self.assertEqual(picked, ["Aaron Judge", "Shohei Ohtani"])


class LightweightPathTests(unittest.TestCase):
    def test_reorder_does_not_clear_recommendation_cache(self) -> None:
        session = {
            DRAFT_QUEUE_KEY: ["A", "B", "C"],
            REC_CACHE_KEY: {"key": ("rec",), "tables": {"ok": True}},
        }
        with mock.patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            reorder_user_draft_queue(session, ["C", "A", "B"])
            mock_save.assert_not_called()
        self.assertEqual(session[REC_CACHE_KEY]["key"], ("rec",))

    def test_remove_does_not_clear_recommendation_cache(self) -> None:
        session = {
            DRAFT_QUEUE_KEY: ["A", "B", "C"],
            REC_CACHE_KEY: {"key": ("rec",), "tables": {"ok": True}},
        }
        with mock.patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            remove_player_from_draft_queue(session, "B")
            mock_save.assert_not_called()
        self.assertEqual(session[REC_CACHE_KEY]["key"], ("rec",))
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["A", "C"])

    def test_panel_drag_calls_canonical_reorder_not_rec_engine(self) -> None:
        session = {DRAFT_QUEUE_KEY: ["A", "B", "C"], REC_CACHE_KEY: {"key": ("rec",)}}
        st = _TrackingStreamlit()
        with mock.patch("draft_ui.render_draft_button", return_value=False), mock.patch(
            "draft_actions._prune_drafted_from_queue"
        ), mock.patch("draft_actions.draft_action_context", return_value={}), mock.patch(
            "draft_state.reorder_user_draft_queue", wraps=reorder_user_draft_queue
        ) as reorder_spy, mock.patch.dict("sys.modules", {"streamlit_sortables": mock.MagicMock()}):
            import sys

            sys.modules["streamlit_sortables"].sort_items = mock.Mock(
                return_value=["C", "A", "B"]
            )
            render_draft_queue_panel(
                st, session, key_prefix="live_queue", use_sidebar=False, compact=False
            )
            self.assertTrue(reorder_spy.called)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["C", "A", "B"])
        self.assertEqual(session[REC_CACHE_KEY]["key"], ("rec",))


if __name__ == "__main__":
    unittest.main()
