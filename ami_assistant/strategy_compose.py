"""A1 answers for ``my_strategy``: the user's own saved strategies and Global Queue, quoted exactly.

Rules:
* Only what the tools returned: ranks, positions, pins, notes and research the user saved. Nothing
  is inferred, and no statistics are added.
* Saved information comes first. Unsaved editor changes are always labelled as unsaved and kept apart.
* Players are matched against the strategy's own entries. A player that isn't there is said to be
  not there, never guessed.
* Player names, not gendered pronouns.
"""

from __future__ import annotations

import re
from typing import Any

from ami_assistant import strategy_router as sr
from ami_assistant.tools import strategy as ts
from ami_assistant.tools.registry import NOT_ENTITLED, ToolResult

LIST_LIMIT = 15
NOTE_LIST_LIMIT = 10
_FALLBACK_LABELS = {
    "balanced": "Balanced (recommended)", "best_available": "Best player available",
    "value_based": "Value-based (value vs. draft cost)", "positional_scarcity": "Positional scarcity",
    "roster_aware": "Roster-aware (fill your needs)",
}
POSITION_PLURAL = {"C": "catchers", "1B": "first basemen", "2B": "second basemen", "3B": "third basemen",
                   "SS": "shortstops", "OF": "outfielders", "DH": "designated hitters", "SP": "starting pitchers",
                   "RP": "relief pitchers", "P": "pitchers", "LF": "left fielders", "CF": "center fielders",
                   "RF": "right fielders"}
_OUTFIELD = {"LF", "CF", "RF", "OF"}


def _approach_label(key: str) -> str:
    try:
        from draft_strategy_pro_ui import APPROACH_LABELS

        return APPROACH_LABELS.get(key, key)
    except Exception:
        return _FALLBACK_LABELS.get(key, key or "—")


_key = ts.player_key
find_entry = ts.find_entry


def _positions(entry: dict[str, Any]) -> set[str]:
    return {p.strip().upper() for p in re.split(r"[/,\s]+", str(entry.get("position") or "")) if p.strip()}


def _plays(entry: dict[str, Any], position: str) -> bool:
    pos = _positions(entry)
    if position == "OF":
        return bool(pos & _OUTFIELD)
    if position == "P":
        return bool(pos & {"P", "SP", "RP"})
    return position in pos


def _player_line(e: dict[str, Any]) -> str:
    bits = [f"{e['rank']}. **{e['name']}**"]
    if e.get("position"):
        bits.append(e["position"])
    text = " · ".join(bits)
    if e.get("pinned"):
        text += " · 📌 pinned"
    if e.get("note"):
        text += " · has a note"
    return text


def _ranks(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {_key(e["name"]): e["rank"] for e in entries}


class StrategyComposer:
    def __init__(self, plan: Any, results: dict[str, list[ToolResult]], question: str) -> None:
        self.plan = plan
        self.results = results
        self.question = question

    def _result(self) -> ToolResult | None:
        for calls in self.results.values():
            if calls:
                return calls[0]
        return None

    # ---- entry point ------------------------------------------------------------------
    def compose(self) -> str:
        res = self._result()
        if res is None:
            return "I couldn't read your strategies just now."
        if not res.ok:
            return self._failure(res)
        if res.tool == "list_my_strategies":
            return self._list(res.data)
        if res.tool == "compare_strategy_to_global":
            return self._diff(res.data)
        if res.tool == "get_global_list":
            return self._global(res.data)
        return self._strategy(res.data)

    @staticmethod
    def _failure(res: ToolResult) -> str:
        names = res.data.get("candidates") or []
        if res.error_code == ts.WHICH_STRATEGY:
            return res.message + (" Your strategies: " + "; ".join(f"**{n}**" for n in names[:8]) + "." if names else "")
        if res.error_code == ts.UNKNOWN_STRATEGY:
            return res.message + (" Your strategies: " + "; ".join(f"**{n}**" for n in names[:8]) + "." if names else "")
        if res.error_code == ts.NO_STRATEGIES:
            return (res.message + " Create one on **Draft Strategy · PRO**: start empty or from a copy of your "
                    "Global Queue.")
        if res.error_code == NOT_ENTITLED:
            return res.message + " Your Global Queue stays free; see **Pricing & Upgrade** to compare plans."
        if res.error_code == ts.SIGN_IN_REQUIRED:
            return "Sign in to use your saved Draft Strategies. Your Global Queue works without an account."
        return res.message or "I couldn't read your strategies just now; nothing was changed."

    # ---- list -------------------------------------------------------------------------
    def _list(self, d: dict[str, Any]) -> str:
        rows = d.get("strategies") or []
        if not rows and not d.get("never_saved_open"):
            return ("You don't have any saved Draft Strategies yet. Create one on **Draft Strategy · PRO**: start "
                    "empty or from a copy of your Global Queue.")
        lines = [f"You have {len(rows)} saved strateg{'y' if len(rows) == 1 else 'ies'}:"]
        for r in rows:
            tags = [f"{r['players']} player{'' if r['players'] == 1 else 's'}"]
            if r.get("selected"):
                tags.append("selected")
            if r.get("unsaved_changes"):
                tags.append("unsaved changes in the editor")
            lines.append(f"- **{r['name']}** · " + " · ".join(tags))
        if d.get("never_saved_open"):
            lines.append(f"- **{d['never_saved_open']}** · open in the editor, not saved yet")
        return "\n".join(lines)

    # ---- one strategy -----------------------------------------------------------------
    def _strategy(self, d: dict[str, Any]) -> str:
        saved, unsaved = d.get("saved"), d.get("unsaved")
        focus = self.plan.focus or sr.F_SUMMARY
        lead: list[str] = []
        if d.get("open_strategy_missing"):
            lead.append("_The strategy that was open in the editor is no longer saved (it may have been deleted), "
                        "so I didn't use it._")
        if saved is None and isinstance(unsaved, dict):  # a new strategy that was never saved
            body = self._focus(unsaved, focus, d, label="in the editor (not saved yet)", research=[])
            return "\n\n".join(lead + [f"**{unsaved['name']}** hasn't been saved yet. This is what's in the editor "
                                       "(unsaved):", body])
        body = self._focus(saved, focus, d, label="saved", research=d.get("research") or [])
        tail = self._unsaved_tail(saved, unsaved, focus) if isinstance(unsaved, dict) else ""
        return "\n\n".join(x for x in lead + [body, tail] if x)

    def _who(self, view: dict[str, Any], d: dict[str, Any], label: str = "") -> str:
        """``**Power** (selected, saved)``: how it was chosen and whether this is the saved version."""
        how = {"selected": "selected", "only_one": "your only strategy"}.get(d.get("chosen_by", ""), "")
        tags = ", ".join(t for t in (how, label) if t)
        return f"**{view['name']}**" + (f" ({tags})" if tags else "")

    def _focus(self, view: dict[str, Any], focus: str, d: dict[str, Any], *, label: str,
               research: list[dict[str, Any]]) -> str:
        entries = view["entries"]
        who = self._who(view, d, label)
        subject = self.plan.subject
        if focus in (sr.F_RANK, sr.F_MEMBER) or (focus == sr.F_NOTE and subject):
            entry = find_entry(subject, entries, self.question)
            typed = subject or "that player"
            if entry is None and d.get("elsewhere"):
                typed = d["elsewhere"][0]["name"]  # the spelling the user saved
            if focus == sr.F_NOTE:
                return self._note_one(entry, typed, who, research, label, d.get("elsewhere") or [])
            if entry is None:
                if not subject:
                    return f"Which player? I can check any player in {who}."
                return f"**{typed}** isn't in {who}." + self._elsewhere(d.get("elsewhere") or [], note=False)
            pin = " It's pinned." if entry.get("pinned") else ""
            if focus == sr.F_MEMBER:
                return f"Yes: **{entry['name']}** is #{entry['rank']} of {len(entries)} in {who}.{pin}"
            return f"You ranked **{entry['name']}** #{entry['rank']} of {len(entries)} in {who}.{pin}"
        if focus == sr.F_NOTE:
            notes = [e for e in entries if e.get("note")]
            if not notes:
                return f"You haven't saved any player notes in {who}."
            lines = [f"Your player notes in {who}:"]
            lines += [f"- **{e['name']}** (#{e['rank']}): “{e['note']}”" for e in notes[:NOTE_LIST_LIMIT]]
            if len(notes) > NOTE_LIST_LIMIT:
                lines.append(f"…and {len(notes) - NOTE_LIST_LIMIT} more.")
            return "\n".join(lines)
        if focus == sr.F_RESEARCH:
            return self._research(research, who, d)
        if focus == sr.F_POSITIONS:
            return self._positions(view, who, label)
        if focus == sr.F_PRIORITIES:
            return self._priorities(view, who, label)
        if focus == sr.F_CONTENTS:
            return self._contents(view, who, label)
        return self._summary(view, who, label, research)

    @staticmethod
    def _elsewhere(rows: list[dict[str, Any]], *, note: bool) -> str:
        if not rows:
            return ""
        bits = []
        for r in rows:
            text = f"**{r['strategy']}** (#{r['rank']} of {r['of']}{', pinned' if r.get('pinned') else ''})"
            if note:
                text += f": “{r['note']}”" if r.get("note") else ": no note saved"
            bits.append(text)
        where = "strategy " if len(rows) == 1 else "strategies "
        return f" **{rows[0]['name']}** is in your saved {where}" + "; ".join(bits) + "."

    def _note_one(self, entry, typed, who, research, label, elsewhere=()) -> str:
        if entry is None:
            return (f"**{typed}** isn't in {who}, so there's no note on that player there."
                    + self._elsewhere(list(elsewhere), note=True))
        lines = []
        if entry.get("note"):
            by = " (saved with AMI after you confirmed it)" if entry.get("note_source") == "ami_confirmed" else ""
            lines.append(f"Your note on **{entry['name']}** in {who}: “{entry['note']}”{by}")
        else:
            lines.append(f"You haven't saved a note on **{entry['name']}** in {who}.")
        key = _key(entry["name"])
        mine = [r for r in research if _key(r.get("player_key")) == key]
        if mine:
            lines.append("Research findings about this player:")
            lines += [f"- {r['at']}: {r['text']}" for r in mine[-5:]]
        return "\n".join(lines)

    def _research(self, research, who, d) -> str:
        if not d.get("research_available", True):
            return f"I couldn't read the research log for {who} just now."
        if not research:
            return f"You haven't saved any research findings in {who} yet."
        lines = [f"Research saved in {who} (newest last):"]
        lines += [f"- {r['at']} · {r['kind'] or 'note'}: {r['text']}" for r in research[-10:]]
        return "\n".join(lines)

    def _contents(self, view, who, label) -> str:
        entries = view["entries"]
        if not entries:
            return f"{who} has no players yet."
        lines = [f"{who} has {len(entries)} player{'s' if len(entries) != 1 else ''}:"]
        lines += [_player_line(e) for e in entries[:LIST_LIMIT]]
        if len(entries) > LIST_LIMIT:
            lines.append(f"…and {len(entries) - LIST_LIMIT} more (see **Draft Strategy · PRO** for the full list).")
        return "\n".join(lines)

    def _positions(self, view, who, label) -> str:
        pos = self.plan.position
        entries = view["entries"]
        plural = POSITION_PLURAL.get(pos, f"{pos} players")
        hits = [e for e in entries if _plays(e, pos)]
        unknown = sum(1 for e in entries if not _positions(e))
        if hits:
            names = ", ".join(f"{e['name']} (#{e['rank']})" for e in hits[:12])
            text = f"{who} has {len(hits)} {plural if len(hits) != 1 else plural.rstrip('s')}: {names}."
        else:
            text = f"{who} has no {plural}."
        if unknown:
            text += (f" {unknown} player{'s have' if unknown != 1 else ' has'} no position recorded in the strategy, "
                     "so they aren't counted.")
        return text

    def _priorities(self, view, who, label) -> str:
        prefs = view.get("preferences") or {}
        entries = view["entries"]
        lines = [f"What you saved in {who}:" if label == "saved" else f"What's in {who}:",
                 f"- **Ranking approach:** {_approach_label(view.get('approach') or '')}"]
        cats = prefs.get("category_priorities") or []
        lines.append(f"- **Category priorities:** {', '.join(cats)}" if cats else "- **Category priorities:** none set")
        if prefs.get("ranking_note"):
            lines.append(f"- **Ranking note:** “{prefs['ranking_note']}”")
        pinned = [e["name"] for e in entries if e.get("pinned")]
        if pinned:
            lines.append(f"- **Pinned:** {', '.join(pinned[:10])}")
        top = entries[:10]
        mix: dict[str, int] = {}
        for e in top:
            for p in sorted(_positions(e)) or ["no position"]:
                mix[p] = mix.get(p, 0) + 1
        if top:
            mix_txt = ", ".join(f"{n} {p}" for p, n in sorted(mix.items(), key=lambda kv: (-kv[1], kv[0])))
            lines.append(f"- **Positions in your top {len(top)}:** {mix_txt}")
        lines.append("_This is what you saved; I haven't added anything to it._")
        return "\n".join(lines)

    def _summary(self, view, who, label, research) -> str:
        entries = view["entries"]
        notes = sum(1 for e in entries if e.get("note"))
        pins = sum(1 for e in entries if e.get("pinned"))
        lines = [f"{who}: {len(entries)} player{'s' if len(entries) != 1 else ''} · {pins} pinned · "
                 f"{notes} note{'s' if notes != 1 else ''} · {len(research)} research entr{'y' if len(research) == 1 else 'ies'} · "
                 f"approach {_approach_label(view.get('approach') or '')}."]
        if entries:
            lines.append("Top of the queue: " + ", ".join(f"{e['rank']}. {e['name']}" for e in entries[:5]) + ".")
        return "\n".join(lines)

    def _unsaved_tail(self, saved: dict[str, Any], unsaved: dict[str, Any], focus: str) -> str:
        s_entries, u_entries = saved["entries"], unsaved["entries"]
        head = "**Unsaved changes in the editor** (not saved yet):"
        if focus in (sr.F_RANK, sr.F_MEMBER, sr.F_NOTE) and self.plan.subject:
            s_e = find_entry(self.plan.subject, s_entries, self.question)
            u_e = find_entry(self.plan.subject, u_entries, self.question)
            if focus == sr.F_NOTE:
                if (s_e or {}).get("note") != (u_e or {}).get("note") and u_e is not None:
                    return f"{head} the note on **{u_e['name']}** reads “{u_e.get('note') or '(no note)'}”."
                return ""
            if (s_e or {}).get("rank") == (u_e or {}).get("rank"):
                return ""
            if u_e is None:
                return f"{head} **{s_e['name']}** has been removed." if s_e else ""
            return f"{head} **{u_e['name']}** is #{u_e['rank']} of {len(u_entries)}."
        s_names, u_names = [e["name"] for e in s_entries], [e["name"] for e in u_entries]
        if s_names == u_names and [e.get("note") for e in s_entries] == [e.get("note") for e in u_entries] \
                and [e.get("pinned") for e in s_entries] == [e.get("pinned") for e in u_entries] \
                and saved.get("preferences") == unsaved.get("preferences") and saved.get("approach") == unsaved.get("approach"):
            return f"{head} other edits (not to the queue, notes, pins or preferences)."
        bits = []
        added = [n for n in u_names if n not in s_names]
        removed = [n for n in s_names if n not in u_names]
        if added:
            bits.append("added " + ", ".join(added[:8]))
        if removed:
            bits.append("removed " + ", ".join(removed[:8]))
        if not added and not removed and s_names != u_names:
            bits.append("the order changed")
        s_notes = {_key(e["name"]): e.get("note") or "" for e in s_entries}
        u_notes = {_key(e["name"]): e.get("note") or "" for e in u_entries}
        if any(s_notes[k] != u_notes[k] for k in s_notes.keys() & u_notes.keys()):
            bits.append("notes changed")
        if {_key(e["name"]) for e in s_entries if e.get("pinned")} != {_key(e["name"]) for e in u_entries if e.get("pinned")}:
            bits.append("pins changed")
        if saved.get("preferences") != unsaved.get("preferences") or saved.get("approach") != unsaved.get("approach"):
            bits.append("preferences changed")
        return f"{head} {len(u_names)} players; " + "; ".join(bits or ["other edits"]) + "."

    # ---- Global Queue / comparison ----------------------------------------------------
    def _global(self, d: dict[str, Any]) -> str:
        entries = d.get("entries") or []
        who = "your **Global Queue**"
        src = f" It was loaded from **{d['loaded_from']}**." if d.get("loaded_from") else ""
        focus = self.plan.focus
        if focus in (sr.F_RANK, sr.F_MEMBER, sr.F_NOTE) and (self.plan.subject or entries):
            entry = find_entry(self.plan.subject, entries, self.question)
            typed = self.plan.subject or "that player"
            if entry is None:
                return f"**{typed}** isn't in {who}." if self.plan.subject else f"Which player? I can check {who}."
            if focus == sr.F_NOTE:
                return (f"Your Global Queue note on **{entry['name']}**: “{entry['note']}”." if entry.get("note")
                        else f"You haven't saved a Global Queue note on **{entry['name']}**.")
            return f"**{entry['name']}** is #{entry['rank']} of {len(entries)} in {who}." + src
        if not entries:
            return f"{who[0].upper() + who[1:]} is empty." + src
        lines = [f"{who[0].upper() + who[1:]} has {len(entries)} player{'s' if len(entries) != 1 else ''}.{src}"]
        lines += [_player_line(e) for e in entries[:LIST_LIMIT]]
        if len(entries) > LIST_LIMIT:
            lines.append(f"…and {len(entries) - LIST_LIMIT} more.")
        return "\n".join(lines)

    def _diff(self, d: dict[str, Any]) -> str:
        name = f"**{d['strategy']}**"
        label = "not saved yet" if d.get("never_saved") else "saved"
        lines = [f"{name} ({label}, {d['strategy_size']} players) vs your **Global Queue** ({d['global_size']} players):"]
        if not d["only_strategy"] and not d["only_global"]:
            lines.append("- Same players" + (", in the same order." if d.get("same_order") else ", in a different order."))
        if d["only_strategy"]:
            lines.append(f"- Only in {name} ({len(d['only_strategy'])}): " + ", ".join(d["only_strategy"][:10])
                         + ("…" if len(d["only_strategy"]) > 10 else ""))
        if d["only_global"]:
            lines.append(f"- Only in the Global Queue ({len(d['only_global'])}): " + ", ".join(d["only_global"][:10])
                         + ("…" if len(d["only_global"]) > 10 else ""))
        moved = [b for b in d["both"] if b["strategy_rank"] != b["global_rank"]]
        if d["both"]:
            lines.append(f"- In both: {len(d['both'])}" + (f"; ranked differently: " + ", ".join(
                f"{b['name']} (#{b['strategy_rank']} vs #{b['global_rank']})" for b in moved[:5]) if moved else ""))
        if d.get("unsaved_changes"):
            lines.append("_This compares the saved strategy; you also have unsaved edits in the editor._")
        lines.append("_Nothing was changed. Copying between them is done on purpose in the strategy's Transfer tab._")
        return "\n".join(lines)


def compose_my_strategy(plan: Any, results: dict[str, list[ToolResult]], question: str = "") -> str:
    return StrategyComposer(plan, results, question).compose()
