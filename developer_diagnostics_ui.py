"""Consolidated developer diagnostics — one expander per page, bottom placement."""

from __future__ import annotations

import json
from typing import Any, Callable


def render_page_developer_diagnostics(
    st: Any,
    *,
    developer_mode: bool,
    summary: dict[str, Any] | None = None,
    detail_sections: dict[str, Any] | None = None,
    render_extra: Callable[[Any], None] | None = None,
) -> None:
    """Single collapsed expander; detailed JSON behind optional nested expander."""
    if not developer_mode:
        return
    summary = dict(summary or {})
    detail_sections = dict(detail_sections or {})
    with st.expander("Developer diagnostics", expanded=False):
        if summary:
            st.markdown("**Summary**")
            for key, val in summary.items():
                st.text(f"{key}: {val!r}")
        if render_extra is not None:
            render_extra(st)
        if detail_sections:
            with st.expander("Detailed traces (JSON)", expanded=False):
                st.code(json.dumps(detail_sections, indent=2, default=str), language="json")
