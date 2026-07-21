"""Wrap rec_col heavy block in _paint_heavy_recommendations_body for fragment defer."""
from __future__ import annotations

from pathlib import Path

path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

start_marker = "                if _defer_heavy_paint:\n"
end_marker = "                from draft_ui import render_live_manual_draft_panel\n"

start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if line == start_marker and start_idx is None:
        start_idx = i
    if line == end_marker and start_idx is not None:
        end_idx = i
        break

if start_idx is None or end_idx is None:
    raise SystemExit(f"markers not found start={start_idx} end={end_idx}")

# Remove defer caption block + if not _defer_heavy_paint line
if not lines[start_idx + 5].strip().startswith("if not _defer_heavy_paint"):
    raise SystemExit(f"unexpected line at {start_idx+5}: {lines[start_idx+5]!r}")

header = "                def _paint_heavy_recommendations_body() -> None:\n"
body_start = start_idx + 6
body_lines = lines[body_start:end_idx]
dedented = []
for ln in body_lines:
    if ln.startswith("                    "):
        dedented.append("                " + ln[4:])
    else:
        dedented.append(ln)

footer = (
    "                try:\n"
    "                    from live_draft_heavy_paint_ui import render_deferred_heavy_paint_fragment\n\n"
    "                    render_deferred_heavy_paint_fragment(\n"
    "                        st,\n"
    "                        st.session_state,\n"
    "                        _paint_heavy_recommendations_body,\n"
    "                    )\n"
    "                except ImportError:\n"
    "                    if not _defer_heavy_paint:\n"
    "                        _paint_heavy_recommendations_body()\n\n"
)

new_lines = lines[:start_idx] + [header] + dedented + [footer] + lines[end_idx:]
path.write_text("".join(new_lines), encoding="utf-8")
print(f"Wrapped lines {start_idx+1}-{end_idx}")
