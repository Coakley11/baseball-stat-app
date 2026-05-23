"""Player action helpers — dedupe lists and identity normalization (no Streamlit)."""

from __future__ import annotations


def dedupe_append_name(existing, name: str, *, cap: int | None = None) -> list:
    """Append a display name if not already present (order preserved)."""
    out = []
    seen = set()
    for x in list(existing or []):
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    n = str(name or "").strip()
    if n and n not in seen:
        out.append(n)
    if cap is not None:
        return out[-int(cap) :]
    return out


def merge_chart_labels(existing, new_label: str, *, max_labels: int = 3) -> list:
    """Trend multi-chart label list: bump new label to end, cap length, no duplicates."""
    labels = [str(x).strip() for x in list(existing or []) if str(x).strip()]
    nl = str(new_label or "").strip()
    if not nl:
        return labels[:max_labels]
    labels = [x for x in labels if x != nl]
    labels.append(nl)
    return labels[-max_labels:]
