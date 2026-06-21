"""Audit helpers — every suite app open URL must propagate ``?suite_workspace=``."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

SUITE_APP_KEYS: tuple[str, ...] = (
    "music",
    "investment",
    "baseball",
    "nba",
    "applied_intelligence",
    "future_lens",
)


def _query_param(url: str, name: str) -> str:
    parsed = urlparse(str(url or "").strip())
    raw = parse_qs(parsed.query)
    vals = raw.get(name) or []
    return str(vals[0] or "").strip() if vals else ""


def audit_registry_open_urls(*, workspace_id: str = "daniel") -> list[dict[str, str]]:
    """Return issues for ``app_registry.get_app_url`` missing workspace param."""
    issues: list[dict[str, str]] = []
    try:
        from app_registry import get_app_url
    except ImportError:
        return [{"app": "*", "issue": "app_registry unavailable"}]
    ws = str(workspace_id or "daniel").strip() or "daniel"
    for app_key in SUITE_APP_KEYS:
        url = get_app_url(app_key, workspace_id=ws)
        if not url:
            issues.append({"app": app_key, "issue": "empty url", "url": ""})
            continue
        if _query_param(url, "suite_workspace") != ws:
            issues.append(
                {
                    "app": app_key,
                    "issue": "missing or wrong suite_workspace",
                    "url": url,
                    "expected": ws,
                    "actual": _query_param(url, "suite_workspace"),
                }
            )
    return issues


def audit_resume_action_urls(*, workspace_id: str = "ariel") -> list[dict[str, str]]:
    """Return issues for ``build_resume_action_url`` missing workspace param."""
    issues: list[dict[str, str]] = []
    try:
        from suite_deep_links import build_resume_action_url
    except ImportError:
        return [{"app": "*", "issue": "suite_deep_links unavailable"}]
    ws = str(workspace_id or "ariel").strip() or "ariel"
    for app_key in SUITE_APP_KEYS:
        url = build_resume_action_url(
            app_key,
            resume_key=f"{app_key}:audit",
            page="",
            metrics={"workspace_id": ws},
        )
        if not url:
            issues.append({"app": app_key, "issue": "empty resume url", "url": ""})
            continue
        if _query_param(url, "suite_workspace") != ws:
            issues.append(
                {
                    "app": app_key,
                    "issue": "resume url missing workspace",
                    "url": url,
                    "expected": ws,
                    "actual": _query_param(url, "suite_workspace"),
                }
            )
    return issues


def audit_command_center_link_url(*, workspace_id: str = "daniel") -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    try:
        from suite_command_center_link import command_center_url
    except ImportError:
        return [{"app": "command_center", "issue": "suite_command_center_link unavailable"}]
    ws = str(workspace_id or "daniel").strip() or "daniel"
    url = command_center_url(workspace_id=ws)
    if not url:
        issues.append({"app": "command_center", "issue": "empty command center url"})
    elif _query_param(url, "suite_workspace") != ws:
        issues.append(
            {
                "app": "command_center",
                "issue": "command center link missing workspace",
                "url": url,
                "expected": ws,
                "actual": _query_param(url, "suite_workspace"),
            }
        )
    return issues


def collect_deep_link_audit_issues(*, workspace_id: str = "daniel") -> list[dict[str, str]]:
    """Run all deep-link audits for tests and diagnostics."""
    issues: list[dict[str, str]] = []
    issues.extend(audit_registry_open_urls(workspace_id=workspace_id))
    issues.extend(audit_resume_action_urls(workspace_id=workspace_id))
    issues.extend(audit_command_center_link_url(workspace_id=workspace_id))
    return issues


def assert_deep_links_include_workspace(*, workspace_id: str = "daniel") -> None:
    issues = collect_deep_link_audit_issues(workspace_id=workspace_id)
    if issues:
        lines = [f"{i.get('app')}: {i.get('issue')} ({i.get('url', '')})" for i in issues]
        raise AssertionError("Deep-link audit failed:\n" + "\n".join(lines))
