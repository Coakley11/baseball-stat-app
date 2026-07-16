"""Auto-pick advancement chain diagnostics."""

from __future__ import annotations

import unittest

from live_draft_autopick_chain import (
    AUTOPICK_CHAIN_KEY,
    format_autopick_chain_banner,
    note_autopick_chain,
    reset_autopick_chain,
)


class AutopickChainTests(unittest.TestCase):
    def test_notes_stages_and_stop_point(self) -> None:
        session: dict = {}
        reset_autopick_chain(session, pick_index=2)
        note_autopick_chain(session, "timer_hit_zero", ok=True, pick_index=2)
        note_autopick_chain(
            session,
            "auto_pick_selected",
            ok=True,
            selected_player="Aaron Judge",
            pick_index=2,
        )
        note_autopick_chain(
            session,
            "auto_pick_applied",
            ok=False,
            error="shared commit failed",
            pick_index=2,
        )
        chain = session[AUTOPICK_CHAIN_KEY]
        self.assertEqual(chain["stopped_at"], "auto_pick_applied")
        self.assertIn("shared commit failed", str(chain["last_error"]))
        banner = format_autopick_chain_banner(session)
        self.assertIn("AUTOPICK CHAIN", banner)
        self.assertIn("Aaron Judge", banner)


if __name__ == "__main__":
    unittest.main()
