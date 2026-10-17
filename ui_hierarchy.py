"""Answer-first page building blocks (U1).

A page reads top to bottom as:

    page identity (page_head) → answer / takeaway (answer_card, metric_tiles, ranked_list)
    → next actions (action_row) → explore more (explore_more: filters, full tables, charts)

These helpers only present numbers the page already computed. They never compute a
statistic. All text is HTML-escaped unless a caller passes ``html=True`` content it built from
escaped parts.
"""

from __future__ import annotations

import html
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Sequence

U1_CSS = """<style>
.u1-page-head { margin: 0 0 0.35rem 0; }
.u1-page-head .u1-title { font-size: 1.55rem; font-weight: 700; color: #0b2540; line-height: 1.25; margin: 0; }
.u1-page-head .u1-purpose { font-size: 0.95rem; color: #4a5d70; margin: 2px 0 0 0; }
.u1-answer { border: 1px solid #d8e2ec; border-left: 4px solid #1f5fa8; border-radius: 10px;
  padding: 12px 14px; background: #f6f9fc; margin: 0.25rem 0 0.6rem 0; }
.u1-answer.good { border-left-color: #2e7d4f; }
.u1-answer.warn { border-left-color: #b26a00; }
.u1-answer .u1-kicker { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: #5a6f82; }
.u1-answer .u1-headline { font-size: 1.2rem; font-weight: 700; color: #0b2540; margin: 2px 0 4px 0; line-height: 1.3; }
.u1-answer .u1-body { font-size: 0.93rem; color: #33475b; margin: 0; }
.u1-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 8px; margin: 0.35rem 0 0.6rem 0; }
.u1-tile { border: 1px solid #e3e9f0; border-radius: 8px; padding: 8px 10px; background: #fff; min-width: 0; }
.u1-tile .u1-v { font-size: 1.2rem; font-weight: 700; color: #0b2540; overflow-wrap: anywhere; }
.u1-tile .u1-l { font-size: 0.74rem; color: #5a6f82; text-transform: uppercase; letter-spacing: 0.04em; }
.u1-tile .u1-s { font-size: 0.74rem; color: #6b7c8f; }
.u1-ranks { margin: 0.2rem 0 0.6rem 0; width: 100%; }
.u1-rank-row { display: flex; align-items: center; gap: 10px; padding: 7px 6px; border-bottom: 1px solid #eef2f6; min-width: 0; }
.u1-rank-row.me { background: #fff8e6; border-radius: 6px; }
.u1-ranks .u1-name { font-weight: 600; color: #0b2540; flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.u1-ranks .u1-sub { font-size: 0.8rem; color: #5a6f82; }
.u1-ranks .u1-val { font-weight: 700; color: #0b2540; white-space: nowrap; }
.u1-badge { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px;
  border-radius: 50%; background: #e8eef5; color: #0b2540; font-weight: 700; font-size: 0.85rem; flex: 0 0 auto; }
.u1-badge.r1 { background: #f3d36b; } .u1-badge.r2 { background: #d6dce4; } .u1-badge.r3 { background: #e3b48a; }
.u1-pos { display: inline-block; font-size: 0.7rem; font-weight: 700; padding: 1px 6px; border-radius: 4px;
  background: #eef3f8; color: #28507a; margin-right: 4px; }
.u1-label { font-size: 0.78rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  color: #5a6f82; margin: 0.6rem 0 0.2rem 0; }
.u1-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 0.2rem 0 0.5rem 0; }
.u1-chip { font-size: 0.82rem; padding: 3px 9px; border-radius: 999px; background: #eef3f8; color: #28507a; }
.u1-chip.good { background: #e6f4ec; color: #1f6b42; } .u1-chip.warn { background: #fff1dc; color: #8a5300; }
.u1-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; margin: 0.3rem 0 0.4rem 0; }
.u1-card { border: 1px solid #dfe7ef; border-radius: 10px; padding: 12px 14px; background: #fff; min-width: 0; }
.u1-card .u1-card-title { font-weight: 700; color: #0b2540; font-size: 1.02rem; }
.u1-card .u1-card-body { font-size: 0.88rem; color: #4a5d70; margin-top: 3px; }
.u1-progress { height: 7px; background: #eef2f6; border-radius: 4px; overflow: hidden; margin: 4px 0 2px 0; }
.u1-progress > span { display: block; height: 7px; background: #1f5fa8; border-radius: 4px; }
.u1-muted { font-size: 0.82rem; color: #5a6f82; }
</style>"""


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def inject_css(st: Any) -> None:
    """Emit the U1 stylesheet (one small <style> block; pages call it once via page_head)."""
    st.markdown(U1_CSS, unsafe_allow_html=True)


def page_head(st: Any, title: str, purpose: str = "") -> None:
    """Short page identity: title + one plain-language line."""
    inject_css(st)
    purpose_html = f'<p class="u1-purpose">{esc(purpose)}</p>' if purpose else ""
    st.markdown(f'<div class="u1-page-head"><p class="u1-title">{esc(title)}</p>{purpose_html}</div>',
                unsafe_allow_html=True)


def answer_card(st: Any, headline: str, body: str = "", *, kicker: str = "", tone: str = "",
                body_html: bool = False) -> None:
    """The first answer on the page. ``tone``: "" | "good" | "warn"."""
    tone_cls = f" {tone}" if tone in ("good", "warn") else ""
    kicker_html = f'<div class="u1-kicker">{esc(kicker)}</div>' if kicker else ""
    body_part = (body if body_html else esc(body)) if body else ""
    body_html_block = f'<p class="u1-body">{body_part}</p>' if body_part else ""
    st.markdown(
        f'<div class="u1-answer{tone_cls}">{kicker_html}<div class="u1-headline">{esc(headline)}</div>{body_html_block}</div>',
        unsafe_allow_html=True,
    )


def metric_tiles(st: Any, tiles: Iterable[tuple[str, Any, str]]) -> None:
    """Small metric tiles: (label, value, sub-line). Wraps on phones; never scrolls sideways."""
    items = "".join(
        f'<div class="u1-tile"><div class="u1-l">{esc(label)}</div><div class="u1-v">{esc(value)}</div>'
        + (f'<div class="u1-s">{esc(sub)}</div>' if sub else "")
        + "</div>"
        for label, value, sub in tiles
    )
    if items:
        st.markdown(f'<div class="u1-tiles">{items}</div>', unsafe_allow_html=True)


def ranked_list(st: Any, rows: Sequence[dict[str, Any]], *, start: int = 1) -> None:
    """Rank badges + name + sub-line + value. Row keys: name, sub, value, me (bool), positions (list)."""
    items = []
    for i, row in enumerate(rows, start=start):
        rank = row.get("rank", i)
        try:
            rank_n = int(rank)
        except (TypeError, ValueError):
            rank_n = 0
        badge_cls = f" r{rank_n}" if 1 <= rank_n <= 3 else ""  # medal colour follows the rank, so ties match
        pos = "".join(f'<span class="u1-pos">{esc(p)}</span>' for p in (row.get("positions") or []))
        sub = f'<div class="u1-sub">{pos}{esc(row.get("sub") or "")}</div>' if (pos or row.get("sub")) else ""
        me = " me" if row.get("me") else ""
        items.append(
            f'<div class="u1-rank-row{me}"><span class="u1-badge{badge_cls}">{esc(rank)}</span>'
            f'<div class="u1-name">{esc(row.get("name"))}{sub}</div>'
            f'<span class="u1-val">{esc(row.get("value", ""))}</span></div>'
        )
    if items:
        st.markdown(f'<div class="u1-ranks">{"".join(items)}</div>', unsafe_allow_html=True)


def chips(st: Any, items: Iterable[tuple[str, str]]) -> None:
    """Small labelled chips: (text, tone) with tone "" | "good" | "warn"."""
    parts = "".join(f'<span class="u1-chip{(" " + t) if t in ("good", "warn") else ""}">{esc(x)}</span>' for x, t in items)
    if parts:
        st.markdown(f'<div class="u1-chips">{parts}</div>', unsafe_allow_html=True)


def section_label(st: Any, text: str) -> None:
    st.markdown(f'<div class="u1-label">{esc(text)}</div>', unsafe_allow_html=True)


def action_row(st: Any, actions: Sequence[tuple[str, Callable[[], None]]], *, key: str, primary: int | None = 0) -> None:
    """2–4 next-step buttons. Each action runs its callback via ``on_click`` (survives reruns);
    callbacks should only schedule navigation or set state — never save or execute a move."""
    if not actions:
        return
    try:
        from mobile_foundation import mobile_wrap_row

        wrap = mobile_wrap_row(st, f"u1-actions-{key}")
    except ImportError:
        wrap = st.container()
    with wrap:
        cols = st.columns(len(actions))
    for i, ((label, callback), col) in enumerate(zip(actions, cols)):
        col.button(label, key=f"u1_action_{key}_{i}", on_click=callback, use_container_width=True,
                   type="primary" if primary is not None and i == primary else "secondary")


@contextmanager
def explore_more(st: Any, label: str = "Explore more", *, expanded: bool = False):
    """Everything advanced: full filters, full tables, secondary charts, methodology.

    Keep ``label`` constant for a page so the open/closed state survives reruns."""
    with st.expander(label, expanded=expanded):
        yield
