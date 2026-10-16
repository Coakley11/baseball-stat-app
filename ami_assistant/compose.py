"""Deterministic answer writer: tool results → short, plain-language, grounded markdown.

Every number and reason in an answer is read from a tool result; nothing is computed or
inferred here beyond formatting and choosing which returned fields to mention. Failures use
the tool's own user-facing message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ami_assistant import router as r
from ami_assistant.capabilities import CAPABILITIES, DEFERRED, DISABLED, FUTURE_ACTIONS, SNAPSHOT
from ami_assistant.data import DATA_SOURCE_LABEL
from ami_assistant.glossary import TERMS
from ami_assistant.tools.registry import ToolResult

RATE = {"BA", "OBP", "SLG", "OPS"}
STAT_NAMES = {
    "G": "games", "AB": "at-bats", "R": "runs", "H": "hits", "2B": "doubles", "3B": "triples", "HR": "home runs",
    "RBI": "RBI", "SB": "stolen bases", "BB": "walks", "BA": "batting average", "OBP": "on-base percentage",
    "SLG": "slugging", "OPS": "OPS",
}
FOCUS_LABEL = {
    "power": "Power here means home runs, slugging and doubles.",
    "speed": "Speed here means stolen bases and triples.",
    "contact": "Contact here means batting average and hits.",
    "patience": "Patience here means walks and on-base percentage.",
    "production": "Run production here means runs and RBI.",
}
TABLE_STATS = ("G", "AB", "HR", "RBI", "R", "SB", "BA", "OBP", "SLG", "OPS")
ACTION_WORDS = {a.key: a.title.lower() for a in FUTURE_ACTIONS}
ACTION_WORDS["app_change"] = "make that change"


@dataclass
class ComposedAnswer:
    text: str
    basis: list[str] = field(default_factory=list)


def fmt(stat: str, value: Any) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if stat in RATE:
        s = f"{v:.3f}"
        return s[1:] if 0 <= v < 1 else s
    return f"{int(round(v)):,}"


def fmt_slope(stat: str, value: Any) -> str:
    if value is None:
        return "no trend"
    v = float(value)
    if stat in RATE:
        s = f"{abs(v):.3f}".lstrip("0") or ".000"
        return f"{'+' if v >= 0 else '−'}{s} {stat} per season"
    return f"{'+' if v >= 0 else '−'}{abs(v):.1f} {stat} per season"


def ordinal(n: float | int | None) -> str:
    if n is None:
        return "—"
    k = int(round(float(n)))
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suffix}"


def span(rng: Any) -> str:
    if not rng:
        return ""
    lo, hi = int(rng[0]), int(rng[1])
    return str(lo) if lo == hi else f"{lo}–{hi}"


def score_text(key: str, value: float) -> str:
    """Draft scores as the pages show them: Roster Fit to 2 places, the 0–100 scores to 1."""
    return f"{value:.2f}" if key == "Roster Fit Score" else f"{value:.1f}"


def surname(name: str) -> str:
    parts = str(name or "").split()
    return parts[-1] if parts else str(name)


def _table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(out)


def _first(results: dict[str, list[ToolResult]], name: str) -> ToolResult | None:
    got = results.get(name) or []
    return got[0] if got else None


def _failure(res: ToolResult) -> str:
    text = res.message or "I couldn't get that from the app."
    extra = res.data.get("candidates") or res.data.get("suggestions")
    if extra:
        text += " " + ("Options: " if res.data.get("candidates") else "Did you mean: ") + "; ".join(extra[:5]) + "?"
    return text


class Composer:
    def __init__(self, latest_season: int = 0, first_season: int = 0) -> None:
        self.latest = latest_season
        self.first = first_season
        self.question = ""

    def compose(self, plan: "r.Plan", results: dict[str, list[ToolResult]], question: str = "") -> ComposedAnswer:
        self.question = str(question or "")
        if plan.intent == r.CLARIFY:
            return ComposedAnswer(plan.clarification)
        failed = [res for calls in results.values() for res in calls if not res.ok]
        handler = getattr(self, f"_{plan.intent}", None)
        if failed and plan.intent not in (r.FANTASY, r.ACTION, r.DRAFT_STRATEGY):
            return ComposedAnswer(_failure(failed[0]))
        if handler is None:
            return ComposedAnswer("Could you rephrase that?")
        text = handler(plan, results)
        if plan.notes:
            text += "\n\n" + "\n".join(f"_{n}_" for n in plan.notes)
        return ComposedAnswer(text, self._basis(plan, results))

    # ---- basis line --------------------------------------------------------------
    def _basis(self, plan: "r.Plan", results: dict[str, list[ToolResult]]) -> list[str]:
        if plan.grounding == "app_data" and plan.intent in r.STAT_INTENTS:
            return [f"{DATA_SOURCE_LABEL}, {self.first}–{self.latest} seasons"]
        if plan.intent in (r.DRAFT_NEXT, r.DRAFT_EXPLAIN, r.DRAFT_NEEDS, r.DRAFT_STRATEGY, r.SLEEPERS):
            src = next((res.data.get("source_page") for calls in results.values() for res in calls
                        if res.ok and res.data.get("source_page")), "")
            return [f"Your {src or 'draft page'}'s current recommendations (this session)"]
        if plan.grounding == "product_help":
            return ["Baseball Explorer's page guides and controls"]
        return []

    # ---- help --------------------------------------------------------------------
    def _capabilities(self, plan, results) -> str:
        lines = ["I'm AMI. I answer from this app's own data and explain how to use it — and I never change anything."]
        for cap in CAPABILITIES:
            tag = {SNAPSHOT: " — from your draft pages", DEFERRED: " — coming soon", DISABLED: " — not available; use the app's pages"}.get(cap.status, "")
            lines.append(f"- **{cap.title}**{tag}: e.g. “{cap.examples[0]}”")
        return "\n".join(lines)

    def _help_page(self, plan, results) -> str:
        d = _first(results, "explain_app_page").data
        lines = [f"**{d['page']}** — {d['purpose']}"]
        if d.get("when"):
            lines.append(f"**When to use it:** {d['when']}")
        if d.get("outputs"):
            lines.append(f"**You'll see:** {d['outputs']}")
        if d.get("controls"):
            lines.append("**Main controls:** " + ", ".join(f"“{c}”" for c in d["controls"][:7] if "{" not in c))
        tips = d.get("tips", [])[:3]
        bullets = [f"- {tip}" for tip in tips]
        bullets += [f"- **{t['name']}:** {t['definition']}" for t in d.get("terms", [])[:2]
                    if not any(t["definition"] in tip for tip in tips)]
        if bullets:
            lines.append("\n".join(bullets))
        if d.get("example_questions"):
            lines.append("**Ask me, e.g.:** " + " · ".join(f"“{x}”" for x in d["example_questions"][:2]))
        for step in d.get("next_steps", [])[:1]:
            lines.append(f"**Next:** {step}")
        lines.append(d["navigation"])
        return "\n\n".join(lines)

    def _help_metric(self, plan, results) -> str:
        d = _first(results, "explain_metric").data
        text = f"**{d['term']}** — {d['definition']}"
        if d.get("shown_on"):
            text += f"\n\nYou'll see it on: {', '.join(d['shown_on'])}."
        return text

    def _help_howto(self, plan, results) -> str:
        res = _first(results, "find_feature") or _first(results, "explain_app_page")
        if res is None:
            return plan.clarification or "I don't have step-by-step help for that yet."
        if res.tool == "explain_app_page":
            return self._help_page(plan, {"explain_app_page": [res]})
        d = res.data
        steps = [d["navigation"], *d["steps"]]
        text = f"**{d['task']}** — on **{d['page']}**:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        if d.get("note"):
            text += f"\n\n_{d['note']}_"
        return text

    def _action_request(self, plan, results) -> str:
        what = ACTION_WORDS.get(plan.action, "make that change")
        text = (f"I can't {what} for you — AMI is read-only and never changes drafts, rosters, trades or lineups. "
                "You can do it yourself in the app:")
        res = _first(results, "find_feature") or _first(results, "explain_app_page")
        if res is not None and res.ok:
            if res.tool == "find_feature":
                d = res.data
                steps = [d["navigation"], *d["steps"]]
                text += "\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
            else:
                text += f"\n\n{res.data['navigation']}"
        else:
            where = next((a.ui_path for a in FUTURE_ACTIONS if a.key == plan.action), "")
            text = text.replace(" You can do it yourself in the app:",
                                f" You can do it yourself on **{where}**." if where else " Use the page where you'd normally do it.")
        return text

    def _external_current(self, plan, results) -> str:
        latest = self.latest
        if plan.year_range and plan.year_range[0] > latest:
            return (f"The app's data ends with the {latest} season, so it has nothing for {span(plan.year_range)}. "
                    f"I can answer the same question for {latest} or any earlier season.")
        return (
            "That needs current MLB information, which this app doesn't have — its stats come from the "
            f"Lahman database through the {latest} season, so I won't guess from older numbers. "
            f"I can answer the same question for {latest} or any earlier range "
            f"(for example “Who led in home runs in {latest}?”)."
        )

    # ---- stats -------------------------------------------------------------------
    def _compare(self, plan, results) -> str:
        d = _first(results, "compare_players").data
        players = d["players"]
        names = [p["player"]["name"] for p in players]
        header = f"**{' vs '.join(names)}** — {d['basis']}"
        if plan.focus:
            focus_stats = [s for s in plan.stats if s in d["leaders"]]
        elif plan.stats:
            focus_stats = [s for s in plan.stats if s in d["leaders"]]
        else:
            focus_stats = ["OPS"] if "OPS" in d["leaders"] else []
        by_leader: dict[str, list[str]] = {}
        ties: list[str] = []
        for stat in focus_stats:
            lead = d["leaders"][stat]
            # Leader's value first: "home runs (148 vs 119)".
            ordered = sorted(lead["values"].items(), key=lambda kv: kv[1], reverse=True)
            vals = " vs ".join(fmt(stat, v) for _, v in ordered)
            phrase = f"{STAT_NAMES.get(stat, stat)} ({vals})"
            if lead["leader"]:
                by_leader.setdefault(lead["leader"], []).append(phrase)
            else:
                ties.append(phrase)
        sentences = []
        for leader, phrases in by_leader.items():
            joined = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]
            sentences.append(f"**{leader}** leads in {joined}.")
        if ties:
            sentences.append("Tied in " + ", ".join(ties) + ".")
        stats = [s for s in TABLE_STATS if s in d["stats"] or s in ("G", "AB")]
        if plan.focus or plan.stats:
            stats = ["G", "AB"] + [s for s in plan.stats if s not in ("G", "AB")]
        rows = [[s] + [fmt(s, p["totals"].get(s)) for p in players] for s in stats]
        seasons = [f"{p['player']['name']}: {len(p['seasons'])} season{'s' if len(p['seasons']) != 1 else ''} ({span([min(p['seasons']), max(p['seasons'])])})" for p in players]
        parts = [header]
        if sentences:
            parts.append(" ".join(sentences))
        if plan.focus in FOCUS_LABEL:
            parts.append(f"_{FOCUS_LABEL[plan.focus]}_")
        parts.append(_table([""] + [surname(n) for n in names], rows))
        parts.append("Seasons counted — " + "; ".join(seasons) + ". Rates are recomputed from the summed totals (as on Career Totals).")
        small = [p["player"]["name"] for p in players if p.get("small_sample")]
        if small:
            parts.append(f"_Small sample: {', '.join(small)} had fewer at-bats than the app's qualified minimum for that span._")
        if d.get("range_note"):
            parts.append(f"_{d['range_note']}_")
        return "\n\n".join(parts)

    def _leaderboard(self, plan, results) -> str:
        d = _first(results, "get_leaderboard").data
        stat = d["stat"]
        who = POSITION_PLURAL.get(d.get("position") or "", "hitters")
        head = f"**Top {len(d['rows'])} {who} by {STAT_NAMES.get(stat, stat)}, {span(d['year_range'])}**"
        lines = [head]
        for row in d["rows"]:
            extra = f" ({fmt('AB', row.get('AB'))} AB)" if stat in RATE else ""
            lines.append(f"{row['rank']}. {row['player']} — {fmt(stat, row.get(stat))}{'' if stat in RATE else ' ' + stat}{extra}")
        if not d["rows"]:
            lines.append("No players meet those filters.")
        focus = d.get("focus")
        if focus:
            if focus.get("rank"):
                lines.append(f"\n{focus['player']} ranks **#{focus['rank']}** of {d['pool_size']:,} ({fmt(stat, focus.get(stat))}).")
            else:
                lines.append(f"\n{focus['player']} isn't in this ranking (below the filters or not in range).")
        notes = []
        if d.get("min_ab"):
            label = "the app's qualified minimum for this range" if d.get("qualification") else "your minimum"
            notes.append(f"Minimum {d['min_ab']:,} AB ({label}).")
        if d.get("position"):
            notes.append(f"Position = {d['position_mode']} ({d['position']}), as on Career Totals.")
        notes.append(f"Same calculation as the {d['source_page']} page.")
        if d.get("range_note"):
            notes.append(d["range_note"])
        return "\n".join(lines) + "\n\n_" + " ".join(notes) + "_"

    def _trend_block(self, d: dict[str, Any], stats: list[str]) -> str:
        name = d["player"]["name"]
        trends = {t["stat"]: t for t in d["trends"]}
        lines = [f"**{name} — trends over {span(d['window'])}** ({d['player_window_games']} games)"]
        counts = d.get("direction_counts") or {}
        tracked = len(d["trends"])
        if counts and tracked > 1:
            up, down = counts.get("improving", 0), counts.get("declining", 0)
            verdict = ("mostly improving" if up > down and up >= tracked / 2 else
                       "mostly declining" if down > up and down >= tracked / 2 else "mixed")
            lines.append(f"Overall {verdict}: {up} of {tracked} tracked stats improving, {down} declining, "
                         f"{counts.get('stable', 0)} about flat.")
        if stats:
            chosen = [trends[s] for s in stats if s in trends]
        else:
            strongest = [trends[s] for s in d["strongest"][:3]]
            weakest = [trends[s] for s in d["weakest"][:2] if s not in d["strongest"][:3]]
            chosen = strongest + weakest
        for t in chosen:
            stat = t["stat"]
            seasons = ", ".join(f"{v['season']}: {fmt(stat, v['value'])}" for v in t["by_season"])
            pct = f", {ordinal(t['percentile_in_pool'])} percentile" if t["percentile_in_pool"] is not None else ""
            lines.append(f"- **{stat}** {t['direction']} ({fmt_slope(stat, t['slope_per_season'])}{pct}) — {seasons}")
        if d["player_in_pool"]:
            note = f"_Percentiles compare with the {d['pool_size']:,} hitters who played at least {d['min_games']} games in {span(d['window'])}._"
        else:
            note = f"_{name} played fewer than {d['min_games']} games in this window, so there's no percentile rank._"
        return "\n".join(lines) + "\n\n" + note

    def _trend(self, plan, results) -> str:
        blocks = [self._trend_block(res.data, plan.stats) for res in results.get("get_player_trends", [])]
        first = results["get_player_trends"][0].data
        text = "\n\n".join(blocks)
        if plan.focus in FOCUS_LABEL:
            text += f"\n\n_{FOCUS_LABEL[plan.focus]}_"
        text += f"\n\n_{first['method']}_"
        if first.get("window_note"):
            text += f"\n\n_{first['window_note']}_"
        return text

    def _trend_leaders(self, plan, results) -> str:
        d = _first(results, "get_trend_leaders").data
        stat = d["stat"]
        word = "improving" if d["direction"] == "improving" else "declining"
        lines = [f"**Fastest {word} in {stat}, {span(d['window'])}** (at least {d['min_games']} games)"]
        for i, row in enumerate(d["rows"], 1):
            lines.append(f"{i}. {row['player']} — {fmt_slope(stat, row['slope_per_season'])}")
        lines.append(f"\n_Same as sorting the Trend Value table by {stat} Δ. {d['method']}_")
        return "\n".join(lines)

    def _valuation(self, plan, results) -> str:
        blocks = []
        for res in results.get("get_player_valuation", []):
            d = res.data
            v = d["valuation"]
            name = d["player"]["name"]
            w = d["weights"]
            lines = [
                f"**{name}: Valuation Score {v['valuation_score']:.2f} — #{v['rank']} of {d['pool_size']:,}** "
                f"({span(d['window'])}, at least {d['min_games']} games, weights {w['current']:g}:{w['trend']:g})",
                f"- Current Score {v['current_score']:.1f} — {ordinal(v['current_percentile'])} percentile for recent production.",
                f"- Trend Score {v['trend_score']:.1f} — {ordinal(v['trend_percentile'])} percentile for how fast production is rising.",
            ]
            drivers = ", ".join(f"{x['stat']} ({x['points']:.1f} pts)" for x in v["top_current_drivers"])
            lines.append(f"- Biggest production contributors: {drivers}.")
            if v["top_trend_drivers"]:
                lines.append("- Trend lifted by: " + ", ".join(f"{x['stat']} ({fmt_slope(x['stat'], x['slope'])})" for x in v["top_trend_drivers"]) + ".")
            if v["trend_drags"]:
                lines.append("- Trend held back by: " + ", ".join(f"{x['stat']} ({fmt_slope(x['stat'], x['slope'])})" for x in v["trend_drags"]) + ".")
            blocks.append("\n".join(lines))
        d0 = results["get_player_valuation"][0].data
        text = "\n\n".join(blocks)
        text += f"\n\n_{d0['method']} {' '.join(d0['page_notes'])}_"
        if re.search(r"\b(?:under|over)valued\b", self.question.lower()):
            text += ("\n\n_Valuation ranks production and trend; it doesn't compare with draft-market price. "
                     "For model-vs-market gaps (sleepers and bust risks), see Fantasy Sleepers & Busts._")
        return text

    def _valuation_board(self, plan, results) -> str:
        d = _first(results, "get_player_valuation").data
        lines = [f"**Top Valuation Scores, {span(d['window'])}** (at least {d['min_games']} games, all positions)"]
        for row in d["top"]:
            lines.append(f"{row['rank']}. {row['player']} — {row['valuation_score']:.2f} "
                         f"(Current {row['current_score']:.1f}, Trend {row['trend_score']:.1f})")
        lines.append(f"\n_{d['method']}_")
        return "\n".join(lines)

    def _player_profile(self, plan, results) -> str:
        d = _first(results, "get_player_profile").data
        p = d["player"]
        c = d["career_totals"]
        bits = [f"{span(p['seasons'])}", f"{d['seasons_played']} seasons"]
        if d.get("position"):
            bits.append(d["position"])
        head = f"**{p['name']}** ({', '.join(bits)}){' · Hall of Famer' if d.get('hall_of_famer') else ''}"
        career = (f"Career: {fmt('BA', c.get('BA'))} / {fmt('OBP', c.get('OBP'))} / {fmt('SLG', c.get('SLG'))} "
                  f"(BA/OBP/SLG), {fmt('OPS', c.get('OPS'))} OPS, {fmt('HR', c.get('HR'))} HR, {fmt('RBI', c.get('RBI'))} RBI, "
                  f"{fmt('SB', c.get('SB'))} SB in {fmt('G', c.get('G'))} games.")
        lines = [head, career]
        if d["best_seasons_by_ops"]:
            lines.append("**Best seasons by OPS** (qualified):")
            for s in d["best_seasons_by_ops"]:
                team = f", {s['team']}" if s.get("team") else ""
                lines.append(f"- {s['season']}{team}: {fmt('OPS', s.get('OPS'))} OPS, {fmt('HR', s.get('HR'))} HR, "
                             f"{fmt('RBI', s.get('RBI'))} RBI, {fmt('BA', s.get('BA'))} BA")
        else:
            lines.append("_No season reached the app's qualified at-bat minimum, so there's no best-season list._")
        return "\n\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:]) + f"\n\n_Qualified = at least {d['qualification_rule']}._"

    def _player_seasons(self, plan, results) -> str:
        d = _first(results, "get_player_seasons").data
        name = d["player"]["name"]
        seasons = d["seasons"]
        lead = ""
        if len(seasons) == 1 and plan.stats:
            s = seasons[0]
            lead = f"In {s['season']}, {name} had " + ", ".join(f"{fmt(st, s.get(st))} {st}" for st in plan.stats) + ".\n\n"
        header = ["Season", "G", "AB", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]
        rows = [[str(s["season"])] + [fmt(h, s.get(h)) for h in header[1:]] for s in seasons]
        text = lead + f"**{name}, {span(d['year_range'])}**\n\n" + _table(header, rows)
        if len(seasons) > 1:
            t = d["totals"]
            text += (f"\n\nTotal: {fmt('HR', t.get('HR'))} HR, {fmt('RBI', t.get('RBI'))} RBI, "
                     f"{fmt('OPS', t.get('OPS'))} OPS in {fmt('G', t.get('G'))} games.")
        if d.get("range_note"):
            text += f"\n\n_{d['range_note']}_"
        return text

    # ---- draft -------------------------------------------------------------------
    @staticmethod
    def _rec_line(i: int, row: dict[str, Any]) -> str:
        pos = f" ({row['Primary Position']})" if row.get("Primary Position") else ""
        scores = []
        for key in ("Decision Score", "Player Grade", "Roster Fit Score"):
            if isinstance(row.get(key), (int, float)):
                scores.append(f"{key} {score_text(key, row[key])}")
        line = f"{i}. **{row['player']}**{pos}" + (f" — {' · '.join(scores)}" if scores else "")
        why = row.get("why_this_pick") or row.get("reason")
        if why:
            line += f"\n   _{why}_"
        return line

    def _draft_next(self, plan, results) -> str:
        d = _first(results, "get_draft_recommendations").data
        where = d.get("source_page") or "your draft page"
        pick = f" at pick {d['current_pick']}" if d.get("current_pick") else ""
        pos = f" {d['position'].upper()}" if d.get("position") else ""
        lines = [f"**Top{pos} recommendations from {where}{pick}:**"]
        lines += [self._rec_line(i, row) for i, row in enumerate(d.get("recommendations", []), 1)]
        if d.get("note"):
            lines.append(d["note"])
        best = [b["player"] for b in d.get("best_available", [])[:5]]
        if best:
            lines.append(f"\nBest available by market value: {', '.join(best)}.")
        if d.get("needed_positions"):
            lines.append(f"Your open positions: {', '.join(d['needed_positions'])}.")
        lines.append("\n_These are the page's own rankings. AMI doesn't draft for you — pick on the draft page._")
        return "\n".join(lines)

    def _draft_explain(self, plan, results) -> str:
        res = _first(results, "explain_draft_recommendation")
        if res is None:
            d = _first(results, "get_draft_recommendations").data
            recs = d.get("recommendations") or []
            if not recs:
                return "The draft page has no recommendations right now."
            row, needed, where, list_pos = recs[0], d.get("needed_positions") or [], d.get("source_page"), 1
        else:
            d = res.data
            row, needed, where, list_pos = d["row"], d.get("needed_positions") or [], d.get("source_page"), d["position_in_list"]
        name = row["player"]
        lines = [f"**Why {name}** (#{list_pos} on {where or 'the draft page'}):"]
        if row.get("why_this_pick") or row.get("reason"):
            lines.append(f"The page's reasoning: _{row.get('why_this_pick') or row.get('reason')}_")
        reasons = []
        pos = str(row.get("Primary Position") or "")
        if pos and needed and any(p.strip().upper() in {n.upper() for n in needed} for p in pos.replace("/", ",").split(",")):
            reasons.append(f"plays {pos}, a position your roster still needs")
        if isinstance(row.get("Fantasy Edge"), (int, float)) and row["Fantasy Edge"] > 0:
            reasons.append(f"the model ranks {surname(name)} {int(round(row['Fantasy Edge']))} spots ahead of the market")
        if row.get("Survival Label"):
            prob = row.get("Survival Probability")
            pct = f" ({float(prob) * 100:.0f}% chance to last)" if isinstance(prob, (int, float)) and prob <= 1 else ""
            reasons.append(f"survival outlook to your next pick: {row['Survival Label']}{pct}")
        if reasons:
            lines.append("In short: " + "; ".join(reasons) + ".")
        scores = []
        for key, desc in (("Decision Score", "overall strength of this pick now"), ("Player Grade", "player quality"),
                          ("Roster Fit Score", "fit with your roster")):
            if isinstance(row.get(key), (int, float)):
                scores.append(f"{key} {score_text(key, row[key])} ({desc})")
        if scores:
            lines.append("Scores: " + "; ".join(scores) + ".")
        return "\n\n".join(lines)

    def _draft_needs(self, plan, results) -> str:
        d = _first(results, "get_team_needs").data
        team = d.get("team") or "Your team"
        lines = [f"**{team}'s needs** (from {d.get('source_page') or 'the draft page'})"]
        lines.append("Open positions: " + (", ".join(d["needed_positions"]) if d.get("needed_positions") else "none listed") + ".")
        weak = d.get("weak_categories") or []
        strong = d.get("strong_categories") or []
        if weak:
            lines.append("Weak categories vs the remaining player pool: " + ", ".join(
                f"{x['stat']} ({x.get('gap_vs_pool_pct', 0):+.0f}%)" for x in weak) + ".")
        elif d.get("category_needs"):
            lines.append("Categories to strengthen: " + ", ".join(d["category_needs"]) + ".")
        if strong:
            lines.append("Strengths: " + ", ".join(f"{x['stat']} ({x.get('gap_vs_pool_pct', 0):+.0f}%)" for x in strong) + ".")
        return "\n\n".join(lines)

    def _draft_strategy(self, plan, results) -> str:
        needs = _first(results, "get_team_needs")
        recs = _first(results, "get_draft_recommendations")
        if not (needs and needs.ok and recs and recs.ok):
            failed = next(res for res in (needs, recs) if res is not None and not res.ok)
            return _failure(failed)
        needed = [n.upper() for n in needs.data.get("needed_positions") or []]
        rows = recs.data.get("recommendations") or []
        lines = [f"The app doesn't make you choose: **Decision Score** already blends both — {TERMS['decision_score'].definition}"]
        if rows:
            top = rows[0]
            pos = str(top.get("Primary Position") or "")
            fills = any(p.strip().upper() in needed for p in pos.replace("/", ",").split(",")) if pos else False
            ds = f", Decision Score {top['Decision Score']:.1f}" if isinstance(top.get("Decision Score"), (int, float)) else ""
            lines.append(f"Right now the top pick is **{top['player']}** ({pos or 'position n/a'}{ds})"
                         + (", which also fills a need." if fills else (f"; your open positions are {', '.join(needed)}." if needed else ".")))
            need_pick = next((x for x in rows[1:] if any(p.strip().upper() in needed for p in str(x.get("Primary Position") or "").replace("/", ",").split(","))), None)
            if need_pick is not None and not fills:
                ds2 = f" (Decision Score {need_pick['Decision Score']:.1f})" if isinstance(need_pick.get("Decision Score"), (int, float)) else ""
                lines.append(f"Highest-ranked player at a need position: **{need_pick['player']}**{ds2}. "
                             "The gap between their Decision Scores is the price of drafting for need.")
        return "\n\n".join(lines)

    def _sleepers(self, plan, results) -> str:
        d = _first(results, "get_sleepers_busts").data
        lines = ["**Fantasy Sleepers & Busts** (as last shown on that page)"]
        for label, key in (("Sleepers", "sleepers"), ("Bust risks", "busts")):
            rows = d.get(key) or []
            if rows:
                items = []
                for x in rows[:5]:
                    edge = x.get("Fantasy Edge")
                    items.append(f"{x['player']}" + (f" (edge {edge:+.0f})" if isinstance(edge, (int, float)) else ""))
                lines.append(f"{label}: " + ", ".join(items) + ".")
        lines.append("_Fantasy Edge = Market Rank − Model Rank (positive = sleeper, negative = bust risk)._")
        return "\n\n".join(lines)

    def _fantasy_team(self, plan, results) -> str:
        not_wired = next((res for calls in results.values() for res in calls if not res.ok), None)
        parts = [not_wired.message if not_wired else "AMI can't read your league data yet."]
        howto = _first(results, "find_feature")
        if howto is not None and howto.ok:
            d = howto.data
            steps = [d["navigation"], *d["steps"]]
            parts.append(f"Here's how to do it on **{d['page']}**:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))
        return "\n\n".join(parts)


POSITION_PLURAL = r.POSITION_NAMES
