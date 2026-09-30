"""Polished Quick Guide card — single balanced HTML block, safely escaped.

M2: the card is a native <details>/<summary> disclosure so it can collapse by
default on phones (tap the header to expand) while staying exactly as before —
always visible, non-interactive-looking — on desktop. No Python call site
changes: every existing render_quick_guide_card() call keeps working as-is.
"""

from __future__ import annotations

import html
import re
from typing import Any

try:
    from mobile_foundation import PHONE_MAX_PX
except ImportError:  # pragma: no cover - foundation module always present in-repo
    PHONE_MAX_PX = 640

# Emitted inline with every card (cheap, harmless to repeat — same pattern as
# other page-local <style> blocks in this codebase, e.g. live_draft_room_ui.py).
_QUICK_GUIDE_CSS = f"""<style>
.page-guide > summary {{ cursor: pointer; list-style: none; }}
.page-guide > summary::-webkit-details-marker {{ display: none; }}
.page-guide > summary::marker {{ content: ""; }}
.page-guide > summary::after {{
    content: "\\25B8"; float: right; font-size: 12px; color: #5a6f82;
    transition: transform 0.15s ease;
}}
.page-guide[open] > summary::after {{ transform: rotate(90deg); }}
@media (min-width: {PHONE_MAX_PX + 1}px) {{
    /* Desktop: unchanged from pre-M2 — always fully visible, not a toggle. */
    .page-guide > summary {{ cursor: default; }}
    .page-guide > summary::after {{ display: none; }}
    .page-guide > *:not(summary) {{ display: block !important; }}
}}
</style>"""


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
        f"{_QUICK_GUIDE_CSS}"
        f'<details class="page-guide" aria-label="{_esc(title)}">'
        f'<summary class="page-guide-title">{_esc(icon)} {_esc(title)}</summary>'
        f'<div class="page-guide-body">'
        f'<p class="page-guide-item"><strong>What it does:</strong> {_allow_strong(what_it_does)}</p>'
        f'<p class="page-guide-item"><strong>When to use it:</strong> {_allow_strong(when_to_use)}</p>'
        f'<p class="page-guide-item"><strong>Main outputs:</strong> {_allow_strong(main_outputs)}</p>'
        f"{tips_block}"
        f"</div></details>"
    )
    st.markdown(card_html, unsafe_allow_html=True)
