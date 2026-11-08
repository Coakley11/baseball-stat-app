"""End/Delete Draft for Everyone looked like an ordinary blue primary button (owner review, 2026-11-08).

It is destructive and permanent, so both steps are red: the first button has red text and border, and the
final "Confirm End/Delete" (shown after the warning) is solid red. Authorization, the confirmation step and
the deletion itself are unchanged.
"""

import re
import unittest
from pathlib import Path

import action_icons

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "live_draft_control_center_ui.py").read_text(encoding="utf-8")


def _block_before(key: str, span: int = 500) -> str:
    i = SRC.index(f'    key="{key}"')  # the button itself, not a trace's widget_key=
    return SRC[max(0, i - span):i + 200]


class DeleteButtonStyleTests(unittest.TestCase):
    def test_the_first_button_is_red_and_not_the_blue_primary(self) -> None:
        block = _block_before("live_draft_discard_btn")
        self.assertIn('_icons.danger_container(st, "live_draft_discard")', block)
        self.assertRegex(block, r'key="live_draft_discard_btn",\s*type="secondary"')

    def test_the_confirmation_is_solid_red(self) -> None:
        block = _block_before("live_draft_discard_confirm_btn")
        self.assertIn('_icons.danger_container(st, "live_draft_discard_confirm")', block)
        css = action_icons._STYLES
        self.assertTrue(re.search(r'st-key-bx-danger-"\] button\[kind="primary"\][^{]*\{\s*background: #b91c1c', css))

    def test_confirmation_and_authorization_are_unchanged(self) -> None:
        self.assertIn("on_click=on_show_end_delete_confirm", SRC)
        self.assertIn("on_click=on_confirm_end_delete_for_everyone", SRC)
        self.assertIn("Permanently delete this draft for every participant?", SRC)
        self.assertIn('"Keep Draft"', SRC)


if __name__ == "__main__":
    unittest.main()
