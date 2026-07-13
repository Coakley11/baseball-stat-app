"""Quick guide must not render stray HTML closing tags."""

from __future__ import annotations

import inspect
import unittest


class PageGuideMarkupTests(unittest.TestCase):
    def test_render_page_guide_does_not_emit_literal_div_closer(self) -> None:
        import streamlit_app

        source = inspect.getsource(streamlit_app.render_page_guide)
        self.assertNotIn("</div>", source)
        self.assertIn("##### Quick guide", source)


if __name__ == "__main__":
    unittest.main()
