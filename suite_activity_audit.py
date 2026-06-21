"""Audit helpers — activity writes must tag workspace + scoped cloud app keys."""

from __future__ import annotations

from typing import Any

SUITE_ACTIVITY_APPS: tuple[str, ...] = (
    "music",
    "investment",
    "baseball",
    "nba",
    "applied_intelligence",
    "future_lens",
    "command_center",
)

REQUIRED_ACTIVITY_SCOPING: tuple[str, ...] = ("workspace_id",)


def prepare_activity_metrics(
    app: str,
    metrics: dict[str, Any] | None,
    *,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Mirror ``suite_activity_client`` workspace tagging for tests."""
    out: dict[str, Any] = dict(metrics or {})
    ws = str(workspace_id or out.get("workspace_id") or "").strip()
    if not ws:
        try:
            from suite_workspace import get_active_workspace_id

            ws = get_active_workspace_id()
        except Exception:
            ws = "daniel"
    out.setdefault("workspace_id", ws)
    return out


def scoped_activity_app_key(app: str, metrics: dict[str, Any] | None = None) -> str:
    """Return the Supabase ``app`` key used for an activity write."""
    m = prepare_activity_metrics(app, metrics)
    try:
        from suite_workspace import normalize_workspace_id, scoped_cloud_app_id

        ws = normalize_workspace_id(str(m.get("workspace_id") or "daniel"))
        return scoped_cloud_app_id(app, ws)
    except ImportError:
        return str(app or "").strip()


def audit_activity_metrics(app: str, metrics: dict[str, Any] | None = None) -> list[str]:
    """Return human-readable issues for an activity payload."""
    issues: list[str] = []
    app_key = str(app or "").strip()
    if not app_key:
        return ["missing app id"]
    m = dict(metrics or {})
    for key in REQUIRED_ACTIVITY_SCOPING:
        if not str(m.get(key) or "").strip():
            issues.append(f"missing metrics.{key}")
    scoped = scoped_activity_app_key(app_key, m)
    if app_key == "music" and str(m.get("workspace_id") or "") == "ariel":
        if scoped == "music":
            issues.append("ariel workspace must not write legacy music cloud key")
    if app_key == "applied_intelligence" and str(m.get("workspace_id") or "") == "ariel":
        if scoped == "applied_intelligence":
            issues.append("ariel workspace must not write legacy AMI cloud key")
    return issues


def audit_activity_write_contract() -> dict[str, list[str]]:
    """Static audit — Ariel scoped keys must be namespaced for legacy apps."""
    report: dict[str, list[str]] = {}
    legacy_apps = ("music", "investment", "baseball", "nba", "applied_intelligence", "future_lens")
    for app in SUITE_ACTIVITY_APPS:
        if app == "command_center":
            continue
        ariel_key = scoped_activity_app_key(app, {"workspace_id": "ariel"})
        issues: list[str] = []
        if not ariel_key:
            issues.append("empty ariel scoped key")
        elif app in legacy_apps and ariel_key == app:
            issues.append(f"ariel key must be namespaced, got {ariel_key!r}")
        report[app] = issues
    return report


def assert_activity_write_contract() -> None:
    report = audit_activity_write_contract()
    failures = {app: msgs for app, msgs in report.items() if msgs}
    if failures:
        lines = [f"{app}: {', '.join(msgs)}" for app, msgs in failures.items()]
        raise AssertionError("Activity write contract failed:\n" + "\n".join(lines))
