"""View models and HTML renderers for Fantasy Lineup / Roster Management UI."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fantasy_weekly_lineup import (
    _player_name_col,
    assignments_to_slot_player_map,
    build_lineup_summary,
    not_starting_players,
    player_eligible_for_slot,
    position_tokens_from_row,
    roster_player_names,
    slot_display_name,
    validate_weekly_lineup,
)


@dataclass(frozen=True)
class SlotKeyLabel:
    key: str
    label: str
    badge: str
    position_name: str
    base_slot: str
    repeat_index: int


@dataclass
class PlayerCardModel:
    player_name: str
    mlb_team: str
    positions: str
    stat_line: str
    photo_html: str
    has_photo: bool
    recommendation: str = ""
    player_id: str = ""


@dataclass
class SlotCardModel:
    slot_key: str
    label: str
    badge: str
    position_name: str
    state: str
    player: PlayerCardModel | None = None


@dataclass
class EmptySlotModel:
    slot_key: str
    label: str
    badge: str
    position_name: str


@dataclass
class TeamHeaderModel:
    team_name: str
    league_name: str
    week: int
    week_label: str
    roster_count: int
    filled_starters: int
    total_starter_slots: int
    is_active_team: bool
    last_saved_at: str = ""


def format_repeated_slot_label(base_slot: str, repeat_index: int) -> str:
    """Human label for repeated slots: OF 1, OF 2, OF 3, etc."""
    base = str(base_slot or "").strip().upper()
    idx = max(1, int(repeat_index))
    if base == "OF":
        return f"OF {idx}"
    if base == "UTIL":
        return "UTIL" if idx == 1 else f"Utility ({idx})"
    name = slot_display_name(base)
    return name if idx == 1 else f"{name} ({idx})"


def slot_badge(base_slot: str, repeat_index: int) -> str:
    base = str(base_slot or "").strip().upper()
    idx = max(1, int(repeat_index))
    if base == "OF":
        return f"OF {idx}"
    if base == "UTIL" and idx > 1:
        return f"UTIL {idx}"
    return base


def build_slot_key_labels(slots: list[str]) -> list[SlotKeyLabel]:
    """Return widget keys and display labels for each configured starter slot."""
    counts: dict[str, int] = {}
    out: list[SlotKeyLabel] = []
    for slot in slots:
        base = str(slot or "").strip().upper()
        count = counts.get(base, 0) + 1
        counts[base] = count
        key = base if count == 1 else f"{base}_{count}"
        label = format_repeated_slot_label(base, count)
        out.append(
            SlotKeyLabel(
                key=key,
                label=label,
                badge=slot_badge(base, count),
                position_name=slot_display_name(base),
                base_slot=base,
                repeat_index=count,
            )
        )
    return out


def slot_key_labels_as_tuples(labels: list[SlotKeyLabel]) -> list[tuple[str, str]]:
    return [(item.key, item.label) for item in labels]


def _mlb_team_from_row(row: pd.Series | dict[str, Any]) -> str:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": _d
    for col in ("Team", "MLB Team", "mlb_team", "team"):
        val = str(getter(col) or "").strip()
        if val and val.lower() not in ("nan", "none"):
            return val
    return ""


def _player_id_from_row(row: pd.Series | dict[str, Any]) -> str:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": _d
    for key in ("player_id", "playerID", "playerId", "mlbam_id", "ID"):
        val = str(getter(key) or "").strip()
        if val:
            return val
    return ""


def initials_from_name(name: str) -> str:
    parts = [p for p in re.split(r"\s+", str(name or "").strip()) if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


# Canonical hitter stat order for player cards: Runs, HR, RBI, SB, AVG, OPS.
# Each entry: (source column aliases, display label, "count" | "rate").
HITTER_STAT_FIELDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("R", "Runs"), "R", "count"),
    (("HR",), "HR", "count"),
    (("RBI",), "RBI", "count"),
    (("SB",), "SB", "count"),
    (("AVG", "BA"), "AVG", "rate"),
    (("OPS",), "OPS", "rate"),
)


def format_rate_stat(value: float) -> str:
    """Three-decimal baseball rate stat, dropping the leading zero when < 1 (.320)."""
    text = f"{float(value):.3f}"
    if text.startswith("0."):
        return text[1:]
    if text.startswith("-0."):
        return "-" + text[2:]
    return text


def _first_present_value(getter: Any, aliases: tuple[str, ...]) -> Any:
    for col in aliases:
        val = getter(col)
        if val is None:
            continue
        if isinstance(val, float) and pd.isna(val):
            continue
        return val
    return None


def compact_stat_line_from_row(row: pd.Series | dict[str, Any]) -> str:
    """Hitter card stat line: R · HR · RBI · SB · AVG · OPS.

    Missing individual columns are skipped (never truncated away), rate stats
    render to three decimals, and counting stats render as integers.
    """
    getter = row.get if hasattr(row, "get") else lambda _k, _d=None: _d
    bits: list[str] = []
    for aliases, label, kind in HITTER_STAT_FIELDS:
        val = _first_present_value(getter, aliases)
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if pd.isna(fval):
            continue
        if kind == "rate":
            bits.append(f"{label} {format_rate_stat(fval)}")
        else:
            bits.append(f"{label} {int(fval)}")
    return " · ".join(bits)


def photo_html_for_player(
    *,
    player_name: str,
    row: pd.Series | dict[str, Any] | None = None,
    size: int = 56,
    use_api: bool = False,
) -> tuple[str, bool]:
    """Return (html, has_photo) with circular headshot or initials/baseball fallback."""
    safe_name = html_lib.escape(str(player_name or "Player"))
    initials = html_lib.escape(initials_from_name(player_name))
    try:
        from player_photos import get_player_photo_info

        photo_info = get_player_photo_info(full_name=player_name, row=row, use_api=use_api, image_size=120)
        url = str(photo_info.get("headshot_url") or "").strip()
        if url:
            return (
                f'<img class="fl-player-photo" src="{html_lib.escape(url)}" '
                f'alt="{safe_name}" width="{size}" height="{size}" loading="lazy"/>',
                True,
            )
    except ImportError:
        pass
    return (
        f'<div class="fl-player-photo fl-photo-fallback" aria-label="{safe_name}">'
        f'<span class="fl-photo-fallback-icon" aria-hidden="true">⚾</span>'
        f'<span class="fl-photo-initials">{initials}</span></div>',
        False,
    )


def build_player_card_model(
    row: pd.Series | dict[str, Any],
    *,
    player_name: str = "",
    recommendation: str = "",
    use_api: bool = False,
) -> PlayerCardModel:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": _d
    name = str(player_name or getter(_player_name_col(pd.DataFrame([row]))) or "").strip()
    tokens = position_tokens_from_row(row)
    positions = "/".join(tokens[:5]) if tokens else "—"
    photo_html, has_photo = photo_html_for_player(player_name=name, row=row, use_api=use_api)
    return PlayerCardModel(
        player_name=name,
        mlb_team=_mlb_team_from_row(row),
        positions=positions,
        stat_line=compact_stat_line_from_row(row),
        photo_html=photo_html,
        has_photo=has_photo,
        recommendation=str(recommendation or "").strip(),
        player_id=_player_id_from_row(row),
    )


def build_empty_slot_model(slot: SlotKeyLabel) -> EmptySlotModel:
    return EmptySlotModel(
        slot_key=slot.key,
        label=slot.label,
        badge=slot.badge,
        position_name=slot.position_name,
    )


def _row_lookup(roster_df: pd.DataFrame) -> dict[str, pd.Series]:
    if roster_df is None or roster_df.empty:
        return {}
    col = _player_name_col(roster_df)
    return {
        str(row[col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(col) or "").strip()
    }


def _recommendation_map(scored_roster: pd.DataFrame | None) -> dict[str, str]:
    if scored_roster is None or scored_roster.empty or "Player" not in scored_roster.columns:
        return {}
    rec_col = "Start/Sit Recommendation" if "Start/Sit Recommendation" in scored_roster.columns else ""
    out: dict[str, str] = {}
    for _, row in scored_roster.iterrows():
        name = str(row.get("Player") or "").strip()
        if name:
            out[name] = str(row.get(rec_col) or "").strip() if rec_col else ""
    return out


def slot_visual_states(
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
) -> dict[str, str]:
    """Map slot_key -> filled | open | invalid."""
    lookup = _row_lookup(roster_df)
    states: dict[str, str] = {}
    for slot in slot_labels:
        player = str(assignments.get(slot.key) or "").strip()
        if not player:
            states[slot.key] = "open"
            continue
        row = lookup.get(player)
        if row is None or not player_eligible_for_slot(position_tokens_from_row(row), slot.base_slot):
            states[slot.key] = "invalid"
        else:
            states[slot.key] = "filled"
    return states


def build_slot_cards(
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
    *,
    scored_roster: pd.DataFrame | None = None,
    validation_styles: dict[str, str] | None = None,
) -> list[SlotCardModel]:
    lookup = _row_lookup(roster_df)
    rec_map = _recommendation_map(scored_roster)
    styles = validation_styles or slot_visual_states(slot_labels, assignments, roster_df)
    cards: list[SlotCardModel] = []
    for slot in slot_labels:
        player_name = str(assignments.get(slot.key) or "").strip()
        state = styles.get(slot.key) or ("open" if not player_name else "filled")
        if state == "valid":
            state = "filled"
        elif state == "empty":
            state = "open"
        player_card = None
        if player_name:
            row = lookup.get(player_name)
            if row is not None:
                player_card = build_player_card_model(
                    row,
                    player_name=player_name,
                    recommendation=rec_map.get(player_name, ""),
                    use_api=False,
                )
            else:
                player_card = PlayerCardModel(
                    player_name=player_name,
                    mlb_team="",
                    positions="—",
                    stat_line="Not on active roster",
                    photo_html=photo_html_for_player(player_name=player_name, row=None)[0],
                    has_photo=False,
                )
                state = "invalid"
        cards.append(
            SlotCardModel(
                slot_key=slot.key,
                label=slot.label,
                badge=slot.badge,
                position_name=slot.position_name,
                state=state,
                player=player_card,
            )
        )
    return cards


def bench_player_cards(
    roster_df: pd.DataFrame,
    assignments: dict[str, str],
    slot_labels: list[SlotKeyLabel],
    *,
    scored_roster: pd.DataFrame | None = None,
) -> list[PlayerCardModel]:
    slot_map = {label.key: str(assignments.get(label.key) or "").strip() for label in slot_labels}
    bench_names = not_starting_players(roster_df, slot_map)
    lookup = _row_lookup(roster_df)
    rec_map = _recommendation_map(scored_roster)
    cards: list[PlayerCardModel] = []
    for name in bench_names:
        row = lookup.get(name)
        if row is None:
            continue
        cards.append(
            build_player_card_model(
                row,
                player_name=name,
                recommendation=rec_map.get(name, ""),
                use_api=False,
            )
        )
    return cards


def build_team_header_model(
    *,
    context: dict[str, Any] | None,
    team_name: str,
    week: int,
    roster_df: pd.DataFrame,
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
    saved: dict[str, Any] | None = None,
) -> TeamHeaderModel:
    league_name = ""
    if isinstance(context, dict):
        league_name = str(
            context.get("display_name")
            or (context.get("metadata") or {}).get("league_name")
            or (context.get("metadata") or {}).get("draft_name")
            or ""
        ).strip()
    filled = sum(1 for label in slot_labels if str(assignments.get(label.key) or "").strip())
    saved_at = str((saved or {}).get("saved_at") or "").strip()
    my_team = str((context or {}).get("my_team_name") or "").strip()
    return TeamHeaderModel(
        team_name=str(team_name or my_team or "—").strip() or "—",
        league_name=league_name or "Active league",
        week=int(week),
        week_label=f"Week {int(week)}",
        roster_count=len(roster_player_names(roster_df)),
        filled_starters=filled,
        total_starter_slots=len(slot_labels),
        is_active_team=bool(my_team and team_name and my_team == team_name),
        last_saved_at=saved_at,
    )


def emit_html_block(st: Any, html: str) -> None:
    """Render raw HTML via st.html when available, else markdown fallback."""
    body = str(html or "")
    if not body.strip():
        return
    if hasattr(st, "html"):
        try:
            st.html(body)
            return
        except Exception:
            pass
    st.markdown(body, unsafe_allow_html=True)


def render_roster_board_html(
    slot_labels: list,
    assignments: dict[str, str],
    team_roster: pd.DataFrame,
    *,
    scored_roster: pd.DataFrame | None = None,
    validation_styles: dict[str, str] | None = None,
) -> str:
    """Single HTML block for starters + bench roster board."""
    slot_cards = build_slot_cards(
        slot_labels,
        assignments,
        team_roster,
        scored_roster=scored_roster,
        validation_styles=validation_styles,
    )
    bench_cards = bench_player_cards(
        team_roster,
        assignments,
        slot_labels,
        scored_roster=scored_roster,
    )
    return (
        '<div class="fl-roster-shell">'
        f'{render_starting_lineup_board_html(slot_cards)}'
        f'{render_bench_section_html(bench_cards)}'
        "</div>"
    )


def inject_lineup_board_styles(st: Any) -> None:
    """Scoped CSS for Fantasy Lineup roster board only."""
    try:
        from player_photos import inject_player_photo_styles

        inject_player_photo_styles(st)
    except ImportError:
        pass
    css = """
<style>
.fl-team-header {
    border: 1px solid rgba(15, 23, 42, 0.12);
    border-radius: 14px;
    padding: 16px 18px;
    margin: 0 0 16px 0;
    background: linear-gradient(135deg, rgba(11, 61, 110, 0.06), rgba(255,255,255,0.02));
}
.fl-team-name { font-size: 1.45rem; font-weight: 800; color: #0b3d6e; line-height: 1.2; }
.fl-league-name { font-size: 0.95rem; color: #475569; margin-top: 2px; }
.fl-team-meta { font-size: 0.84rem; color: #64748b; margin-top: 8px; }
.fl-active-badge {
    display: inline-block; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; color: #166534; background: #dcfce7; border-radius: 999px;
    padding: 2px 8px; margin-left: 6px; vertical-align: middle;
}
.fl-last-saved { font-size: 0.78rem; color: #64748b; margin-top: 6px; }
.fl-section-title {
    font-size: 1.05rem; font-weight: 800; color: #0f172a; margin: 18px 0 10px 0;
}
.fl-slot-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 12px;
    margin: 8px 0 16px 0;
}
.fl-slot-card {
    border-radius: 12px;
    padding: 12px;
    min-height: 132px;
    background: #ffffff;
    border: 1px solid rgba(15, 23, 42, 0.10);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.fl-slot-open {
    border: 2px dashed #cbd5e1;
    background: #f8fafc;
}
.fl-slot-invalid { border-color: #fca5a5; background: #fff7f7; }
.fl-slot-filled { border-color: rgba(11, 61, 110, 0.18); }
.fl-slot-badge {
    display: inline-block; font-size: 0.72rem; font-weight: 800; letter-spacing: 0.05em;
    color: #0b3d6e; background: #e0f2fe; border-radius: 6px; padding: 2px 7px;
}
.fl-slot-pos-name { font-size: 0.76rem; color: #64748b; margin-top: 4px; }
.fl-slot-open-label { font-size: 0.95rem; font-weight: 700; color: #475569; margin-top: 14px; }
.fl-slot-open-hint { font-size: 0.78rem; color: #94a3b8; margin-top: 4px; }
.fl-player-card { display: flex; gap: 10px; align-items: flex-start; margin-top: 10px; }
.fl-player-photo {
    width: 56px; height: 56px; border-radius: 50%; object-fit: cover; flex-shrink: 0;
    border: 2px solid rgba(11, 61, 110, 0.22); background: #edf2f7;
}
.fl-photo-fallback {
    display: flex; align-items: center; justify-content: center; position: relative;
    color: #64748b; overflow: hidden;
}
.fl-photo-fallback-icon { font-size: 1.1rem; opacity: 0.55; position: absolute; }
.fl-photo-initials { font-size: 0.78rem; font-weight: 800; z-index: 1; }
.fl-player-meta { min-width: 0; flex: 1; }
.fl-player-name { font-size: 0.95rem; font-weight: 800; color: #0f172a; line-height: 1.2; }
.fl-player-team { font-size: 0.76rem; color: #64748b; margin-top: 2px; }
.fl-player-pos { font-size: 0.74rem; color: #475569; margin-top: 2px; }
.fl-player-stats {
    font-size: 0.74rem; color: #334155; margin-top: 4px;
    line-height: 1.35; overflow-wrap: anywhere; word-break: normal;
}
.fl-player-rec { font-size: 0.72rem; font-weight: 700; color: #0b3d6e; margin-top: 4px; }
.fl-slot-state-invalid { font-size: 0.72rem; font-weight: 700; color: #b91c1c; margin-top: 6px; }
.fl-bench-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
    margin: 8px 0 16px 0;
}
.fl-bench-card {
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 10px;
    padding: 10px;
    background: #fafbfc;
}
.fl-action-bar {
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 12px;
    padding: 12px 14px;
    background: #f8fafc;
    margin: 12px 0;
}
.fl-action-metrics { display: flex; flex-wrap: wrap; gap: 10px 16px; font-size: 0.82rem; color: #334155; }
.fl-validation-list { margin: 8px 0 0 0; padding-left: 18px; font-size: 0.82rem; color: #475569; }
.fl-roster-shell { display: block; width: 100%; margin: 0 0 12px 0; }
@media (max-width: 768px) {
    .fl-slot-grid { grid-template-columns: 1fr; }
    .fl-bench-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .fl-player-photo { width: 52px; height: 52px; }
    .fl-team-name { font-size: 1.25rem; }
}
@media (max-width: 420px) {
    .fl-bench-grid { grid-template-columns: 1fr; }
}
</style>
"""
    emit_html_block(st, css)


def render_team_header_html(model: TeamHeaderModel) -> str:
    active = '<span class="fl-active-badge">Your active team</span>' if model.is_active_team else ""
    saved = ""
    if model.last_saved_at:
        saved = '<div class="fl-last-saved">Previously saved</div>'
    league = html_lib.escape(model.league_name)
    team = html_lib.escape(model.team_name)
    return (
        f'<div class="fl-team-header">'
        f'<div class="fl-team-name">{team}{active}</div>'
        f'<div class="fl-league-name">{league}</div>'
        f'<div class="fl-team-meta">'
        f'{html_lib.escape(model.week_label)} · '
        f'{model.filled_starters}/{model.total_starter_slots} positions filled'
        f'</div>{saved}</div>'
    )


def _render_player_card_inner(card: PlayerCardModel) -> str:
    team = html_lib.escape(card.mlb_team) if card.mlb_team else "—"
    rec = (
        f'<div class="fl-player-rec">{html_lib.escape(card.recommendation)}</div>'
        if card.recommendation
        else ""
    )
    stats = html_lib.escape(card.stat_line) if card.stat_line else "—"
    return (
        f'<div class="fl-player-card">'
        f'{card.photo_html}'
        f'<div class="fl-player-meta">'
        f'<div class="fl-player-name">{html_lib.escape(card.player_name)}</div>'
        f'<div class="fl-player-team">{team}</div>'
        f'<div class="fl-player-pos">{html_lib.escape(card.positions)}</div>'
        f'<div class="fl-player-stats">{stats}</div>{rec}'
        f'</div></div>'
    )


def render_slot_card_html(card: SlotCardModel) -> str:
    state_class = f"fl-slot-{card.state}" if card.state in ("open", "invalid", "filled") else "fl-slot-filled"
    badge = html_lib.escape(card.badge)
    pos_name = html_lib.escape(card.position_name)
    if card.state == "open" or card.player is None:
        return (
            f'<div class="fl-slot-card {state_class}">'
            f'<span class="fl-slot-badge">{badge}</span>'
            f'<div class="fl-slot-pos-name">{pos_name}</div>'
            f'<div class="fl-slot-open-label">Open slot</div>'
            f'<div class="fl-slot-open-hint">Choose player or add from bench</div>'
            f'</div>'
        )
    invalid_note = (
        '<div class="fl-slot-state-invalid">Ineligible or not on roster</div>'
        if card.state == "invalid"
        else ""
    )
    return (
        f'<div class="fl-slot-card {state_class}">'
        f'<span class="fl-slot-badge">{badge}</span>'
        f'<div class="fl-slot-pos-name">{pos_name}</div>'
        f'{_render_player_card_inner(card.player)}{invalid_note}'
        f'</div>'
    )


def render_starting_lineup_board_html(cards: list[SlotCardModel]) -> str:
    if not cards:
        return ""
    cells = "".join(render_slot_card_html(card) for card in cards)
    return f'<div class="fl-section-title">Starting Lineup</div><div class="fl-slot-grid">{cells}</div>'


def render_bench_section_html(cards: list[PlayerCardModel]) -> str:
    if not cards:
        return (
            '<div class="fl-section-title">Bench</div>'
            '<div class="fl-slot-open-hint">All roster players are in the starting lineup.</div>'
        )
    cells = []
    for card in cards:
        cells.append(f'<div class="fl-bench-card">{_render_player_card_inner(card)}</div>')
    return f'<div class="fl-section-title">Bench</div><div class="fl-bench-grid">{"".join(cells)}</div>'


def render_action_metrics_html(
    *,
    validation: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    open_slots = summary.get("open_slots") or []
    bench = summary.get("bench") or []
    valid_ok = "Valid" if validation.get("ok") else "Needs fixes"
    return (
        f'<div class="fl-action-bar"><div class="fl-action-metrics">'
        f'<span><strong>Validation:</strong> {html_lib.escape(valid_ok)}</span>'
        f'<span><strong>Filled:</strong> {len(summary.get("starters") or [])}</span>'
        f'<span><strong>Open slots:</strong> {len(open_slots)}</span>'
        f'<span><strong>Bench:</strong> {len(bench)}</span>'
        f'</div></div>'
    )


def roster_names_for_team(roster_df: pd.DataFrame, team_name: str) -> set[str]:
    if roster_df is None or roster_df.empty:
        return set()
    col = _player_name_col(roster_df)
    team_col = "Team" if "Team" in roster_df.columns else None
    names: set[str] = set()
    for _, row in roster_df.iterrows():
        if team_col and str(row.get(team_col) or "").strip() != str(team_name or "").strip():
            continue
        name = str(row.get(col) or "").strip()
        if name:
            names.add(name)
    return names
