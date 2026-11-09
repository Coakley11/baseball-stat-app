"""Official parent-brand artwork; no authentication, state or network behavior."""
from base64 import b64encode
from functools import lru_cache
from pathlib import Path

LOGO = Path(__file__).resolve().parent / "static" / "branding" / "daniel_ai_suite.png"

@lru_cache(maxsize=1)
def suite_logo_uri():
    return "data:image/png;base64," + b64encode(LOGO.read_bytes()).decode("ascii")

def render_suite_logo(target, *, placement="sidebar"):
    """Full readable wordmark on a white surface, preserving original proportions."""
    widths = {"sidebar": 200, "login": 400, "hub": 360}
    width = widths[placement]
    if placement == "sidebar":
        # A viewport derivative clips only the wordmark; the approved raster is
        # referenced intact. Do not redraw, distort or duplicate its pixels.
        icon = LOGO.with_name("daniel_ai_suite_icon.svg").read_text(encoding="utf-8")
        icon = icon.replace('href="daniel_ai_suite.png"', 'href="' + suite_logo_uri() + '"')
        icon = icon.replace('<svg ', '<svg style="display:block;width:100%;height:auto" ')
        target.markdown(
            '<div class="daniel-suite-brand-icon" style="width:100%;max-width:120px;'
            'margin:0 auto 0.8rem;padding:4px;background:#fff;border-radius:10px;'
            'box-sizing:border-box;overflow:hidden">' + icon + '</div>',
            unsafe_allow_html=True,
        )
        return
    target.markdown(
        '<div class="daniel-suite-brand" style="width:100%;max-width:' + str(width) +
        'px;margin:0 auto 0.8rem;background:#fff;border-radius:10px;overflow:hidden">'
        '<img src="' + suite_logo_uri() + '" alt="Daniel AI Suite" '
        'style="display:block;width:100%;height:auto;object-fit:contain"></div>',
        unsafe_allow_html=True,
    )

def render_suite_login_brand(target):
    render_suite_logo(target, placement="login")
