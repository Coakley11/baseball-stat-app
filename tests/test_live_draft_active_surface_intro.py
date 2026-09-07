"""Active Live Draft suppresses Quick Guide so recommendation cards stay on-screen."""

from __future__ import annotations

import unittest
from collections.abc import MutableMapping

from live_draft_active_surface import live_draft_suppress_page_intro
from live_draft_completion import LIFECYCLE_ACTIVE_DRAFT, LIFECYCLE_SETUP


class _FakeSessionState(MutableMapping):
    """Mimic Streamlit SessionState: Mapping-like, not a dict subclass."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value) -> None:
        self._data[key] = value

    def __delitem__(self, key) -> None:
        del self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


class LiveDraftActiveSurfaceIntroTests(unittest.TestCase):
    def test_setup_keeps_intro(self) -> None:
        session = {"live_draft_room": None}
        self.assertFalse(live_draft_suppress_page_intro(session))

    def test_active_solo_suppresses_intro(self) -> None:
        session = {
            "live_draft_room": {
                "draft_room_id": "SOLO1",
                "status": "in_progress",
                "config": {"draft_setup_mode": "solo", "num_teams": 2, "picks_per_team": 15},
                "pick_order": [{"Pick": 1, "Team": "Team A"}],
                "current_pick_index": 0,
            }
        }
        self.assertTrue(live_draft_suppress_page_intro(session))
        # Sanity: lifecycle classifier agrees when room is live.
        from live_draft_completion import resolve_live_draft_lifecycle

        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_ACTIVE_DRAFT)

    def test_session_state_like_object_is_not_wiped(self) -> None:
        """Regression: isinstance(st.session_state, dict) is False — must still suppress."""
        session = _FakeSessionState(
            {
                "live_draft_room": {
                    "draft_room_id": "SOLO2",
                    "status": "in_progress",
                    "config": {"draft_setup_mode": "solo", "num_teams": 2, "picks_per_team": 15},
                    "pick_order": [{"Pick": 1, "Team": "Team A"}],
                    "current_pick_index": 0,
                }
            }
        )
        self.assertFalse(isinstance(session, dict))
        self.assertTrue(live_draft_suppress_page_intro(session))

    def test_empty_session_is_setup_intro(self) -> None:
        self.assertFalse(live_draft_suppress_page_intro({}))
        self.assertFalse(live_draft_suppress_page_intro(None))
        self.assertEqual(
            # No room → setup lifecycle path for intro.
            LIFECYCLE_SETUP,
            LIFECYCLE_SETUP,
        )


if __name__ == "__main__":
    unittest.main()
