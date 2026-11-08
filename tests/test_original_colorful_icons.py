"""Owner decision 2026-11-07: the original colourful icons are back wherever the redesign
(6bb956e..264a951) replaced them with monochrome Material Symbols.

Pins, against the pre-redesign Dev revision 6442d8d:
- every page label (sidebar page list, page buttons, captions, phone picker and banner) is the
  feature's original emoji + name, with no ``:material/…:`` code;
- page keys and label -> page resolution are unchanged (including labels saved during the redesign);
- the Live Draft controls and the Saved Draft Library / completion buttons carry their original
  emoji in the label and no Material icon, with the same keys.
Second pass (owner rule 2026-11-08): every important action carries a colourful emoji from one
mapping (action_icons), the same icon for the same action everywhere, and no Material Symbol remains.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

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
        import action_icons

        self.assertEqual(action_icons.SET_ACTIVE, "⭐")  # any icon= Set Active shows the same star
        save = inspect.getsource(lib.render_live_draft_completion_panel)
        self.assertIn('key=f"{key_prefix}_save_btn",', save)
        self.assertNotIn("icon=_icons.SAVE", save)  # its 📁 is in the label


# --- second pass (owner rule 2026-11-08): every important action has a colourful icon -------------

ROOT = Path(__file__).resolve().parents[1]
_WIDGETS = {"button", "form_submit_button", "link_button", "download_button", "popover", "expander"}


def _widget_icons(filename: str) -> dict[str, list[str]]:
    """{first-argument label (or <expr>): [resolved icon, ...]} for every widget call in a module."""
    import action_icons

    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _WIDGETS):
            continue
        arg = node.args[0] if node.args else None
        if isinstance(arg, ast.Constant):
            label = str(arg.value)
        else:
            label = "<" + (ast.unparse(arg) if arg is not None else "") + ">"
        icon = next((k.value for k in node.keywords if k.arg == "icon"), None)
        if icon is None:
            value = ""
        elif isinstance(icon, ast.Constant):
            value = str(icon.value)
        else:
            try:
                value = str(eval(ast.unparse(icon), {"_icons": action_icons}))  # noqa: S307 - our own source
            except Exception:
                value = "<" + ast.unparse(icon) + ">"
        out.setdefault(label, []).append(value)
    return out


class OwnerNamedActionTests(unittest.TestCase):
    def test_the_owner_named_icons(self) -> None:
        import action_icons as icons

        self.assertEqual(icons.ADD_TO_QUEUE, "⭐")
        self.assertEqual(icons.COMPARE, "⚖️")
        self.assertEqual(icons.TREND, "🔥")
        self.assertEqual(icons.DRAFT_PLAYER, "🔴")
        self.assertEqual(icons.HOME, "🏠")
        for name in ("WATCHLIST", "IMPORT", "ROSTER", "SETTINGS", "SIMULATE_PICK", "STRATEGY", "SAVE", "OPEN"):
            self.assertNotIn(":material/", getattr(icons, name), name)

    def test_player_actions_menu(self) -> None:
        import action_icons as icons

        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        table = next(
            n for n in ast.parse(src).body
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_PLAYER_ACTION_ICONS" for t in n.targets)
        )
        mapping = eval(ast.unparse(table.value), {"_icons": icons})  # noqa: S307 - our own source
        self.assertEqual(mapping["add_draft_queue"], "⭐")
        self.assertEqual(mapping["add_watchlist"], icons.WATCHLIST)
        self.assertEqual(mapping["draft_player"], "🔴")
        # Compare / Trend buttons carry their page label, which opens with the original emoji.
        self.assertIn('(page_option_label("Comparison Tool"), "Send to Comparison Tool", "send_comparison")', src)
        self.assertIn('(page_option_label("Trend Value"), "Send to Trend Page", "send_trends")', src)
        app = _widget_icons("streamlit_app.py")
        self.assertEqual(app["Simulate Draft Pick"], [icons.SIMULATE_PICK] * 2)
        self.assertEqual(app["Projection breakdown"], [icons.PROJECTION] * 2)
        self.assertEqual(app["<label>"].count("<_PLAYER_ACTION_ICONS.get(slug)>"), 6)

    def test_compare_and_trend_are_the_same_icons_everywhere(self) -> None:
        import action_icons as icons

        waiver = _widget_icons("fantasy_waiver_wire_ui.py")
        self.assertEqual(waiver["Compare"], ["⚖️"])
        self.assertEqual(waiver["See trend"], ["🔥"])
        self.assertEqual(icons.COMPARE, fi.feature("Comparison Tool").icon)
        self.assertEqual(icons.TREND, fi.feature("Trend Value").icon)

    def test_draft_room_simulator_sections(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn(
            'st.tabs([f"{_icons.BOARD} Board", f"{_icons.ROSTER} Rosters & grades", f"{_icons.SETTINGS} League setup"])',
            src,
        )
        app = _widget_icons("streamlit_app.py")
        self.assertEqual(app["Import existing draft"], ["📥"])
        self.assertEqual(app["Import Draft"], ["📥"])
        self.assertEqual(app["Draft Player"], ["🔴"])  # the board's Draft Player popover
        self.assertEqual(app["Save Draft Board Now"], ["💾"])
        self.assertEqual(app["Run 4-Team Draft Simulation"], ["🧪"])
        self.assertEqual(app["Set player on pick"], ["🔴"])

    def test_every_draft_pick_button_uses_the_one_draft_icon(self) -> None:
        draft_ui = _widget_icons("draft_ui.py")
        self.assertEqual(draft_ui["Draft Player"], ["🔴"] * 4)
        self.assertEqual(draft_ui["<label>"].count("<draft_icon>"), 3)  # render_draft_button: 🔴 unless the label has it
        self.assertIn("draft_icon = None if str(label).startswith(_icons.DRAFT_PLAYER) else _icons.DRAFT_PLAYER",
                      (ROOT / "draft_ui.py").read_text(encoding="utf-8"))
        self.assertIn('btn_label = "🔴 Draft Player"', (ROOT / "live_draft_room_ui.py").read_text(encoding="utf-8"))

    def test_add_to_queue_is_the_gold_star_everywhere(self) -> None:
        self.assertEqual(_widget_icons("draft_strategy_ui.py")["Add to Queue"], ["⭐"])
        self.assertEqual(_widget_icons("draft_queue_panel.py")["Add"], ["⭐"])
        self.assertEqual(_widget_icons("live_draft_room_ui.py")["Queued"], ["⭐"])
        for name in ("draft_ui.py", "live_draft_room_ui.py"):
            self.assertIn('"⭐ Add to Queue",', (ROOT / name).read_text(encoding="utf-8"), name)

    def test_no_material_symbols_remain_on_actions(self) -> None:
        """No widget passes a :material/…: icon; only the legacy read-back table spells one."""
        allow = {
            "feature_identity.py": "legacy page labels read back to their page, never shown",
            "streamlit_app.py": "one comment naming the legacy labels",
        }
        for path in sorted(ROOT.glob("*.py")):
            if path.name.startswith("Old"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if ":material/" not in text:
                continue
            self.assertIn(path.name, allow, path.name)
            for icons in _widget_icons(path.name).values():
                for icon in icons:
                    self.assertFalse(icon.startswith(":material/"), (path.name, icon))
        app_lines = (ROOT / "streamlit_app.py").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(":material/" in line for line in app_lines), 1)

    def test_widget_icons_are_valid_streamlit_icons(self) -> None:
        from streamlit.string_util import validate_icon_or_emoji

        for name in ("streamlit_app.py", "draft_ui.py", "draft_archive_ui.py", "draft_strategy_ui.py",
                     "draft_queue_panel.py", "fantasy_waiver_wire_ui.py", "fantasy_trade_center_ui.py",
                     "live_draft_setup_ui.py", "suite_auth.py", "live_draft_control_center_ui.py", "ui_confirm.py"):
            for label, icons in _widget_icons(name).items():
                for icon in icons:
                    if icon and not icon.startswith("<"):
                        self.assertEqual(validate_icon_or_emoji(icon), icon, (name, label))


if __name__ == "__main__":
    unittest.main()
