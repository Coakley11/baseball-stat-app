"""Single source of truth for Streamlit Cloud app iframe selection."""

from __future__ import annotations

from typing import Any


def resolve_streamlit_app_frame(page):
    """Prefer frame whose URL contains /~/ (Streamlit app view)."""
    for frame in page.frames:
        url = str(frame.url or "")
        if "/~/" in url or "~/+" in url:
            return frame
    return page.main_frame


def describe_page_frames(page) -> dict[str, Any]:
    frames_meta: list[dict[str, Any]] = []
    for idx, frame in enumerate(page.frames):
        frames_meta.append(
            {
                "index": idx,
                "name": str(getattr(frame, "name", "") or ""),
                "url": str(frame.url or "")[:240],
            }
        )
    app = resolve_streamlit_app_frame(page)
    return {
        "frame_count": len(page.frames),
        "frames": frames_meta,
        "selected_frame_url": str(app.url or "")[:240],
        "selected_frame_name": str(getattr(app, "name", "") or ""),
        "selected_is_main": app == page.main_frame,
    }
