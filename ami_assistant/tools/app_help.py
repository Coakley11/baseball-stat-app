"""App-help tools over the authoritative registry (page_help, glossary, draft_tools).

Every prose field is passed through ``render_page_names``, so pages are named by their current
labels (``nav_groups.NAV_LABELS``) however the registry spells them.
"""

from __future__ import annotations

from ami_assistant.context import render_page_names
from ami_assistant.glossary import TERMS, find_term
from ami_assistant.page_help import DRAFT_TOOL_PAGES, HOWTO_BY_KEY, PAGE_HELP, find_howto, find_page
from ami_assistant.tools.registry import BAD_ARGUMENT, ToolResult, fail, tool


def _home_tasks() -> list[dict[str, object]]:
    """Home's task cards, straight from ``home_page.TASKS``. The draft card shows the four
    ``draft_tools.HOME_DRAFT_CHOICES`` instead of one button (U3A), so it carries those."""
    from draft_tools import HOME_DRAFT_CHOICES, purpose
    from home_page import DRAFT_TASK, TASKS

    tasks: list[dict[str, object]] = []
    for _icon, title, line, button, page in TASKS:
        if title == DRAFT_TASK:
            choices = [{"button": label, "page": PAGE_HELP[p].label, "purpose": purpose(p)} for label, p in HOME_DRAFT_CHOICES]
            tasks.append({"title": title, "line": line, "choices": choices})
        else:
            tasks.append({"title": title, "line": line, "button": button, "page": PAGE_HELP[page].label})
    return tasks


@tool(
    "explain_app_page",
    capability="app_guidance",
    description="What a Baseball Explorer page does, when to use it, its main controls, what's under Explore more, "
                "related terms and how to get there.",
    parameters={"properties": {"page": {"type": "string"}}, "required": ["page"]},
    reuses=("page_guides.PAGE_GUIDES", "nav_groups.PAGE_SECTION / NAV_LABELS", "home_page.TASKS",
            "draft_tools.DRAFT_TOOLS / HOME_DRAFT_CHOICES"),
)
def explain_app_page(*, page: str) -> ToolResult:
    ph = PAGE_HELP.get(page) or find_page(page)
    if ph is None:
        return fail("explain_app_page", BAD_ARGUMENT, f"There's no page called “{page}”.", pages=sorted(PAGE_HELP))
    return ToolResult(
        tool="explain_app_page",
        ok=True,
        data={
            "page": ph.label,  # what the user sees (U1–U3 renames); the key stays below
            "page_key": ph.key,
            "group": ph.group,
            "purpose": ph.purpose,
            "reading": [render_page_names(r) for r in ph.reading],
            "explore_more": ph.explore_more_text,
            "tasks": _home_tasks() if ph.key == "Home" else [],
            "when": ph.when,
            "outputs": ph.outputs,
            "tips": list(ph.tips),
            "controls": list(ph.controls),
            "example_questions": list(ph.questions),
            "terms": [{"name": TERMS[t].name, "definition": render_page_names(TERMS[t].definition)}
                      for t in ph.terms if t in TERMS],
            "next_steps": [render_page_names(s) for s in ph.next_steps],
            "navigation": ph.navigation(),
        },
    )


@tool(
    "explain_metric",
    capability="app_guidance",
    description="Definition of an app metric or label (Decision Score, Valuation Score, Trend Value, OPS, lineup "
                "status, trade verdict, …) in the app's own words.",
    parameters={"properties": {"term": {"type": "string"}}, "required": ["term"]},
    reuses=("draft_score_display.SCORE_TOOLTIPS", "page_guides.PAGE_GUIDES", "trend_slopes", "rate_stat_qualification",
            "u3_answers", "ui_hierarchy.COMMISSIONER_PANEL_LABEL"),
)
def explain_metric(*, term: str) -> ToolResult:
    t = TERMS.get(term) or find_term(term)
    if t is None:
        return fail("explain_metric", BAD_ARGUMENT, f"“{term}” isn't a metric AMI knows.", terms=sorted(x.name for x in TERMS.values()))
    return ToolResult(
        tool="explain_metric",
        ok=True,
        data={"term": t.name, "definition": render_page_names(t.definition), "shown_on": list(t.where), "source": t.source},
    )


@tool(
    "explain_draft_tools",
    capability="app_guidance",
    description="What each draft tool is for (Live Draft Room, Draft Room Simulator, Draft Assistant, Draft Lab, "
                "Saved Draft Library) and which Home draft choice opens it. All five, or the ones named.",
    parameters={"properties": {"pages": {"type": "array", "items": {"type": "string"}}}},
    reuses=("draft_tools.DRAFT_TOOLS", "draft_tools.HOME_DRAFT_CHOICES"),
)
def explain_draft_tools(*, pages: list[str] | None = None) -> ToolResult:
    from draft_tools import DRAFT_TOOLS, HOME_DRAFT_CHOICES
    from home_page import DRAFT_TASK

    wanted = [p for p in (pages or []) if p in DRAFT_TOOL_PAGES]
    home = {page: label for label, page in HOME_DRAFT_CHOICES}
    tools = [
        {"page": PAGE_HELP[page].label, "page_key": page, "name": name, "purpose": why,
         "home_choice": home.get(page, ""), "section": PAGE_HELP[page].group, "navigation": PAGE_HELP[page].navigation()}
        for page, _icon, name, why in DRAFT_TOOLS
        if not wanted or page in wanted
    ]
    return ToolResult(tool="explain_draft_tools", ok=True, data={"tools": tools, "all": not wanted, "home_card": DRAFT_TASK})


@tool(
    "find_feature",
    capability="app_guidance",
    description="Where and how to do something in the app (compare players, make a trade, add from waivers, …), step by step.",
    parameters={"properties": {"task": {"type": "string"}}, "required": ["task"]},
    reuses=("ami_assistant.page_help.HOWTOS (label-checked)",),
)
def find_feature(*, task: str) -> ToolResult:
    h = HOWTO_BY_KEY.get(task) or find_howto(task)
    if h is None:
        page = find_page(task)
        if page is None:
            return fail("find_feature", BAD_ARGUMENT, "AMI doesn't have step-by-step help for that yet.")
        return explain_app_page(page=page.key)
    ph = PAGE_HELP[h.page]
    return ToolResult(
        tool="find_feature",
        ok=True,
        data={
            "task": h.title,
            "page": ph.label,
            "page_key": h.page,
            "navigation": ph.navigation(),
            "steps": [render_page_names(s) for s in h.steps],
            "note": render_page_names(h.note),
        },
    )
