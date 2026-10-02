"""Mobile M1 responsive foundation — CSS contract and opt-in helpers."""

from __future__ import annotations

import re
from pathlib import Path

import mobile_foundation as mf

ROOT = Path(__file__).resolve().parents[1]


class _FakeSt:
    def __init__(self):
        self.markdown_calls = []
        self.container_keys = []

    def markdown(self, body, unsafe_allow_html=False):
        self.markdown_calls.append((body, unsafe_allow_html))

    def container(self, key=None):
        self.container_keys.append(key)
        return key


def test_breakpoints_match_streamlit_theme():
    assert mf.PHONE_MAX_PX == 640
    assert mf.TABLET_MAX_PX == 768
    assert mf.SMALL_PHONE_MAX_PX < mf.PHONE_MAX_PX < mf.TABLET_MAX_PX
    assert mf.media_phone() == "@media (max-width: 640px)"
    assert mf.media_tablet() == "@media (max-width: 768px)"


def test_css_braces_balanced_and_no_format_leftovers():
    css = mf.mobile_foundation_css()
    assert css.count("{") == css.count("}")
    assert "{{" not in css and "}}" not in css
    assert "{_" not in css


def test_css_uses_current_streamlit_column_testid():
    css = mf.mobile_foundation_css()
    assert 'data-testid="stColumn"' in css
    assert 'data-testid="column"' not in css


def test_wide_column_shrink_rule_does_not_override_phone_stacking():
    css = mf.mobile_foundation_css()
    m = re.search(r"@media \(min-width: 641px\) \{\s*\[data-testid=\"stColumn\"\] \{ min-width: 0; \}", css)
    assert m, "column min-width reset must be scoped above the phone breakpoint"
    # The only !important column overrides live under the metric-row / opt-in helper selectors.
    for line in css.splitlines():
        scoped = "stMetric" in line or "st-key-m-" in line
        if 'stColumn"]' in line and "!important" in line and not scoped:
            raise AssertionError(f"unexpected !important column rule: {line}")


def test_css_does_not_blanket_hide_content():
    css = mf.mobile_foundation_css()
    assert "display: none" not in css
    assert "visibility: hidden" not in css
    assert "overflow-x: hidden" not in css
    assert "overflow: hidden" not in css


def test_touch_targets_and_input_zoom_guard_are_phone_scoped():
    css = mf.mobile_foundation_css()
    phone_blocks = css.split(mf.media_phone())
    assert len(phone_blocks) >= 2
    before_phone = phone_blocks[0]
    assert "min-height: 2.75rem" not in before_phone
    assert "font-size: 16px" not in before_phone
    assert "min-height: 2.75rem" in css
    assert "font-size: 16px" in css


def test_metric_only_rows_go_two_up_on_phones_without_hiding_values():
    css = mf.mobile_foundation_css()
    phone_part = css.split(mf.media_phone(), 1)[1]
    assert ':has(> [data-testid="stColumn"] [data-testid="stMetric"])' in phone_part
    # Rows mixing metrics with controls/tables are excluded.
    assert ':not(:has([data-testid="stButton"], [data-testid="stSelectbox"]' in css
    assert "white-space: normal" in css and "text-overflow: clip" in css


def test_no_nested_has_selectors():
    """Browsers reject :has() inside :has(), which silently drops the whole rule."""
    css = mf.mobile_foundation_css()
    for m in re.finditer(r":has\(", css):
        depth, i = 1, m.end()
        while depth and i < len(css):
            if css.startswith(":has(", i):
                raise AssertionError(f"nested :has() near: {css[m.start():m.start() + 120]}")
            depth += {"(": 1, ")": -1}.get(css[i], 0)
            i += 1


def test_inject_emits_single_style_block():
    st = _FakeSt()
    mf.inject_mobile_foundation_css(st)
    assert len(st.markdown_calls) == 1
    body, unsafe = st.markdown_calls[0]
    assert unsafe is True
    assert body.startswith("<style>") and body.endswith("</style>")


def test_row_helpers_use_prefixed_container_keys():
    st = _FakeSt()
    assert mf.mobile_inline_row(st, "pager") == "m-inline-pager"
    assert mf.mobile_wrap_row(st, "draft actions!") == "m-wrap-draft-actions"
    css = mf.mobile_foundation_css()
    assert '[class*="st-key-m-inline-"]' in css
    assert '[class*="st-key-m-wrap-"]' in css


def test_scroll_x_wrapper_escapes_label():
    out = mf.mobile_scroll_x("<table></table>", label='Board "A"')
    assert out.startswith('<div class="m-scroll-x" role="region"')
    assert "&quot;A&quot;" in out
    assert mf.mobile_scroll_x("<p>x</p>") == '<div class="m-scroll-x"><p>x</p></div>'


def test_app_appends_foundation_to_base_style_markdown():
    src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    base_style = src.index(".fantasy-source-card {border-radius")
    # Appended after the base rules (same specificity → later wins) in the SAME
    # st.markdown call: a separate call adds an empty element + 16px block gap.
    append = src.index('""" + _MOBILE_FOUNDATION_STYLE, unsafe_allow_html=True)')
    assert append > base_style
    assert "inject_mobile_foundation_css(st)" not in src
    # Before the sidebar/page body so every page receives it.
    assert append < src.index('_selected_page = st.sidebar.radio(')


def test_style_tag_wraps_css():
    tag = mf.mobile_foundation_style_tag()
    assert tag == f"<style>{mf.mobile_foundation_css()}</style>"


def test_portfolio_polish_has_no_stale_column_testid():
    src = (ROOT / "portfolio_polish.py").read_text(encoding="utf-8")
    assert 'data-testid="column"' not in src


def test_wrap_row_button_rule_targets_streamlit_buttons_only():
    """M3 regression (caught live on Live Draft setup): a bare ``button`` selector also
    stretched the select (react-aria ComboBox) chevron over the field, hiding values."""
    css = mf.mobile_foundation_css()
    assert '[data-testid="stColumn"] button {' not in css
    assert '[data-testid="stColumn"] [data-testid^="stBaseButton-"] { width: 100%; }' in css
