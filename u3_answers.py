"""Plain-language answers for the U3 league pages (Lineup, Trade Center). Pure functions, no Streamlit.

Same rules as ``u1_answers`` / ``u2_answers``: every sentence comes from values the page
already computed (the canonical lineup validation, the lineup record's status, the trade
engine's own verdict and roster checks). Nothing here scores a player, picks a lineup or
judges a trade on its own.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from u2_answers import _join, _plural

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

