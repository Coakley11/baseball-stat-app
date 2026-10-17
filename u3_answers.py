"""Plain-language answers for the U3 league pages (Lineup, Trade Center). Pure functions, no Streamlit.

Same rules as ``u1_answers`` / ``u2_answers``: every sentence comes from values the page
already computed (the canonical lineup validation, the lineup record's status, the trade
engine's own verdict and roster checks). Nothing here scores a player, picks a lineup or
judges a trade on its own.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from u2_answers import _join, _plural

# The trade engine's own three-way classification (evaluate_trade: need-weighted gain > 2 /
# < -2 / otherwise), in plain words. A roster problem for your team overrides it in the label.
TRADE_VALUE_LABELS = {
    "Good for your team": "Favors your team",
    "Bad for your team": "Favors the other team",
    "Neutral": "Balanced",
}
TRADE_VALUE_THRESHOLD = 2  # evaluate_trade's cut-off, quoted in the explanation
ROSTER_ISSUE_LABEL = "Creates roster issue"


def lineup_answer(
    *,
    team: str,
    week_text: str,
    slots: Sequence[tuple[str, str]],
    assignments: Mapping[str, str],
    validation: Mapping[str, Any],
    bench_count: int,
    locked: bool,
    record_status: str = "",
    edit_message: str = "",
    proxy: bool = False,
) -> dict[str, Any]:
    """The Lineup page's answer: is this week's lineup complete, what is missing, is it saved.

    ``slots``: (slot key, display label) in board order. ``validation``: the result of
    ``validate_weekly_lineup`` for these assignments (the same rule Save enforces).
    ``record_status``: the saved record's status ("draft" while you build, "locked" after
    Save Lineup). ``edit_message``: the page's own editability line for the week."""
    total = len(slots)
    open_labels = [label for key, label in slots if not str(assignments.get(key) or "").strip()]
    filled = total - len(open_labels)
    unfillable = list(validation.get("unfillable_slots") or [])
    ineligible = [f"{i.get('player')} at {i.get('slot')}" for i in (validation.get("ineligible_slots") or []) if isinstance(i, Mapping)]
    duplicates = list(validation.get("duplicate_players") or [])

    if locked:
        status = "Saved and locked" if record_status == "locked" else "Locked"
        status_tile = ("Locked", "saved" if record_status == "locked" else "")
    elif record_status == "draft":
        status = "Draft (not submitted)"
        status_tile = ("Draft", "not submitted")
    else:
        status = "Not saved yet"
        status_tile = ("Not saved", "")

    tone = ""
    if ineligible or duplicates:
        n = len(ineligible) + len(duplicates)
        headline = f"Fix {_plural(n, 'starter')} before saving"
        tone = "warn"
    elif open_labels and len(open_labels) > len(unfillable):
        headline = f"{_plural(len(open_labels), 'starting spot')} open: {_join(open_labels)}"
        tone = "warn"
    elif open_labels:
        headline = f"{filled} of {total} starters set; this roster has no one for {_join(open_labels)}"
        tone = "warn"
    elif locked:
        headline = f"Lineup {'saved and locked' if record_status == 'locked' else 'locked'}: {filled} of {total} starters"
        tone = "good"
    else:
        headline = f"Lineup complete: {filled} of {total} starters set"
        tone = "good"

    parts = []
    if edit_message:
        parts.append(edit_message.rstrip(".") + ".")
    if not locked:
        if ineligible or duplicates:
            parts.append("Save Lineup stays off until every starter is eligible for their spot.")
        elif open_labels and len(open_labels) > len(unfillable):
            parts.append("Drag a bench player into each open spot, or use the suggested lineup.")
        elif open_labels:
            parts.append("Those spots score nothing this week. Check waivers for an eligible player.")
        if record_status == "draft":
            parts.append("Your changes are kept as a draft; press Save Lineup to submit and lock them.")
        else:
            parts.append("Nothing is submitted until you press Save Lineup.")
    body = " ".join(parts)

    chips = [(f"{label} open", "warn") for label in open_labels]
    chips += [(f"{p} not eligible", "warn") for p in ineligible]
    chips += [(f"{p} assigned twice", "warn") for p in duplicates]
    tiles = [
        ("Starters", f"{filled}/{total}", ""),
        ("Open", str(len(open_labels)), ", ".join(open_labels[:3]) + ("…" if len(open_labels) > 3 else "")),
        ("Bench", str(int(bench_count)), ""),
        ("Status", *status_tile),
    ]
    kicker = f"{'Commissioner acting for ' if proxy else ''}{team} · {week_text}"
    # The obvious next step: fill from the roster, else look on waivers, else (complete) Save.
    if locked:
        primary = ""
    elif ineligible or duplicates or len(open_labels) > len(unfillable):
        primary = "suggest"
    elif open_labels:
        primary = "waivers"
    else:
        primary = "save"
    return {"headline": headline, "body": body, "tone": tone, "kicker": kicker, "tiles": tiles,
            "chips": chips, "status": status, "primary": primary,
            "complete": not open_labels and not ineligible and not duplicates}


def _fmt_change(cat: str, value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if cat in ("BA", "AVG", "OBP", "SLG", "OPS"):
        text = f"{abs(v):.3f}"
        text = text[1:] if text.startswith("0.") else text
    else:
        text = f"{abs(v):.0f}" if abs(v - round(v)) < 1e-9 else f"{abs(v):.1f}"
    if not text.strip("0."):
        return "0"
    return ("+" if v > 0 else "−") + text


def trade_verdict(
    analysis: Mapping[str, Any],
    *,
    my_team: str,
    partner: str = "",
    roster_issues: Sequence[Mapping[str, Any]] = (),
    format_change: Callable[[str, Any], str] | None = None,
) -> dict[str, Any]:
    """Verdict card for an analyzed trade, from the trade engine's own output.

    ``analysis``: ``build_trade_analysis_package`` (verdict, weighted_gain, category_rows,
    helps/hurts, positions, player rows). ``roster_issues``: ``trade_roster_issues`` for this
    trade; an issue on your own roster makes the label "Creates roster issue". No overall
    judgment beyond the engine's classification is added."""
    fmt = format_change or _fmt_change
    value_label = TRADE_VALUE_LABELS.get(str(analysis.get("verdict") or ""), "")
    try:
        gain = float(analysis.get("weighted_gain") or 0.0)
    except (TypeError, ValueError):
        gain = 0.0
    # A required slot you can no longer fill, or going over the roster size, is a roster issue.
    # Open roster spots ("under") are only noted: a waiver add fills them.
    mine = [i for i in roster_issues if str(i.get("team") or "") == my_team and i.get("kind") in ("slot", "over")]
    theirs = [i for i in roster_issues if i not in mine]
    other = partner or "the other team"

    label = ROSTER_ISSUE_LABEL if mine else (value_label or "Analysis")
    if mine:
        tone = "warn"
    elif value_label == "Favors your team":
        tone = "good"
    elif value_label == "Favors the other team":
        tone = "warn"
    else:
        tone = ""

    t = TRADE_VALUE_THRESHOLD
    body = (f"Category value difference {gain:+.1f} for you (current-season totals; categories your team needs "
            f"count 1.5×). Above +{t} favors you, below −{t} favors {other}, in between is balanced.")
    if mine and value_label:
        body = f"On value alone: {value_label.lower()}. " + body
    cats = {str(r.get("category") or ""): r.get("change") for r in (analysis.get("category_rows") or [])}
    helps = [c for c in (analysis.get("helps") or []) if c in cats]
    hurts = [c for c in (analysis.get("hurts") or []) if c in cats]
    chips = [(f"{c} {fmt(c, cats[c])}", "good") for c in helps]
    chips += [(f"{c} {fmt(c, cats[c])}", "warn") for c in hurts]

    gives = [r for r in (analysis.get("player_rows") or []) if r.get("side") == "Give"]
    gets = [r for r in (analysis.get("player_rows") or []) if r.get("side") == "Receive"]
    lost = [str(p) for p in (analysis.get("positions_lost") or []) if str(p).strip()]
    gained = [str(p) for p in (analysis.get("positions_gained") or []) if str(p).strip()]
    tiles = [
        ("Value difference", f"{gain:+.1f}", "need-weighted"),
        ("You give", " · ".join(lost) or "—", _plural(len(gives), "player")),
        ("You receive", " · ".join(gained) or "—", _plural(len(gets), "player")),
        ("Your roster", "OK" if not mine else _plural(len(mine), "issue"), "required slots and size"),
    ]
    return {
        "label": label,
        "value_label": value_label,
        "tone": tone,
        "headline": label if label == value_label or not value_label else f"{label} · value {value_label.lower()}",
        "body": body,
        "chips": chips,
        "tiles": tiles,
        "my_issues": [str(i.get("message") or "") for i in mine],
        "other_notes": [str(i.get("message") or "") for i in theirs],
        "give": gives,
        "receive": gets,
    }
