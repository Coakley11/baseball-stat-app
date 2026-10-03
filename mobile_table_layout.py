"""Mobile M5 — generic wide-table phone treatment (freeze leading identity columns).

Generalizes the column-pinning helper M4 introduced for Fantasy tables
(``fantasy_mobile_layout.pinned_identity_column_config``, still re-exported there
for backward compatibility) so any wide statistical table across the app — Historical
Explorer, Leaderboards, Comparison, Trend Value, Valuation, ML Predictions, the Waiver
player pool — can freeze its player/team/rank identity columns while stat columns
scroll, without duplicating the logic.

Presentation only: pinning never reorders, renames or recomputes a column. Only a
*leading* run of already-first identity columns is ever pinned — a column that isn't
already at the left edge is left alone rather than promoted there, so desktop column
order is always unchanged.
"""

from __future__ import annotations

from typing import Any, Iterable

# Identity columns this app's wide stat tables commonly lead with, across pages.
# Page call sites pass their own subset/order; this is a shared reference list for
# callers that want the common case rather than spelling out their own tuple.
GENERAL_IDENTITY_COLUMNS: tuple[str, ...] = (
    "Year",
    "Player",
    "Fantasy Team",
    "Team",
    "MLB Team",
    "Primary Position",
    "Position",
    "Rank",
)

__all__ = (
    "GENERAL_IDENTITY_COLUMNS",
    "leading_identity_columns",
    "pinned_identity_column_config",
)


def leading_identity_columns(columns: Iterable[Any], identity: Iterable[str]) -> list[str]:
    """The run of ``identity`` columns at the very start of ``columns`` (order kept).

    Stops at the first column not in ``identity`` — a later identity column (e.g. a
    "Team" that sits after a non-identity "Bats" column) is never pulled forward,
    because pinning only freezes columns already at the left edge.
    """
    wanted = {str(c) for c in identity}
    out: list[str] = []
    for col in columns:
        if str(col) not in wanted:
            break
        out.append(str(col))
    return out


def pinned_identity_column_config(st: Any, columns: Iterable[Any], identity: Iterable[str]) -> dict[str, Any]:
    """``st.dataframe``/``st.data_editor`` ``column_config`` pinning the leading identity run.

    Returns ``{}`` (no-op) on a Streamlit build without ``column_config.Column(pinned=...)``,
    so callers can pass this straight through without a version check of their own.
    """
    cfg: dict[str, Any] = {}
    for col in leading_identity_columns(columns, identity):
        try:
            cfg[col] = st.column_config.Column(pinned=True)
        except Exception:  # pragma: no cover - older Streamlit without pinned columns
            return {}
    return cfg
