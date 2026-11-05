"""Approved logos must remain self-contained and preserve resolved navigation."""
import base64
import io
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import suite_brand_assets as brands


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_link_preserves_url_label_and_new_tab():
    class Target:
        def markdown(self, text, **kwargs):
            self.text = text

    target = Target()
    url = 'https://example.test/?suite_workspace=alice&resume=a%2Fb#section'
    assert brands.render_command_center_brand_link(target, '<Command Center>', url)
    markup = Markup(target.text)
    anchor = next(attrs for tag, attrs in markup.tags if tag == 'a')
    assert anchor['href'] == url
    assert anchor['target'] == '_blank'
    assert 'noopener' in anchor['rel']
    assert '&lt;Command Center&gt;' in target.text
    image = next(attrs for tag, attrs in markup.tags if tag == 'img')
    with Image.open(io.BytesIO(base64.b64decode(image['src'].split(',', 1)[1]))) as im:
        assert im.size == (96, 96)


def test_missing_logo_uses_existing_button_fallback():
    brands.brand_data_uri.cache_clear()
    with patch.object(brands, 'ROOT', Path('/nonexistent-branding-test')):
        assert not brands.render_command_center_brand_link(object(), 'Command Center', 'https://example.test')
    brands.brand_data_uri.cache_clear()


def test_each_shipped_optimized_asset_decodes():
    assets = brands.ROOT / 'static/branding'
    found = list(assets.glob('command_*.png')) + list(assets.glob('investment_*.png')) + list(assets.glob('*_full.webp'))
    assert found
    for asset in found:
        with Image.open(asset) as image:
            image.load()
            assert image.width <= 768 and image.height <= 768
            if '_emblem_' in asset.name:
                assert image.width == image.height
        assert asset.stat().st_size < 500_000
