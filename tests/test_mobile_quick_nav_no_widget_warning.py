"""D4J log 2026-11-22 13:48 UTC (mobile_nav_m2.py line 214): Streamlit warned that the widget with key
_mobile_quick_nav_select was created with a default value but also had its value set via the Session State API.

Streamlit raises that warning from ``check_session_state_rules`` when a keyed widget passes a default
(for ``st.selectbox``: any ``index`` above 0) while its Session State value was set this run. It logs it once
per process, so the test records what real Streamlit's selectbox passes to the policy check (AppTest).
"""

from __future__ import annotations

import unittest
from unittest import mock

from streamlit.elements.widgets import selectbox as st_selectbox
from streamlit.testing.v1 import AppTest

KEY = "_mobile_quick_nav_select"
_SCRIPT = '''
import streamlit as st
from mobile_nav_m2 import render_mobile_quick_nav

st.session_state.setdefault("main_sidebar_page", "Leaderboards")
render_mobile_quick_nav(
    st,
    active_page=st.session_state["main_sidebar_page"],
    page_options=["Historical Explorer", "Leaderboards", "Trend Value", "Live Draft Room"],
    page_option_label=lambda p: p,
    main_sidebar_page_key="main_sidebar_page",
    on_sidebar_page_change=lambda: None,
)
'''


class QuickNavWidgetWarningTests(unittest.TestCase):
    def test_quick_nav_selectbox_never_passes_a_default_with_its_session_value(self) -> None:
        seen: list[object] = []
        real = st_selectbox.check_widget_policies

        def spy(dg, key, on_change=None, *, default_value=None, **kw):
            if key == KEY:
                seen.append(default_value)
            return real(dg, key, on_change, default_value=default_value, **kw)

        with mock.patch.object(st_selectbox, "check_widget_policies", side_effect=spy):
            at = AppTest.from_string(_SCRIPT, default_timeout=60)
            at.run()  # Leaderboards is the 2nd page of its section: index 1 used to be passed as the default
            at.session_state["main_sidebar_page"] = "Trend Value"
            at.run()
        self.assertFalse(at.exception)
        self.assertTrue(seen)
        self.assertEqual(set(seen), {None})
        self.assertEqual(at.selectbox(key=KEY).value, "Trend Value")


if __name__ == "__main__":
    unittest.main()
