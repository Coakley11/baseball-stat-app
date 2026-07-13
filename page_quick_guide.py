"""Polished Quick Guide card — single balanced HTML block, safely escaped."""

from __future__ import annotations

import html
import re
from typing import Any


def _esc(text: str) -> str:
    return html.escape(str(text or "").strip(), quote=True)


def _allow_strong(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if re.search(r"</?strong>", raw, flags=re.I):
        return raw
    return _esc(raw)


def render_quick_guide_card(
    st: Any,
    *,
    what_it_does: str,
    when_to_use: str,
    main_outputs: str,
    tips: list[str] | None = None,
    title: str = "Quick guide",
    icon: str = "📘",
) -> None:
    """Render one self-contained guide card (no split HTML fragments)."""
    tip_items = "".join(
        f"<li>{_allow_strong(tip)}</li>" for tip in (tips or []) if str(tip or "").strip()
    )
    tips_block = (
        f'<p class="page-guide-item"><strong>Tips:</strong></p><ul class="page-guide-tips">{tip_items}</ul>'
        if tip_items
        else ""
    )
    card_html = (
        f'<div class="page-guide" role="note" aria-label="{_esc(title)}">'
        f'<div class="page-guide-title">{_esc(icon)} {_esc(title)}</div>'
        f'<div class="page-guide-body">'
        f'<p class="page-guide-item"><strong>What it does:</strong> {_allow_strong(what_it_does)}</p>'
        f'<p class="page-guide-item"><strong>When to use it:</strong> {_allow_strong(when_to_use)}</p>'
        f'<p class="page-guide-item"><strong>Main outputs:</strong> {_allow_strong(main_outputs)}</p>'
        f"{tips_block}"
        f"</div></div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)
