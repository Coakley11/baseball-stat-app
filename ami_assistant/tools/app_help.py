"""App-help tools over the authoritative registry (page_help, glossary)."""

from __future__ import annotations

from ami_assistant.glossary import TERMS, find_term
from ami_assistant.page_help import HOWTO_BY_KEY, PAGE_HELP, find_howto, find_page
from ami_assistant.tools.registry import BAD_ARGUMENT, ToolResult, fail, tool


def _home_tasks() -> list[dict[str, str]]:
    """Home's task cards, straight from ``home_page.TASKS`` (icon, title, line, button, page key)."""
    from home_page import TASKS

    return [{"title": title, "line": line, "button": button, "page": page} for _icon, title, line, button, page in TASKS]


@tool(
    "explain_app_page",
    capability="app_guidance",
    description="What a Baseball Explorer page does, when to use it, its main controls, related terms and how to get there.",
    parameters={"properties": {"page": {"type": "string"}}, "required": ["page"]},
    reuses=("page_guides.PAGE_GUIDES", "nav_groups.PAGE_SECTION / NAV_LABELS", "home_page.TASKS"),
)
def explain_app_page(*, page: str) -> ToolResult:
    ph = PAGE_HELP.get(page) or find_page(page)
    if ph is None:
        return fail("explain_app_page", BAD_ARGUMENT, f"There's no page called “{page}”.", pages=sorted(PAGE_HELP))
    return ToolResult(
        tool="explain_app_page",
        ok=True,
        data={
            "page": ph.label,  # what the user sees (U1 renames); the key stays below
            "page_key": ph.key,
            "group": ph.group,
            "purpose": ph.purpose,
            "explore_more": ph.explore_more,
            "tasks": _home_tasks() if ph.key == "Home" else [],
            "when": ph.when,
            "outputs": ph.outputs,
            "tips": list(ph.tips),
            "controls": list(ph.controls),
            "example_questions": list(ph.questions),
            "terms": [{"name": TERMS[t].name, "definition": TERMS[t].definition} for t in ph.terms if t in TERMS],
            "next_steps": list(ph.next_steps),
            "navigation": ph.navigation(),
        },
    )


@tool(
    "explain_metric",
    capability="app_guidance",
    description="Definition of an app metric (Decision Score, Valuation Score, Trend Value, OPS, …) in the app's own words.",
    parameters={"properties": {"term": {"type": "string"}}, "required": ["term"]},
    reuses=("draft_score_display.SCORE_TOOLTIPS", "page_guides.PAGE_GUIDES", "trend_slopes", "rate_stat_qualification"),
)
def explain_metric(*, term: str) -> ToolResult:
    t = TERMS.get(term) or find_term(term)
    if t is None:
        return fail("explain_metric", BAD_ARGUMENT, f"“{term}” isn't a metric AMI knows.", terms=sorted(x.name for x in TERMS.values()))
    return ToolResult(
        tool="explain_metric",
        ok=True,
        data={"term": t.name, "definition": t.definition, "shown_on": list(t.where), "source": t.source},
    )


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
            "steps": list(h.steps),
            "note": h.note,
        },
    )
