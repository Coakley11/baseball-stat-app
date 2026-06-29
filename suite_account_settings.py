"""
User-facing Account Settings UX — identity and workspace diagnostics (not full auth).

Synced to sibling suite apps via ``scripts/sync_suite_cloud_modules.py``.
"""

from __future__ import annotations

from typing import Any

from suite_account import account_summary
from suite_user import get_user_email
from suite_workspace import (
    DEFAULT_WORKSPACE_ID,
    _INITIALIZED_KEY,
    _QUERY_PARAM,
    SESSION_KEY,
    append_suite_workspace_param,
    get_active_workspace_id,
    init_suite_workspace,
    load_persisted_workspace_id,
    normalize_workspace_id,
    scoped_cloud_app_id,
    workspace_dir,
    workspace_label,
    workspace_storage_app_keys,
)

# Logical app ids shown in namespace preview (matches suite_workspace._SUITE_STORAGE_APP_IDS).
NAMESPACE_PREVIEW_APPS: tuple[tuple[str, str], ...] = (
    ("applied_intelligence", "Applied Math (AMI)"),
    ("baseball", "Baseball"),
    ("investment", "Investment"),
    ("music", "Music"),
    ("nba", "NBA"),
    ("future_lens", "FutureLens"),
)

_ISSUE_QUERY_MISMATCH = "query_workspace_mismatch"
_ISSUE_PERSIST_MISMATCH = "persisted_workspace_mismatch"
_ISSUE_ACTIVITY_NAMESPACE = "activity_namespace_mismatch"
_ISSUE_DIRECT_APP_OPEN = "direct_app_open_risk"


def _qp_get(st: Any, name: str) -> str:
    try:
        raw = st.query_params.get(name)
    except Exception:
        return ""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return str(raw[0] or "").strip()
    return str(raw).strip()


def _password_auth_available() -> bool:
    try:
        from suite_auth import password_auth_available

        return password_auth_available()
    except ImportError:
        return False


def build_scoped_cloud_key_preview(workspace_id: str | None = None) -> dict[str, str]:
    """Map logical app id → Supabase ``app`` row key for the given workspace."""
    ws = normalize_workspace_id(workspace_id or DEFAULT_WORKSPACE_ID)
    return {app_id: scoped_cloud_app_id(app_id, ws) for app_id, _ in NAMESPACE_PREVIEW_APPS}


def build_account_settings_context(*, st: Any | None = None) -> dict[str, Any]:
    """Structured account + workspace summary for UI and tests."""
    if st is not None:
        init_suite_workspace(st)
    ws = get_active_workspace_id(st)
    acct = account_summary()
    email = get_user_email()
    persisted = load_persisted_workspace_id()
    query_ws = normalize_workspace_id(_qp_get(st, _QUERY_PARAM)) if st is not None else persisted
    query_raw = _qp_get(st, _QUERY_PARAM) if st is not None else ""
    namespace_keys = sorted(workspace_storage_app_keys(ws))
    cloud_preview = build_scoped_cloud_key_preview(ws)
    sample_app_url = ""
    try:
        from app_registry import get_app_url

        sample_app_url = get_app_url("applied_intelligence", workspace_id=ws)
    except Exception:
        sample_app_url = append_suite_workspace_param(
            "https://example.test/applied-mathematical-intelligence",
            workspace_id=ws,
        )

    return {
        "email": email,
        "email_display": email if email else "(not configured — set suite_user_email in secrets)",
        "display_name": acct.get("display_name") or "",
        "suite_user_id": acct.get("external_id") or "",
        "account_user_id": acct.get("user_id") or "",
        "sync_mode": acct.get("mode") or "local",
        "active_workspace_id": ws,
        "active_workspace_label": workspace_label(ws),
        "persisted_workspace_id": persisted,
        "query_workspace_id": query_ws if query_raw else "",
        "query_workspace_raw": query_raw,
        "workspace_data_dir": str(workspace_dir(ws)),
        "namespace_keys": namespace_keys,
        "scoped_cloud_keys": cloud_preview,
        "sample_app_url": sample_app_url,
        "password_auth_available": _password_auth_available(),
        "isolation_note": (
            "Daniel uses legacy unscoped cloud keys (e.g. applied_intelligence). "
            "Other profiles use scoped keys (e.g. applied_intelligence__ariel). "
            "Saved state and activity never cross profiles when opened with the matching workspace."
        ),
    }


def detect_workspace_namespace_issues(*, st: Any | None = None) -> list[dict[str, str]]:
    """
    Return user-visible warnings when workspace identity may be inconsistent.

    Covers URL param vs session, persisted file vs session, and activity namespace hints.
    """
    issues: list[dict[str, str]] = []

    if st is not None:
        query_raw = _qp_get(st, _QUERY_PARAM)
        if query_raw and not st.session_state.get(_INITIALIZED_KEY):
            query_ws = normalize_workspace_id(query_raw)
            session_ws = normalize_workspace_id(
                str(st.session_state.get(SESSION_KEY) or load_persisted_workspace_id())
            )
            if query_ws != session_ws:
                issues.append(
                    {
                        "code": _ISSUE_QUERY_MISMATCH,
                        "severity": "error",
                        "title": "URL workspace does not match saved profile",
                        "detail": (
                            f"The page URL has ?{_QUERY_PARAM}={query_raw!r} (→ {query_ws!r}) "
                            f"but the saved profile was {workspace_label(session_ws)!r} ({session_ws!r}). "
                            "Command Center will switch to the URL profile on load."
                        ),
                    }
                )
        init_suite_workspace(st)

    ws = get_active_workspace_id(st)
    persisted = load_persisted_workspace_id()
    if persisted != ws:
        issues.append(
            {
                "code": _ISSUE_PERSIST_MISMATCH,
                "severity": "warning",
                "title": "Saved workspace file differs from active session",
                "detail": (
                    f"Persisted profile is {workspace_label(persisted)!r} ({persisted!r}) "
                    f"but this session is {workspace_label(ws)!r} ({ws!r}). "
                    "This usually clears after you switch profiles once."
                ),
            }
        )

    try:
        from activity_diagnostics import build_workspace_activity_namespace_diagnostics

        ns = build_workspace_activity_namespace_diagnostics(st)
        hint = str(ns.get("namespace_mismatch_hint") or "").strip()
        if hint:
            issues.append(
                {
                    "code": _ISSUE_ACTIVITY_NAMESPACE,
                    "severity": "warning",
                    "title": "Activity namespace may not match this profile",
                    "detail": hint,
                }
            )
    except Exception:
        pass

    if ws != DEFAULT_WORKSPACE_ID:
        issues.append(
            {
                "code": _ISSUE_DIRECT_APP_OPEN,
                "severity": "info",
                "title": "Open apps from Command Center to preserve this profile",
                "detail": (
                    f"You are on the {workspace_label(ws)} profile. "
                    "Some apps default to Daniel when opened directly. "
                    f"Use Open buttons here or append ?suite_workspace={ws} to app URLs."
                ),
            }
        )

    return issues


def _account_ui(st: Any, *, sidebar: bool = False) -> Any:
    return st.sidebar if sidebar else st


def account_workspace_expander_label(ctx: dict[str, Any]) -> str:
    label = str(ctx.get("active_workspace_label") or "Workspace").strip()
    return f"Account & Workspace · {label}"


def render_global_workspace_badge(st: Any, *, sidebar: bool = True) -> None:
    """Prominent workspace badge — use inside Account & Workspace tab in normal mode."""
    init_suite_workspace(st)
    ws = get_active_workspace_id(st)
    label = workspace_label(ws)
    accent = "#6366f1" if ws == DEFAULT_WORKSPACE_ID else "#0ea5e9"
    show_id = False
    try:
        from suite_workspace import can_show_developer_tools

        show_id = can_show_developer_tools(st=st)
    except ImportError:
        show_id = False
    id_line = (
        f'<div style="font-size:0.78rem;color:#64748b;margin-top:0.2rem;">id: <code>{ws}</code></div>'
        if show_id
        else ""
    )
    ui = _account_ui(st, sidebar=sidebar)
    ui.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, {accent}22, {accent}11);
            border: 1px solid {accent}55;
            border-radius: 12px;
            padding: 0.65rem 0.75rem;
            margin-bottom: 0.5rem;
        ">
            <div style="font-size:0.72rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.04em;">
                Active workspace
            </div>
            <div style="font-size:1.05rem;font-weight:800;color:#0f172a;margin-top:0.15rem;">
                {label}
            </div>
            {id_line}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _signed_in_email(ctx: dict[str, Any], session_state: dict[str, Any]) -> str:
    try:
        from suite_auth import current_auth_email, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(session_state):
            email = str(current_auth_email(session_state) or "").strip()
            if email:
                return email
    except ImportError:
        pass
    email = str(ctx.get("email_display") or "").strip()
    if email and email != "(not configured — set suite_user_email in secrets)":
        return email
    return ""


def _render_minimal_account_workspace_body(
    st: Any,
    ui: Any,
    session_state: dict[str, Any],
    ctx: dict[str, Any],
) -> None:
    """Normal mode — email + logout only."""
    email = _signed_in_email(ctx, session_state)
    if email:
        ui.markdown(f"Signed in: **{email}**")
    try:
        from suite_auth import is_auth_enabled, is_authenticated, logout

        if is_auth_enabled() and is_authenticated(session_state):
            if ui.button("Log out", key="suite_account_workspace_logout_btn", use_container_width=True):
                logout(session_state, st=st)
                st.rerun()
            return
    except ImportError:
        pass
    if not email:
        ui.caption("Shared suite profile (no individual sign-in on this deploy).")


def render_user_account_access(st: Any, *, for_homepage: bool = False, sidebar: bool = False) -> None:
    """Deprecated alias — use render_account_workspace_access."""
    render_account_workspace_access(st, for_homepage=for_homepage, sidebar=sidebar)


def render_account_workspace_access(
    st: Any,
    *,
    for_homepage: bool = False,
    sidebar: bool = False,
    account_panel_expanded: bool = False,
) -> None:
    """Collapsed Account & Workspace tab in normal mode; full diagnostics in dev mode."""
    init_suite_workspace(st)
    ctx = build_account_settings_context(st=st)
    ui = _account_ui(st, sidebar=sidebar)
    dev_mode = False
    try:
        from suite_workspace import can_show_developer_tools

        dev_mode = can_show_developer_tools(st=st)
    except ImportError:
        pass

    try:
        from suite_auth import is_auth_enabled, is_authenticated, render_auth_panel

        auth_on = is_auth_enabled()
        signed_in = is_authenticated(st.session_state)
    except ImportError:
        auth_on = False
        signed_in = True

    if auth_on and not signed_in:
        ui.info("Sign in to sync your suite data across devices.")
        render_auth_panel(st, expanded=True)
        return

    if dev_mode:
        render_account_settings_panel(
            st,
            expanded=account_panel_expanded or dev_mode,
            show_title=True,
            sidebar=sidebar,
        )
        return

    header = account_workspace_expander_label(ctx)
    with ui.expander(header, expanded=False):
        _render_minimal_account_workspace_body(st, ui, st.session_state, ctx)


def render_account_settings_panel(
    st: Any,
    *,
    expanded: bool = False,
    show_title: bool = True,
    sidebar: bool = False,
) -> None:
    """User-facing Account Settings — identity, workspace, namespace diagnostics."""
    init_suite_workspace(st)
    ctx = build_account_settings_context(st=st)
    issues = detect_workspace_namespace_issues(st=st)
    ui = _account_ui(st, sidebar=sidebar)

    title = "Account & workspace"
    if show_title:
        with ui.expander(title, expanded=expanded):
            _render_account_settings_body(st, ctx, issues)
    else:
        ui.markdown(f"### {title}")
        _render_account_settings_body(st, ctx, issues)


def _render_account_settings_body(st: Any, ctx: dict[str, Any], issues: list[dict[str, str]]) -> None:
    for issue in issues:
        severity = issue.get("severity", "warning")
        title = issue.get("title", "Workspace notice")
        detail = issue.get("detail", "")
        if severity == "error":
            st.error(f"**{title}** — {detail}")
        elif severity == "info":
            st.info(f"**{title}** — {detail}")
        else:
            st.warning(f"**{title}** — {detail}")

    st.markdown("#### Profile & account")
    st.markdown(
        f"| Field | Value |\n|---|---|\n"
        f"| **Email** | {ctx['email_display']} |\n"
        f"| **Display name** | {ctx['display_name'] or '—'} |\n"
        f"| **Suite user id** | `{ctx['suite_user_id']}` |\n"
        f"| **Storage user id** | `{ctx['account_user_id']}` |\n"
        f"| **Sync mode** | **{ctx['sync_mode']}** |"
    )

    st.markdown("#### Workspace profile")
    st.markdown(
        f"| Field | Value |\n|---|---|\n"
        f"| **Active profile** | **{ctx['active_workspace_label']}** |\n"
        f"| **Workspace id** | `{ctx['active_workspace_id']}` |\n"
        f"| **Persisted profile** | `{ctx['persisted_workspace_id']}` |\n"
        f"| **URL profile** | `{ctx['query_workspace_id'] or '—'}` |\n"
        f"| **Local data folder** | `{ctx['workspace_data_dir']}` |"
    )

    st.markdown("#### Cloud namespace (Daniel vs Ariel isolation)")
    st.caption(ctx["isolation_note"])
    preview_rows = "\n".join(
        f"| {label} | `{ctx['scoped_cloud_keys'][app_id]}` |"
        for app_id, label in NAMESPACE_PREVIEW_APPS
    )
    st.markdown(f"| App | Scoped cloud key |\n|---|---|\n{preview_rows}")

    with st.expander("Full namespace key list (all suite apps)", expanded=False):
        for key in ctx["namespace_keys"]:
            st.code(key)

    st.markdown("#### Deep links")
    st.caption("Apps opened from Command Center include your active workspace in the URL.")
    st.code(ctx["sample_app_url"] or "(no sample URL)", language="text")
    if ctx["active_workspace_id"] != DEFAULT_WORKSPACE_ID:
        st.caption(
            f"Direct app URL pattern: append `?suite_workspace={ctx['active_workspace_id']}` "
            "when not opening from Command Center."
        )

    st.markdown("#### Sign-in & password")
    if ctx["password_auth_available"]:
        try:
            from suite_auth import render_auth_panel

            render_auth_panel(st, expanded=False)
        except ImportError:
            st.button("Reset password", disabled=True, key="_acct_settings_reset_pw_stub")
    else:
        st.info(
            "**Real Accounts (Sprint C)** adds sign-in, passwords, and per-user permissions. "
            "Enable `SUITE_AUTH_ENABLED` in secrets to activate Supabase Auth. "
            "This deployment uses shared suite secrets — there is no password to reset yet."
        )

    st.markdown("#### Isolation diagnostics")
    daniel_keys = build_scoped_cloud_key_preview("daniel")
    ariel_keys = build_scoped_cloud_key_preview("ariel")
    if daniel_keys.get("applied_intelligence") == ariel_keys.get("applied_intelligence"):
        st.error(
            "Daniel and Ariel would share the same AMI cloud key — isolation is broken. "
            "Report this in Developer Mode."
        )
    else:
        st.success(
            f"Daniel AMI key `{daniel_keys['applied_intelligence']}` is separate from "
            f"Ariel `{ariel_keys['applied_intelligence']}`."
        )
