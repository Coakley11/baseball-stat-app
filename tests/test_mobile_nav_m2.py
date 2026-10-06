"""Mobile M2 — quick-nav grouping, widget-sync, and callback-routing contract."""

from __future__ import annotations

import unittest
from pathlib import Path

import mobile_nav_m2 as nav

ROOT = Path(__file__).resolve().parents[1]


class _FakeContainer:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSt:
    def __init__(self, session_state=None):
        self.session_state = session_state if session_state is not None else {}
        self.markdown_calls = []
        self.selectbox_calls = []
        self.container_keys = []

    def markdown(self, body, unsafe_allow_html=False):
        self.markdown_calls.append(body)

    def container(self, key=None):
        self.container_keys.append(key)
        return _FakeContainer()

    def selectbox(self, label, options, *, index=0, format_func=None, key=None, on_change=None, label_visibility=None):
        self.selectbox_calls.append(
            {
                "label": label,
                "options": list(options),
                "index": index,
                "format_func": format_func,
                "key": key,
                "on_change": on_change,
            }
        )
        return options[index] if options else None


def live_page_options() -> list[str]:
    """Read PAGE_OPTIONS from source instead of importing streamlit_app.

    Mobile M7 (determinism): ``import streamlit_app`` executes the whole app
    script. In a bare pytest process that succeeds on its own but can fail when
    an earlier test in the same run has already touched Streamlit's session
    state — these three tests were the M1–M6 suite's only order-dependent mobile
    failures. The contract being tested is a module-level list literal, so
    reading it statically tests exactly the same thing, deterministically (and
    much faster).
    """
    import ast

    tree = ast.parse((ROOT / "streamlit_app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PAGE_OPTIONS" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError("PAGE_OPTIONS not found as a module-level literal in streamlit_app.py")


class PageGroupCoverageTests(unittest.TestCase):
    def test_every_live_page_option_has_a_group(self) -> None:
        """Pulls the real PAGE_OPTIONS list so a newly added page that forgets
        to register a mobile-nav group fails this test immediately."""
        missing = [p for p in live_page_options() if p not in nav.PAGE_GROUPS]
        self.assertEqual(missing, [], f"pages missing from mobile PAGE_GROUPS: {missing}")

    def test_no_stale_groups_for_removed_pages(self) -> None:
        options = live_page_options()
        stale = [p for p in nav.PAGE_GROUPS if p not in options]
        self.assertEqual(stale, [], f"mobile PAGE_GROUPS references removed pages: {stale}")

    def test_page_options_source_read_matches_the_imported_module(self) -> None:
        """Guards the static read itself: if PAGE_OPTIONS ever stops being a
        module-level literal, this fails loudly instead of silently testing
        stale data."""
        import streamlit_app as app

        self.assertEqual(live_page_options(), list(app.PAGE_OPTIONS))

    def test_grouped_page_options_preserves_every_page_reorders_by_group(self) -> None:
        options = live_page_options()
        ordered = nav.grouped_page_options(options)
        self.assertEqual(set(ordered), set(options))
        self.assertEqual(len(ordered), len(options))
        # Group order fixed, e.g. Live Draft Room must sit after every
        # "Explore & Analyze" page and before every "Fantasy Team" page.
        i_live = ordered.index("Live Draft Room")
        i_explore_last = max(ordered.index(p) for p, g in nav.PAGE_GROUPS.items() if g == "Explore & Analyze")
        i_team_first = min(ordered.index(p) for p, g in nav.PAGE_GROUPS.items() if g == "Fantasy Team")
        self.assertLess(i_explore_last, i_live)
        self.assertLess(i_live, i_team_first)

    def test_unmapped_page_is_appended_not_dropped(self) -> None:
        ordered = nav.grouped_page_options(["Historical Explorer", "Some New Page"])
        self.assertIn("Some New Page", ordered)
        self.assertEqual(ordered[-1], "Some New Page")


class RenderMobileQuickNavTests(unittest.TestCase):
    def _label(self, page: str) -> str:
        return f"[{page}]"

    def test_renders_current_page_and_selectbox_scoped_to_root_key(self) -> None:
        st = _FakeSt()
        calls = []
        nav.render_mobile_quick_nav(
            st,
            active_page="Live Draft Room",
            page_options=["Historical Explorer", "Live Draft Room", "Fantasy Standings Tracker"],
            page_option_label=self._label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: calls.append("changed"),
        )
        self.assertIn(nav.QUICK_NAV_ROOT_KEY, st.container_keys)
        self.assertEqual(len(st.selectbox_calls), 1)
        sb = st.selectbox_calls[0]
        self.assertEqual(sb["key"], nav.QUICK_NAV_SELECT_KEY)
        # Current page banner shows the resolved label somewhere in the markdown.
        self.assertTrue(any("[Live Draft Room]" in m for m in st.markdown_calls))

    def test_quick_nav_is_a_single_page_element_styles_inside_container(self) -> None:
        """M3 regression: a separate style-only st.markdown plus a hidden-but-present
        layout wrapper each cost a 16px flex gap on EVERY desktop page. Styles now ride
        inside the keyed container's label markdown — one hidden item on desktop."""
        src = (ROOT / "mobile_nav_m2.py").read_text(encoding="utf-8")
        body = src[src.index("def render_mobile_quick_nav"):]
        before_container = body[: body.index("with st.container(key=QUICK_NAV_ROOT_KEY)")]
        self.assertNotIn("st.markdown(", before_container)
        st = _FakeSt()
        nav.render_mobile_quick_nav(
            st,
            active_page="Live Draft Room",
            page_options=["Historical Explorer", "Live Draft Room"],
            page_option_label=self._label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: None,
        )
        self.assertEqual(len(st.markdown_calls), 1)
        md = st.markdown_calls[0]
        self.assertTrue(md.startswith("<style>"))
        self.assertIn("</style>\n<style>", md)  # each style block on its own line
        # M7: the label element became a <nav> landmark; the "own line" contract
        # (what this test is really pinning) is unchanged.
        self.assertIn('</style>\n<nav class="m-quick-nav-current"', md)

    def test_quick_nav_exposes_a_navigation_landmark(self) -> None:
        """M7 (a11y): the app exposes no <nav> landmark otherwise, so the phone page
        switcher is the one place a screen-reader user can reliably jump to."""
        st = _FakeSt()
        nav.render_mobile_quick_nav(
            st,
            active_page="Live Draft Room",
            page_options=["Historical Explorer", "Live Draft Room"],
            page_option_label=self._label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: None,
        )
        md = st.markdown_calls[0]
        self.assertIn('<nav class="m-quick-nav-current" aria-label="Current page">', md)
        self.assertIn('<span aria-hidden="true">', md)  # decorative pin not announced
        self.assertIn("</nav>", md)
        # The select keeps its accessible name even though the label is collapsed.
        self.assertEqual(st.selectbox_calls[0]["label"], "Jump to page")

    def test_selectbox_state_syncs_to_active_page_each_rerun(self) -> None:
        """Regression: without this sync, navigating via the sidebar/deep-link
        would leave the quick-nav selectbox showing a stale prior page, because
        Streamlit widgets prefer session_state[key] over `index=` once set."""
        st = _FakeSt(session_state={nav.QUICK_NAV_SELECT_KEY: "Historical Explorer"})
        nav.render_mobile_quick_nav(
            st,
            active_page="Fantasy Standings Tracker",
            page_options=["Historical Explorer", "Fantasy Standings Tracker"],
            page_option_label=self._label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: None,
        )
        self.assertEqual(st.session_state[nav.QUICK_NAV_SELECT_KEY], "Fantasy Standings Tracker")

    def test_on_change_routes_through_sidebar_page_key_not_a_parallel_state(self) -> None:
        """Picking a new page in the quick-nav must behave exactly like an
        ordinary sidebar click: write MAIN_SIDEBAR_PAGE_KEY then call the SAME
        on_sidebar_page_change callback the real radio uses — no new precedence
        machinery for baseball_persistent_state to reconcile."""
        st = _FakeSt(session_state={"main_sidebar_page": "Historical Explorer"})
        called = []
        nav.render_mobile_quick_nav(
            st,
            active_page="Historical Explorer",
            page_options=["Historical Explorer", "Live Draft Room"],
            page_option_label=self._label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: called.append(st.session_state.get("main_sidebar_page")),
        )
        on_change = st.selectbox_calls[0]["on_change"]
        st.session_state[nav.QUICK_NAV_SELECT_KEY] = "Live Draft Room"
        on_change()
        self.assertEqual(st.session_state["main_sidebar_page"], "Live Draft Room")
        self.assertEqual(called, ["Live Draft Room"])

    def test_on_change_is_noop_when_reselecting_current_page(self) -> None:
        st = _FakeSt(session_state={"main_sidebar_page": "Historical Explorer"})
        called = []
        nav.render_mobile_quick_nav(
            st,
            active_page="Historical Explorer",
            page_options=["Historical Explorer", "Live Draft Room"],
            page_option_label=self._label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: called.append(True),
        )
        on_change = st.selectbox_calls[0]["on_change"]
        st.session_state[nav.QUICK_NAV_SELECT_KEY] = "Historical Explorer"
        on_change()
        self.assertEqual(called, [])

    def test_unknown_active_page_falls_back_to_first_option_without_raising(self) -> None:
        st = _FakeSt()
        nav.render_mobile_quick_nav(
            st,
            active_page="Not A Real Page",
            page_options=["Historical Explorer", "Live Draft Room"],
            page_option_label=self._label,
            main_sidebar_page_key="main_sidebar_page",
            on_sidebar_page_change=lambda: None,
        )
        self.assertEqual(st.selectbox_calls[0]["index"], 0)


class CssScopingTests(unittest.TestCase):
    def test_quick_nav_hidden_above_phone_breakpoint(self) -> None:
        css = nav._quick_nav_css()
        desktop = css.split(f"@media (min-width: {nav.PHONE_MAX_PX + 1}px)", 1)[1].split("@media", 1)[0]
        self.assertIn(f".st-key-{nav.QUICK_NAV_ROOT_KEY}", desktop)
        self.assertIn("display: none", desktop)
        self.assertIn(f"max-width: {nav.PHONE_MAX_PX}px", css)

    def test_quick_nav_keeps_native_flex_layout_on_phone(self) -> None:
        """M3 regression: forcing ``display: block`` on the keyed stVerticalBlock collapsed
        the label's element container (~7px) so the selectbox overlapped the label —
        observed live on Live Draft at 390px. Phone rules must not override display."""
        css = nav._quick_nav_css()
        phone = css.split(f"@media (max-width: {nav.PHONE_MAX_PX}px)", 1)[1]
        self.assertNotIn("display: block", phone)
        self.assertNotIn("display:block", phone)

    def test_hero_subtitle_hidden_only_on_phone(self) -> None:
        css = nav.mobile_header_compaction_css()
        self.assertIn(".title-box .subtitle-text", css)
        self.assertIn(f"max-width: {nav.PHONE_MAX_PX}px", css)
        # Must not blanket-hide the subtitle outside the phone media query.
        before_media = css.split("@media", 1)[0]
        self.assertNotIn("subtitle-text", before_media)


class AppWiringTests(unittest.TestCase):
    def test_render_global_app_chrome_calls_quick_nav_first(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        start = src.index("def render_global_app_chrome(active_page: str)")
        end = src.index("def fmt_int(x):")
        block = src[start:end]
        self.assertIn("render_mobile_quick_nav", block)
        # Must run before the hero markup so it lands at the very top on phones.
        self.assertLess(block.index("render_mobile_quick_nav"), block.index("title-box"))

    def test_quick_nav_failure_never_blocks_page_body(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        start = src.index("def render_global_app_chrome(active_page: str)")
        block = src[start : start + 600]
        self.assertIn("except Exception:", block)


if __name__ == "__main__":
    unittest.main()
