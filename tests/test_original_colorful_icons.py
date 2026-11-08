"""Owner decision 2026-11-07: the original colourful icons are back wherever the redesign
(6bb956e..264a951) replaced them with monochrome Material Symbols.

Pins, against the pre-redesign Dev revision 6442d8d:
- every page label (sidebar page list, page buttons, captions, phone picker and banner) is the
  feature's original emoji + name, with no ``:material/…:`` code;
- page keys and label -> page resolution are unchanged (including labels saved during the redesign);
- the Live Draft controls and the Saved Draft Library / completion buttons carry their original
  emoji in the label and no Material icon, with the same keys.
Icons the redesign added where no original existed are out of scope here (left for the owner).
"""

from __future__ import annotations

import inspect
import unittest

import feature_identity as fi
import mobile_nav_m2 as nav


def _app():
    import streamlit_app as app

    return app


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSt:
    def __init__(self):
        self.session_state: dict = {}
        self.markdown_calls: list[str] = []
        self.selectbox_calls: list[dict] = []

    def markdown(self, body, unsafe_allow_html=False):
        self.markdown_calls.append(str(body))

    def container(self, key=None):
        return _Ctx()

    def selectbox(self, label, options, *, index=0, format_func=None, key=None, on_change=None, label_visibility=None):
        self.selectbox_calls.append({"options": list(options), "format_func": format_func, "key": key})
        return options[index] if options else None


class PageLabelTests(unittest.TestCase):
    # The pre-redesign labels (6442d8d), one per page key.
    ORIGINAL = {
        "Home": "🏠 Home",
        "Historical Explorer": "🔎 Historical Explorer",
        "Career Totals": "📚 Career Totals",
        "Comparison Tool": "⚖️ Compare Players",
        "Leaderboards": "🏆 Leaderboards",
        "Trend Value": "🔥 Trend Value",
        "Valuation": "💰 Valuation",
        "ML Predictions": "🤖 ML Predictions",
        "Fantasy Sleepers & Busts": "💎 Sleepers & Busts",
        "Live Draft Room": "📡 Live Draft Room",
        "Draft Room Simulator": "🧾 Draft Room Simulator",
        "Draft Assistant Simulator": "🧩 Draft Assistant Simulator",
        "Draft Lab / Simulation": "🧪 Draft Lab / Simulation",
        "Saved Draft Library": "📁 Saved Draft Library",
        "Fantasy Standings Tracker": "📊 League Standings",
        "Fantasy Lineup Assistant": "📋 Lineup & Trades",
        "Waiver Wire / Add-Drop Center": "🔄 Waiver Wire",
        "Pricing & Upgrade": "💳 Pricing & Upgrade",
    }

    def test_page_labels_are_the_original_emoji_labels(self) -> None:
        app = _app()
        for page, label in self.ORIGINAL.items():
            self.assertEqual(app.page_option_label(page), label, page)
            self.assertEqual(app.get_sidebar_page_label(page), label, page)
        # Added after 6442d8d with its own emoji from the start (nav_groups / feature_identity).
        self.assertEqual(app.page_option_label("Draft Strategy Assistant"), "♟️ Draft Strategy · PRO")
        for page in app.PAGE_OPTIONS:
            self.assertNotIn(":material/", app.page_option_label(page), page)

    def test_page_keys_and_label_resolution_are_unchanged(self) -> None:
        app = _app()
        self.assertEqual(set(app.PAGE_OPTIONS), set(self.ORIGINAL) | {"Draft Strategy Assistant"})
        for page in app.PAGE_OPTIONS:
            self.assertEqual(app.normalize_page_key(page), page)
            self.assertEqual(app.normalize_page_key(app.page_option_label(page)), page)
            self.assertEqual(app.get_sidebar_page_value(page), page)
        # Labels a session could have saved while the redesign was live still open their page.
        self.assertEqual(app.normalize_page_key(":material/home: Home"), "Home")
        self.assertEqual(app.normalize_page_key(":material/folder_open: Saved Draft Library"), "Saved Draft Library")

    def test_phone_picker_and_current_page_banner_keep_the_emoji(self) -> None:
        app = _app()
        st = _FakeSt()
        nav.render_mobile_quick_nav(
            st,
            active_page="Live Draft Room",
            page_options=["Historical Explorer", "Live Draft Room", "Saved Draft Library"],
            page_option_label=app.page_option_label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: None,
        )
        self.assertTrue(any("📡 Live Draft Room</nav>" in m for m in st.markdown_calls))
        fmt = st.selectbox_calls[0]["format_func"]
        self.assertEqual(fmt("Saved Draft Library"), "📁 Saved Draft Library")
        self.assertEqual(st.selectbox_calls[0]["key"], nav.QUICK_NAV_SELECT_KEY)

    def test_feature_registry_still_holds_the_original_emoji(self) -> None:
        for page, label in self.ORIGINAL.items():
            feat = fi.feature(page)
            self.assertEqual(f"{feat.icon} {feat.name}", label, page)


class ActionButtonTests(unittest.TestCase):
    def test_live_draft_controls_have_their_original_emoji(self) -> None:
        import live_draft_control_center_ui as cc

        src = inspect.getsource(cc.render_live_draft_control_center)
        for label, key in (
            ("⏸ Pause Draft", "live_draft_pause"),
            ("▶ Resume Draft", "live_draft_resume"),
            ("⚡ Auto Pick Now", "live_draft_auto_now"),
            ("🚪 Leave Room", "live_draft_leave_this_room_btn"),
            ("⏱ Reset Timer", None),
        ):
            self.assertIn(f'"{label}"', src)
            if key:
                self.assertIn(f'key="{key}"', src)
        for code in (":material/pause:", ":material/play_arrow:", ":material/bolt:", ":material/logout:"):
            self.assertNotIn(code, src)

    def test_saved_draft_library_and_completion_labels_have_their_original_emoji(self) -> None:
        import draft_archive_ui as lib

        src = inspect.getsource(lib)
        for text in (
            '"⭐ Set Active League",',
            '"⭐ Set Active League" if is_league else "⭐ Set Active Draft"',
            '"✅ Active League" if is_league else "✅ Active Draft"',
            '"📁 Save to Draft Library",',
            'f"⭐ Set Active: {answer[\'recent_name\']}"',
            "Use **⭐ Set Active League** on the correct saved draft below.",
            "use **⭐ Set Active League** to manage this league.",
        ):
            self.assertIn(text, src)
        self.assertNotIn("_icons.SET_ACTIVE", src)
        save = inspect.getsource(lib.render_live_draft_completion_panel)
        self.assertIn('key=f"{key_prefix}_save_btn",', save)
        self.assertNotIn("icon=_icons.SAVE", save)


if __name__ == "__main__":
    unittest.main()
