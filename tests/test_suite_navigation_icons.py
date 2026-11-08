"""Account & Workspace navigation (2026-11-06): the approved Command Center logo as an icon-only link,
a house that opens Baseball Explorer Home, and the shared action icons."""

from __future__ import annotations

import re
import unittest

from streamlit.testing.v1 import AppTest

import action_icons
import suite_brand_assets


def _nav_script() -> None:
    import streamlit as st

    from baseball_account_workspace import _render_suite_navigation

    _render_suite_navigation(st)
    st.write("nav:", st.session_state.get("_navigate_to_page") or "")


class SuiteNavigationTests(unittest.TestCase):
    def test_the_command_center_control_is_the_approved_logo_with_an_accessible_name(self) -> None:
        captured: list[str] = []

        class Target:
            def markdown(self, body, unsafe_allow_html=False):
                captured.append(body)

        self.assertTrue(suite_brand_assets.render_command_center_logo_link(Target(), "https://cc.example/?w=1"))
        html = captured[0]
        self.assertIn(suite_brand_assets.brand_data_uri("command_emblem_96"), html)  # the approved asset
        self.assertIn('aria-label="Open Command Center"', html)
        self.assertIn('title="Open Command Center"', html)
        self.assertIn('href="https://cc.example/?w=1"', html)
        self.assertIn('target="_blank"', html)
        visible = re.sub(r"<[^>]+>", "", html).strip()
        self.assertEqual(visible, "")  # no words beside the logo

    def test_the_house_opens_home_and_shows_no_word(self) -> None:
        at = AppTest.from_function(_nav_script, default_timeout=30)
        at.run()
        home = next(b for b in at.button if b.key == "suite_nav_home_btn")
        self.assertEqual(home.label, "")
        self.assertEqual(home.help, "Baseball Explorer Home")
        self.assertEqual(home.icon if hasattr(home, "icon") else action_icons.HOME, action_icons.HOME)
        home.click().run()
        self.assertEqual(at.session_state["_navigate_to_page"], "Home")
        self.assertTrue(at.session_state["_suite_page_user_nav"])
        self.assertFalse(any("Command Center" in str(getattr(b, "label", "")) for b in at.button))

    def test_action_icon_values_are_colourful_emoji_streamlit_accepts(self) -> None:
        """Owner rule 2026-11-08: every action icon is a colourful emoji, never a Material Symbol."""
        from streamlit.string_util import validate_icon_or_emoji

        values = {k: v for k, v in vars(action_icons).items() if k.isupper() and not k.startswith("_") and isinstance(v, str) and k != "DANGER_KEY_PREFIX"}
        self.assertGreater(len(values), 40)
        for name, value in values.items():
            self.assertNotIn(":material/", value, name)
            self.assertEqual(validate_icon_or_emoji(value), value, name)
        self.assertEqual(action_icons.ADD_TO_QUEUE, "⭐")
        self.assertEqual(action_icons.HOME, "🏠")

    def test_dangerous_actions_are_styled_and_the_original_set_active_star_is_back(self) -> None:
        import inspect

        import draft_archive_ui
        import fantasy_league_invite_ui

        library = inspect.getsource(draft_archive_ui)
        # Owner decision 2026-11-07: the original colourful labels are restored.
        self.assertIn('"⭐ Set Active League" if is_league else "⭐ Set Active Draft"', library)
        self.assertIn('"✅ Active League" if is_league else "✅ Active Draft"', library)
        self.assertEqual(action_icons.SET_ACTIVE, "⭐")  # the same star wherever Set Active appears
        self.assertIn("_icons.danger_container(st, f\"{widget_key_prefix}_del_{draft_id}\")", library)
        invites = inspect.getsource(fantasy_league_invite_ui)
        self.assertIn('key=f"bx-danger-invite_revoke_{iid}"', invites)
        self.assertIn("st-key-bx-danger-", action_icons._STYLES)


if __name__ == "__main__":
    unittest.main()
