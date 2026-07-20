"""Rendered AppTest: Solo Live Draft components share canonical pick/team/revision."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "solo_live_draft_canonical_apptest.py"


class SoloLiveDraftCanonicalAppTest(unittest.TestCase):
    def test_rendered_components_agree_then_ten_expires_advance(self) -> None:
        from streamlit.testing.v1 import AppTest

        from live_draft_pick_commit import PickCommitResult

        def _fast_score(available, roster_df, rule_key, target_counts, config=None):
            scored = available.copy()
            if "Decision Score" not in scored.columns:
                scored["Decision Score"] = range(len(scored), 0, -1)
            return scored.sort_values("Decision Score", ascending=False), []

        at = AppTest.from_file(str(_FIXTURE), default_timeout=60)
        with patch("live_draft_autopick.score_available_for_rule", side_effect=_fast_score):
            with patch(
                "live_draft_pick_commit.persist_applied_pick",
                return_value=PickCommitResult(
                    ok=True,
                    message="ok",
                    error="",
                    commit_path="apptest",
                    board_size_before=0,
                    board_size_after=0,
                    current_pick_index_before=0,
                    current_pick_index_after=0,
                ),
            ):
                at.run()
                self.assertFalse(at.exception)

                # Initial paint: sidebar context caption matches canonical caption.
                captions = [c.value for c in at.caption]
                markdowns = [m.value for m in at.markdown]
                joined = "\n".join(str(x) for x in captions + markdowns)
                self.assertIn("team=Team A", joined)
                self.assertIn("pick=1", joined)

                room = at.session_state["live_draft_room"]
                self.assertEqual(int(room.get("current_pick_index") or 0), 0)

                expire_btn = [b for b in at.button if b.key == "solo_force_expire_btn"]
                self.assertTrue(expire_btn)

                seen = []
                for n in range(1, 11):
                    expire_btn = [b for b in at.button if b.key == "solo_force_expire_btn"]
                    expire_btn[0].click().run()
                    self.assertFalse(at.exception, f"exception on expire {n}")
                    room = at.session_state["live_draft_room"]
                    board = list(room.get("draft_board") or [])
                    self.assertEqual(len(board), n, f"expected {n} picks, got {len(board)}")
                    pid = str(board[-1].get("playerID") or "")
                    self.assertNotIn(pid, seen)
                    seen.append(pid)
                    self.assertIn("_last_expire_ok", at.session_state)
                    self.assertTrue(at.session_state["_last_expire_ok"])
                    self.assertEqual(int(at.session_state["_last_expire_committed"] or 0), n)

                    if n < 10:
                        self.assertEqual(str(room.get("status") or ""), "in_progress")
                        self.assertEqual(int(room.get("current_pick_index") or -1), n)
                        # Captions after rerun still agree on team + pick index.
                        captions = [c.value for c in at.caption]
                        markdowns = [m.value for m in at.markdown]
                        joined = "\n".join(str(x) for x in captions + markdowns)
                        self.assertIn(f"idx={n}", joined)
                    else:
                        self.assertEqual(str(room.get("status") or ""), "complete")

                self.assertEqual(len(seen), 10)
                self.assertEqual(len(set(seen)), 10)


if __name__ == "__main__":
    unittest.main()
