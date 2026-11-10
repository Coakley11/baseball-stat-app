"""Approved parent artwork must stay local, exact and accessible."""
import base64
import hashlib
from xml.etree import ElementTree
import suite_parent_brand as brand

def test_approved_artwork_identity_and_compact_viewport():
    assert hashlib.sha256(brand.LOGO.read_bytes()).hexdigest() == (
        "b4761538cca65b91dbd6bccccc48b710f7e99d318c91e09a073030cc84a3807f"
    )
    svg = ElementTree.parse(brand.LOGO.with_name("daniel_ai_suite_icon.svg")).getroot()
    assert svg.attrib["viewBox"] == "320 0 850 710"
    image, = svg.findall("{http://www.w3.org/2000/svg}image")
    assert image.attrib["href"] == "daniel_ai_suite.png"
    assert (image.attrib["width"], image.attrib["height"]) == ("1536", "1024")

def test_full_and_compact_render_without_app_state_or_remote_images():
    class Target:
        def markdown(self, markup, **kwargs):
            self.markup = markup
    target = Target()
    for placement in ("login", "sidebar", "hub"):
        brand.render_suite_logo(target, placement=placement)
        assert "Daniel AI Suite" in target.markup
        assert "background:#fff" in target.markup
        assert 'src="http' not in target.markup and 'href="http' not in target.markup
        assert base64.b64encode(brand.LOGO.read_bytes()).decode() in target.markup
        assert "width:100%;height:auto" in target.markup
