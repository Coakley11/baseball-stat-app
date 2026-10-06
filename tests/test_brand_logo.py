"""Baseball brand logo: one hero placement plus the compact sidebar mark, nothing else.

Browser checks at 360/390/430/1280 confirm the logo loads at a 1.00 aspect ratio
with no page overflow; these tests pin the structure that makes that true and
keep the logo from spreading to other surfaces.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
BRAND = ROOT / "static" / "brand"


class BrandAssetTests(unittest.TestCase):
    def test_assets_exist_and_are_square(self) -> None:
        from PIL import Image

        for name, px in (("dcbe_logo_512.png", 512), ("dcbe_logo_128.png", 128)):
            path = BRAND / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(Image.open(path).size, (px, px), name)

    def test_display_asset_is_small_enough_to_ship_on_every_page(self) -> None:
        self.assertLess((BRAND / "dcbe_logo_128.png").stat().st_size, 64 * 1024)

    def test_served_by_static_serving(self) -> None:
        config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        self.assertRegex(config, r"enableStaticServing\s*=\s*true")


class HeroPlacementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.titles = re.findall(r'<div class="title-text"[^>]*>.*?</div>', APP)

    def test_both_hero_variants_carry_the_logo(self) -> None:
        """Full hero and the compact draft-page hero."""
        self.assertEqual(len(self.titles), 2)
        for title in self.titles:
            self.assertIn('class="brand-logo"', title)
            self.assertIn('src="app/static/brand/dcbe_logo_128.png"', title)

    def test_logo_is_decorative_beside_the_visible_title(self) -> None:
        for title in self.titles:
            self.assertIn('alt=""', title)
            self.assertIn('aria-hidden="true"', title)
            self.assertIn("Daniel Cohen Baseball Explorer", title)

    def test_logo_replaces_the_emoji_rather_than_duplicating_it(self) -> None:
        for title in self.titles:
            self.assertNotIn("⚾", title)

    def test_size_scales_with_the_title_font(self) -> None:
        """em sizing is what lets one rule cover desktop, compact and phone heroes."""
        self.assertRegex(APP, r"\.title-text \.brand-logo \{height: 1\.5em; width: 1\.5em;")
        self.assertIn("object-fit: contain", APP)


class SidebarPlacementTests(unittest.TestCase):
    def test_compact_sidebar_mark_uses_st_logo_once(self) -> None:
        self.assertEqual(APP.count("st.logo("), 1)

    def test_collapsed_header_copy_is_suppressed(self) -> None:
        """Otherwise phones stack a header-bar copy directly above the hero logo."""
        self.assertIn('[data-testid="stHeaderLogo"] {display: none !important;}', APP)

    def test_logo_is_not_scattered_across_the_app(self) -> None:
        refs = [
            p.relative_to(ROOT).as_posix()
            for p in ROOT.glob("*.py")
            if "dcbe_logo" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        self.assertEqual(refs, ["streamlit_app.py"])
        # Two hero variants + the st.logo path.
        self.assertEqual(APP.count("dcbe_logo_128.png"), 3)


if __name__ == "__main__":
    unittest.main()
