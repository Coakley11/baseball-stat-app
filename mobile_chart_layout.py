"""Mobile M5 — matplotlib chart legibility on phones.

``st.pyplot`` (Streamlit 1.59, this app's version) already defaults to
``width="stretch"``, so a matplotlib figure never causes page overflow — it's a
static image the browser scales to the column's width. What it can't fix is text
*inside* that image: a figure rendered at matplotlib's default font sizes, then
CSS-shrunk from a desktop-width render to a ~360px phone column, turns titles,
axis labels and legends into an unreadable thumbnail (the exact failure mode the
M5 brief calls out). CSS cannot rescale text baked into a bitmap, and this app has
no client-viewport signal to size the figure for the actual render width (every
earlier mobile slice stayed CSS/media-query only for the same reason) — so the
only lever available is matplotlib's own font-size configuration, used here
instead of a CSS workaround.

``legible_matplotlib_chart()`` is a narrow ``rc_context`` bump (title/label/tick/
legend sizes, plus tight layout so a bigger title doesn't clip) applied only around
the handful of ad hoc ``plt.subplots()`` chart functions in ``streamlit_app.py``.
It does not touch chart data, axes ranges, or any other matplotlib caller. Desktop
keeps the same figure, just with modestly larger, more legible text — a small,
deliberate trade rather than a true fix, since no static image can be crisp at
every width; see docs/MOBILE_M5_ANALYTICS.md for what this does and doesn't solve.

Vector charts (this app's two Altair/Vega-Lite scatterplots) don't have this
problem — they already render at ``width="stretch"`` natively crisp at any size
and are left untouched.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

# Modest bump over matplotlib defaults (font.size 10, axes.titlesize 'large' ~12,
# axes.labelsize/tick.labelsize 'medium' ~10, legend.fontsize 'medium' ~10). Large
# enough to meaningfully help legibility once Streamlit's width="stretch" shrinks
# the figure for a phone column, without making the same static image look
# oversized in its desktop column.
MOBILE_CHART_RC: dict[str, object] = {
    "font.size": 12,
    "axes.titlesize": 15,
    "axes.labelsize": 13,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "legend.fontsize": 11,
    "figure.autolayout": True,  # tight layout: avoids a larger title/legend clipping
}

__all__ = ("MOBILE_CHART_RC", "legible_matplotlib_chart")


@contextmanager
def legible_matplotlib_chart() -> Iterator[None]:
    """Wrap a ``plt.subplots()`` + ``st.pyplot()`` block in legible-on-phone rcParams.

    Usage::

        with legible_matplotlib_chart():
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(...)
            st.pyplot(fig, clear_figure=True)
    """
    import matplotlib.pyplot as plt

    with plt.rc_context(MOBILE_CHART_RC):
        yield
