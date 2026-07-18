"""Sidebar ↔ Live Draft ↔ Simulator queue remove/reorder share one canonical state."""

from __future__ import annotations

import unittest
from unittest import mock

from draft_state import (
    DRAFT_QUEUE_KEY,
    add_player_to_draft_queue,
    remove_player_from_user_draft_queue,
    reorder_user_draft_queue,
)
from draft_ui import _resolve_visible_draft_queue, render_draft_queue_panel
from live_draft_ui_cache import REC_CACHE_KEY
from suite_auth import AUTH_USER_ID_KEY


class _TrackingStreamlit:
    def __init__(self, *, button_clicks: set[str] | None = None) -> None:
        self.button_labels: list[str] = []
        self.button_keys: list[str] = []
        self._button_clicks = button_clicks or set()
        self.sidebar = self
        self.session_state = {}

    def subheader(self, *_a, **_k) -> None:
        return None

    def markdown(self, *_a, **_k) -> None:
        return None

    def caption(self, *_a, **_k) -> None:
        return None

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
        return kids


ARROW_LABELS = {"↑", "↓", "⤒", "Up", "Down", "Top", "Move Up", "Move Down"}


class BidirectionalQueueSyncTests(unittest.TestCase):
    def _session(self, queue: list[str]) -> dict:
        return {
            AUTH_USER_ID_KEY: "uuid-daniel",
            "active_shared_draft_room_code": "LIVE99",
            DRAFT_QUEUE_KEY: list(queue),
            "draft_state": {"queue": list(queue)},
            REC_CACHE_KEY: {"key": ("rec",), "tables": {"ok": True}},
        }

    def _render(self, st, session, *, key_prefix: str, use_sidebar: bool, compact: bool) -> None:
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
                st,
                session,
                key_prefix=key_prefix,
                use_sidebar=use_sidebar,
                compact=compact,
                show_subheader=True,
            )

    def test_live_main_remove_updates_sidebar_source(self) -> None:
        session = self._session(["Francisco Lindor", "Aaron Judge"])
        remove_player_from_user_draft_queue(session, "Francisco Lindor")
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Aaron Judge"])
        side_q, _ = _resolve_visible_draft_queue(session, qkey=DRAFT_QUEUE_KEY)
        main_q, _ = _resolve_visible_draft_queue(session, qkey=DRAFT_QUEUE_KEY)
        self.assertEqual(side_q, ["Aaron Judge"])
        self.assertEqual(main_q, ["Aaron Judge"])

    def test_sidebar_remove_updates_main_source(self) -> None:
        session = self._session(["Francisco Lindor", "Aaron Judge"])
        st = _TrackingStreamlit(button_clicks={"sidebar_queue_rm_1"})
        self._render(st, session, key_prefix="sidebar_queue", use_sidebar=True, compact=True)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Francisco Lindor"])
        main_q, _ = _resolve_visible_draft_queue(session, qkey=DRAFT_QUEUE_KEY)
        self.assertEqual(main_q, ["Francisco Lindor"])

    def test_sim_main_remove_updates_sidebar_source(self) -> None:
        session = self._session(["Sim A", "Sim B"])
        session["active_shared_draft_room_code"] = ""
        st = _TrackingStreamlit(button_clicks={"sim_queue_rm_0"})
        self._render(st, session, key_prefix="sim_queue", use_sidebar=False, compact=False)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Sim B"])
        side_q, _ = _resolve_visible_draft_queue(session, qkey=DRAFT_QUEUE_KEY)
        self.assertEqual(side_q, ["Sim B"])

    def test_empty_after_both_removes_no_last_good_rehydrate(self) -> None:
        session = self._session(["Francisco Lindor", "Aaron Judge"])
        session["_live_draft_queue_last_good"] = ["Francisco Lindor", "Aaron Judge"]
        remove_player_from_user_draft_queue(session, "Francisco Lindor")
        remove_player_from_user_draft_queue(session, "Aaron Judge")
        self.assertEqual(session[DRAFT_QUEUE_KEY], [])
        q, source = _resolve_visible_draft_queue(session, qkey=DRAFT_QUEUE_KEY)
        self.assertEqual(q, [])
        self.assertNotEqual(source, "_live_draft_queue_last_good")

    def test_reorder_shared_across_surfaces(self) -> None:
        session = self._session(["A", "B", "C"])
        reorder_user_draft_queue(session, ["C", "A", "B"])
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["C", "A", "B"])
        self.assertEqual((session.get("draft_state") or {}).get("queue"), ["C", "A", "B"])

    def test_no_arrows_in_any_view(self) -> None:
        session = self._session(["A", "B"])
        for prefix, sidebar, compact in (
            ("sidebar_queue", True, True),
            ("live_queue", False, False),
            ("sim_queue", False, False),
        ):
            st = _TrackingStreamlit()
            self._render(st, session, key_prefix=prefix, use_sidebar=sidebar, compact=compact)
            self.assertFalse(ARROW_LABELS.intersection(st.button_labels), prefix)

    def test_remove_does_not_clear_rec_cache(self) -> None:
        session = self._session(["A", "B"])
        with mock.patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            remove_player_from_user_draft_queue(session, "A")
            mock_save.assert_not_called()
        self.assertEqual(session[REC_CACHE_KEY]["key"], ("rec",))

    def test_stale_sortable_cannot_restore_removed_player(self) -> None:
        session = self._session(["A", "B", "C"])
        remove_player_from_user_draft_queue(session, "B")
        # Reorder rejects membership that includes removed B.
        q, changed = reorder_user_draft_queue(session, ["A", "B", "C"])
        self.assertFalse(changed)
        self.assertEqual(q, ["A", "C"])
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["A", "C"])

    def test_live_and_sim_sessions_isolated(self) -> None:
        live = self._session(["Live1", "Live2"])
        sim = {
            AUTH_USER_ID_KEY: "uuid-daniel",
            DRAFT_QUEUE_KEY: ["Sim1", "Sim2"],
            "draft_state": {"queue": ["Sim1", "Sim2"]},
        }
        remove_player_from_user_draft_queue(live, "Live1")
        self.assertEqual(live[DRAFT_QUEUE_KEY], ["Live2"])
        self.assertEqual(sim[DRAFT_QUEUE_KEY], ["Sim1", "Sim2"])

    def test_widget_epoch_bumps_on_remove(self) -> None:
        session = self._session(["A", "B"])
        self.assertEqual(int(session.get("_draft_queue_widget_epoch") or 0), 0)
        remove_player_from_user_draft_queue(session, "A")
        self.assertEqual(int(session.get("_draft_queue_widget_epoch") or 0), 1)


if __name__ == "__main__":
    unittest.main()
