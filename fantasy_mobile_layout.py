"""Mobile M4 — Fantasy Team pages (standings, lineup, waiver, trades) on phones.

Presentation only: no roster, scoring, standings, waiver, transaction or trade logic.

- ``fantasy_card_key``: class hook for an existing bordered player card
  (photo | details | action columns). On phones the card stays one compact row —
  small photo on the left, details beside it, action button under the details —
  instead of stacking a full-width photo, text block and button per player.
- ``pinned_identity_column_config``: freezes the leading identity columns of a wide
  table (e.g. Team, Player) so they stay visible while category columns scroll.
  Only a contiguous leading run is pinned, so column order never changes (pinned
  columns are always drawn first) and desktop tables that fit look the same.

Row compaction (nav buttons, trade actions, open lineup slots) reuses the M1
``mobile_wrap_row`` / ``mobile_inline_row`` helpers rather than new CSS.
"""

from __future__ import annotations

from typing import Any, Iterable

try:
    from mobile_foundation import PHONE_MAX_PX
except ImportError:  # pragma: no cover - foundation module always present in-repo
    PHONE_MAX_PX = 640

CARD_KEY_PREFIX = "m-fcard-"

STANDINGS_IDENTITY_COLUMNS: tuple[str, ...] = ("Fantasy Team", "Team", "Player")
LINEUP_IDENTITY_COLUMNS: tuple[str, ...] = ("Fantasy slot", "Player")

__all__ = (
    "CARD_KEY_PREFIX",
    "STANDINGS_IDENTITY_COLUMNS",
    "LINEUP_IDENTITY_COLUMNS",
    "fantasy_card_key",
    "leading_identity_columns",
    "pinned_identity_column_config",
    "fantasy_mobile_css",
    "fantasy_mobile_style_tag",
    "phone_wrap_row",
    "phone_inline_row",
)


def fantasy_card_key(key_prefix: str, name: str) -> str:
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in f"{key_prefix}_{name}")[:80]
    return f"{CARD_KEY_PREFIX}{safe}"


def leading_identity_columns(columns: Iterable[Any], identity: Iterable[str]) -> list[str]:
    """The run of ``identity`` columns at the very start of ``columns`` (order kept)."""
    wanted = {str(c) for c in identity}
    out: list[str] = []
    for col in columns:
        if str(col) not in wanted:
            break
        out.append(str(col))
    return out


def pinned_identity_column_config(st: Any, columns: Iterable[Any], identity: Iterable[str]) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    for col in leading_identity_columns(columns, identity):
        try:
            cfg[col] = st.column_config.Column(pinned=True)
        except Exception:  # pragma: no cover - older Streamlit without pinned columns
            return {}
    return cfg


def _row(st: Any, key: str, *, inline: bool):
    from contextlib import nullcontext

    try:
        from mobile_foundation import mobile_inline_row, mobile_wrap_row

        return (mobile_inline_row if inline else mobile_wrap_row)(st, key)
    except (ImportError, AttributeError, TypeError):  # test doubles without keyed containers
        return nullcontext()


def phone_wrap_row(st: Any, key: str):
    """M1 wrap row (~2-up tiles on phones), tolerant of minimal ``st`` doubles."""
    return _row(st, key, inline=False)


def phone_inline_row(st: Any, key: str):
    """M1 inline row (columns stay side by side on phones), tolerant of ``st`` doubles."""
    return _row(st, key, inline=True)


_CARD = f'[class*="st-key-{CARD_KEY_PREFIX}"]'
_HB = '[data-testid="stHorizontalBlock"]'
_COL = '[data-testid="stColumn"]'
_TRADE_ACTIONS = '.st-key-m-wrap-trade-actions'


def fantasy_mobile_css() -> str:
    return f"""
/* Mobile M4 — Fantasy player cards: one compact row per player on phones. */
@media (max-width: {PHONE_MAX_PX}px) {{
    {_CARD} {{ padding: 10px 12px !important; gap: 0 !important; }}
    {_CARD} {_HB} {{
        display: grid !important; grid-template-columns: 48px minmax(0, 1fr);
        column-gap: 10px; row-gap: 6px; align-items: start;
    }}
    {_CARD} {_HB} > {_COL} {{ width: auto !important; min-width: 0 !important; flex: none !important; }}
    {_CARD} {_HB} > {_COL}:nth-child(1) {{ grid-column: 1; grid-row: 1 / span 2; }}
    {_CARD} {_HB} > {_COL}:nth-child(2) {{ grid-column: 2; grid-row: 1; }}
    {_CARD} {_HB} > {_COL}:nth-child(3) {{ grid-column: 2; grid-row: 2; }}
    {_CARD} {_HB} > {_COL}:nth-child(1) img,
    {_CARD} {_HB} > {_COL}:nth-child(1) .ld-rec-card-photo > div {{
        width: 48px !important; height: 48px !important; max-width: 48px !important; object-fit: cover;
    }}
    {_CARD} {_HB} > {_COL}:nth-child(2) [data-testid="stVerticalBlock"] {{ gap: 4px; }}
    /* Streamlit pulls each markdown block up by -1rem (to cancel a trailing <p> margin);
       with the tighter gap that made the team line and stat line overlap. */
    {_CARD} [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
    {_CARD} [data-testid="stMarkdownContainer"] p {{ margin: 0; line-height: 1.35; }}
    /* Wrap-row action tiles (trade actions): fill the tile like the nav buttons do. */
    {_TRADE_ACTIONS} [data-testid="stButton"],
    {_TRADE_ACTIONS} [data-testid^="stBaseButton-"] {{ width: 100%; }}
}}
"""


def fantasy_mobile_style_tag() -> str:
    return f"<style>{fantasy_mobile_css()}</style>"
