"""Extract Lineup Management to module and replace elif body with function call."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
lines = (ROOT / "streamlit_app.py").read_text(encoding="utf-8").splitlines()
elif_idx = next(i for i, l in enumerate(lines) if l.strip() == 'elif _assistant_tab == "Lineup Management":')
save_idx = next(
    i for i, l in enumerate(lines[elif_idx:], start=elif_idx) if l.strip().startswith("save_page_state(active_page)")
)
elif_indent = len(lines[elif_idx]) - len(lines[elif_idx].lstrip(" "))
body_base = elif_indent + 4
raw_body = lines[elif_idx + 1 : save_idx]

entries: list[tuple[str, int, str]] = []
for line in raw_body:
    if not line.strip():
        entries.append(("", -1, ""))
        continue
    orig = len(line) - len(line.lstrip(" "))
    entries.append(("line", orig, line))

leak_start: int | None = None
for i, (kind, orig, line) in enumerate(entries):
    if kind == "line" and orig == elif_indent and line.strip().startswith("_lineup_active_context = None"):
        leak_start = i
        break

body: list[str] = []
for i, (kind, orig, line) in enumerate(entries):
    if kind == "":
        body.append("")
        continue
    if leak_start is not None and i >= leak_start:
        line = "    " + line
    elif orig < body_base:
        line = " " * (body_base - orig) + line
    body.append(line)

min_indent = min(len(l) - len(l.lstrip(" ")) for l in body if l.strip())
out: list[str] = []
for line in body:
    if not line.strip():
        out.append("")
        continue
    out.append("    " + line[min_indent:])

header = '''"""Fantasy Lineup Assistant — Lineup Management tab rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd


@dataclass
class LineupManagementDeps:
    """Callables and constants supplied by streamlit_app (avoids circular imports)."""

    build_lineup_assistant_scores: Callable[..., Any]
    enrich_lineup_roster_positions: Callable[..., pd.DataFrame]
    parse_custom_lineup_slots: Callable[..., list[str] | None]
    build_position_aware_lineup: Callable[..., dict[str, Any]]
    roster_position_slot_list: Callable[..., list[str]]
    lineup_diagnosis_report: Callable[..., dict[str, Any]]
    open_waiver_wire_from_lineup_slot: Callable[..., None]
    fantasy_filter_changed: Callable[..., None]
    ensure_select_in_options: Callable[..., Any]
    ensure_widget_state: Callable[..., Any]
    render_output_table: Callable[..., Any]
    format_lineup_assistant_table: Callable[..., pd.DataFrame]
    clean_ui_columns: Callable[..., pd.DataFrame]
    render_contextual_page_nav: Callable[..., None]
    developer_mode_enabled: Callable[[], bool]
    navigate_to_page: Callable[..., None]
    page_option_label: Callable[..., str]
    safe_collection_len: Callable[..., int]
    lineup_default_hitting_slots: tuple[str, ...]
    resolve_lineup_scoring_format: Callable[..., str]


def render_lineup_management_page(
    st: Any,
    session: dict[str, Any],
    *,
    roster_stats: pd.DataFrame,
    lineup_team: str,
    lineup_teams: list[str],
    deps: LineupManagementDeps,
) -> None:
'''

replacements = [
    ("build_lineup_assistant_scores(", "deps.build_lineup_assistant_scores("),
    ("enrich_lineup_roster_positions(", "deps.enrich_lineup_roster_positions("),
    ("_parse_custom_lineup_slots(", "deps.parse_custom_lineup_slots("),
    ("build_position_aware_lineup(", "deps.build_position_aware_lineup("),
    ("_roster_position_slot_list(", "deps.roster_position_slot_list("),
    ("lineup_diagnosis_report(", "deps.lineup_diagnosis_report("),
    ("open_waiver_wire_from_lineup_slot", "deps.open_waiver_wire_from_lineup_slot"),
    ("fantasy_filter_changed", "deps.fantasy_filter_changed"),
    ("ensure_select_in_options(", "deps.ensure_select_in_options("),
    ("ensure_widget_state(", "deps.ensure_widget_state("),
    ("render_output_table(", "deps.render_output_table("),
    ("format_lineup_assistant_table(", "deps.format_lineup_assistant_table("),
    ("clean_ui_columns(", "deps.clean_ui_columns("),
    ("render_contextual_page_nav(", "deps.render_contextual_page_nav("),
    ("developer_mode_enabled(", "deps.developer_mode_enabled("),
    ("navigate_to_page(", "deps.navigate_to_page("),
    ("page_option_label(", "deps.page_option_label("),
    ("safe_collection_len(", "deps.safe_collection_len("),
    ("LINEUP_DEFAULT_HITTING_SLOTS", "deps.lineup_default_hitting_slots"),
    ("resolve_lineup_scoring_format(", "deps.resolve_lineup_scoring_format("),
    ("st.session_state", "session"),
]
text = "\n".join(out)
for old, new in replacements:
    text = text.replace(old, new)
(ROOT / "fantasy_lineup_management_ui.py").write_text(header + text + "\n", encoding="utf-8")

call_block = [
    '        elif _assistant_tab == "Lineup Management":',
    "            from fantasy_lineup_management_ui import LineupManagementDeps, render_lineup_management_page",
    "",
    "            _lineup_deps = LineupManagementDeps(",
    "                build_lineup_assistant_scores=build_lineup_assistant_scores,",
    "                enrich_lineup_roster_positions=enrich_lineup_roster_positions,",
    "                parse_custom_lineup_slots=_parse_custom_lineup_slots,",
    "                build_position_aware_lineup=build_position_aware_lineup,",
    "                roster_position_slot_list=_roster_position_slot_list,",
    "                lineup_diagnosis_report=lineup_diagnosis_report,",
    "                open_waiver_wire_from_lineup_slot=open_waiver_wire_from_lineup_slot,",
    "                fantasy_filter_changed=fantasy_filter_changed,",
    "                ensure_select_in_options=ensure_select_in_options,",
    "                ensure_widget_state=ensure_widget_state,",
    "                render_output_table=render_output_table,",
    "                format_lineup_assistant_table=format_lineup_assistant_table,",
    "                clean_ui_columns=clean_ui_columns,",
    "                render_contextual_page_nav=render_contextual_page_nav,",
    "                developer_mode_enabled=developer_mode_enabled,",
    "                navigate_to_page=navigate_to_page,",
    "                page_option_label=page_option_label,",
    "                safe_collection_len=safe_collection_len,",
    "                lineup_default_hitting_slots=LINEUP_DEFAULT_HITTING_SLOTS,",
    "                resolve_lineup_scoring_format=resolve_lineup_scoring_format,",
    "            )",
    "            render_lineup_management_page(",
    "                st,",
    "                st.session_state,",
    "                roster_stats=roster_stats,",
    "                lineup_team=str(lineup_team or \"\"),",
    "                lineup_teams=lineup_teams,",
    "                deps=_lineup_deps,",
    "            )",
]
lines[elif_idx:save_idx] = call_block
(ROOT / "streamlit_app.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("extracted", len(out), "lines; leak_start", leak_start, "min_indent", min_indent)
