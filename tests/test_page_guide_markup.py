"""Quick guide must not render stray HTML closing tags."""

from __future__ import annotations

import html
import unittest
from unittest import mock


class PageGuideMarkupTests(unittest.TestCase):
    def test_quick_guide_card_is_balanced_html(self) -> None:
        """M2: card is a <details>/<summary> disclosure (collapsible on phones,
        always-visible on desktop via CSS — see page_quick_guide._QUICK_GUIDE_CSS)
        wrapped by a single leading <style> tag, still one st.markdown() call."""
        from page_quick_guide import render_quick_guide_card

        st = mock.MagicMock()
        render_quick_guide_card(
            st,
            what_it_does="Compare players",
            when_to_use="Before drafting",
            main_outputs="Ranked table",
            tips=["Use filters"],
        )
        st.markdown.assert_called_once()
        card_html = st.markdown.call_args[0][0]
        self.assertTrue(card_html.startswith("<style>"))
        self.assertIn("</style><details", card_html)
        self.assertTrue(card_html.endswith("</div></details>"))
        self.assertNotIn("</div></div></div>", card_html)
        self.assertEqual(card_html.count("<div"), card_html.count("</div"))
        self.assertEqual(card_html.count("<details"), card_html.count("</details"))
        self.assertIn(html.escape("Compare players"), card_html)

    def test_quick_guide_card_collapses_on_phones_not_desktop(self) -> None:
        """The disclosure has no `open` attribute (closed by default — the phone
        behavior) and desktop is forced back to always-visible via CSS, matching
        pre-M2 presentation exactly at >640px."""
        from mobile_foundation import PHONE_MAX_PX
        from page_quick_guide import render_quick_guide_card

        st = mock.MagicMock()
        render_quick_guide_card(
            st, what_it_does="x", when_to_use="y", main_outputs="z"
        )
        card_html = st.markdown.call_args[0][0]
        self.assertNotIn("<details open", card_html)
        self.assertIn(f"min-width: {PHONE_MAX_PX + 1}px", card_html)
        self.assertIn("display: block !important", card_html)

    def test_render_page_guide_uses_quick_guide_card(self) -> None:
        from pathlib import Path

        source = Path(__file__).resolve().parents[1].joinpath("streamlit_app.py").read_text(encoding="utf-8")
        start = source.index("def render_page_guide")
        block = source[start : start + 1200]
        self.assertIn("render_quick_guide_card", block)
        self.assertIn("page_quick_guide", block)


if __name__ == "__main__":
    unittest.main()
