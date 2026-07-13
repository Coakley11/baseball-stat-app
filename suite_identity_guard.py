"""Protected browser identity boundary for shared-league and post-draft restores."""

from __future__ import annotations

from typing import Any

WORKSPACE_PROTECTED_SESSION_KEYS = (
    "_suite_active_workspace_id",
    "_suite_owned_workspace_id",
    "_suite_owned_workspace_label",
)

IDENTITY_GUARD_DIAG_KEY = "_suite_identity_guard_diag"
IDENTITY_LAST_MUTATOR_KEY = "_suite_identity_last_workspace_mutator"


def snapshot_protected_browser_identity(session_state: dict[str, Any]) -> dict[str, Any]:
    """Capture auth + workspace keys before applying foreign room/league/cloud state."""
    snap: dict[str, Any] = {}
    try:
        from suite_auth import snapshot_auth_session

        snap["auth"] = snapshot_auth_session(session_state)
    except ImportError:
        snap["auth"] = {}
    workspace: dict[str, Any] = {}
    for key in WORKSPACE_PROTECTED_SESSION_KEYS:
        if key in session_state:
            workspace[key] = session_state[key]
    snap["workspace"] = workspace
    snap["active_workspace_before"] = str(session_state.get("_suite_active_workspace_id") or "").strip()
    return snap


def restore_protected_browser_identity(
    session_state: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> None:
    """Re-apply browser-local auth/workspace keys saved before a state merge."""
    if not isinstance(snapshot, dict) or not snapshot:
        return
    auth = snapshot.get("auth")
    if isinstance(auth, dict) and auth:
        try:
            from suite_auth import restore_auth_session_snapshot

            restore_auth_session_snapshot(session_state, auth)
        except ImportError:
            pass
    workspace = snapshot.get("workspace")
    if isinstance(workspace, dict):
        for key, val in workspace.items():
            session_state[key] = val


def _resolve_header_identity_source(session_state: dict[str, Any]) -> str:
    if str(session_state.get("_suite_auth_user_email") or "").strip():
        return "auth_session"
    try:
        from suite_workspace_registry import _account_context

        ctx = _account_context(session_state)
        if str(ctx.get("email") or "").strip():
            return "account_context"
    except ImportError:
        pass
    return "unknown"


def build_identity_guard_diagnostics(
    session_state: dict[str, Any],
    *,
    st: Any | None = None,
    league_context: dict[str, Any] | None = None,
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only identity probe — never includes secret tokens."""
    diag: dict[str, Any] = {}
    try:
        from suite_auth import (
            account_scoped_workspace_target,
            build_auth_session_diagnostics,
            allowed_workspaces_for_session,
        )

        auth_diag = build_auth_session_diagnostics(session_state, st=st)
        diag.update(auth_diag)
        diag["auth_email"] = auth_diag.get("auth_email") or ""
        diag["auth_user_id"] = auth_diag.get("auth_user_id") or ""
        diag["auth_external_id"] = auth_diag.get("external_id") or ""
        diag["allowed_workspaces"] = tuple(allowed_workspaces_for_session(session_state))
        diag["account_scoped_workspace_target"] = account_scoped_workspace_target(session_state)
    except ImportError:
        diag["auth_email"] = str(session_state.get("_suite_auth_user_email") or "").strip()
        diag["auth_user_id"] = str(session_state.get("_suite_auth_user_id") or "").strip()
        diag["auth_external_id"] = str(session_state.get("_suite_auth_external_id") or "").strip()
        diag["cloud_user_id"] = str(session_state.get("_suite_cloud_user_id") or "").strip()
        diag["allowed_workspaces"] = ()
        diag["account_scoped_workspace_target"] = ""

    diag["cloud_user_id"] = str(
        diag.get("cloud_user_id") or session_state.get("_suite_cloud_user_id") or ""
    ).strip()
    diag["active_workspace_id"] = str(session_state.get("_suite_active_workspace_id") or "").strip()
    diag["owned_workspace_id"] = str(session_state.get("_suite_owned_workspace_id") or "").strip()

    try:
        from suite_workspace_registry import workspace_access_allowed

        active = diag["active_workspace_id"]
        diag["workspace_access_allowed"] = bool(
            active and workspace_access_allowed(active, session_state=session_state)
        )
    except ImportError:
        diag["workspace_access_allowed"] = False

    try:
        from suite_workspace import scoped_cloud_app_id

        ws = diag["active_workspace_id"] or None
        diag["scoped_cloud_app_key"] = scoped_cloud_app_id("baseball", ws)
    except ImportError:
        diag["scoped_cloud_app_key"] = ""

    diag["live_draft_participant_id"] = str(session_state.get("draft_room_participant_id") or "").strip()
    diag["live_draft_participant_team"] = str(session_state.get("draft_room_participant_team") or "").strip()

    room_host = ""
    if isinstance(room, dict):
        room_host = str(room.get("host_user_id") or room.get("host_participant_id") or "").strip()
    if not room_host:
        meta = session_state.get("draft_room_shared_meta")
        if isinstance(meta, dict):
            room_host = str(meta.get("host_user_id") or meta.get("host_participant_id") or "").strip()
    diag["room_host_user_id"] = room_host

    commissioner = ""
    ctx = league_context if isinstance(league_context, dict) else None
    if ctx is None:
        try:
            from fantasy_league_context import get_active_league_context

            loaded = get_active_league_context(session_state)
            if isinstance(loaded, dict):
                ctx = loaded
        except ImportError:
            ctx = None
    if isinstance(ctx, dict):
        meta = dict(ctx.get("metadata") or {})
        commissioner = str(meta.get("commissioner_user_id") or "").strip()
    diag["league_commissioner_user_id"] = commissioner

    prior = session_state.get(IDENTITY_GUARD_DIAG_KEY)
    if isinstance(prior, dict):
        diag["workspace_value_before_restore"] = prior.get("workspace_value_before_restore") or ""
        diag["workspace_value_after_restore"] = prior.get("workspace_value_after_restore") or ""
        diag["workspace_value_after_enforcement"] = prior.get("workspace_value_after_enforcement") or ""
    else:
        diag["workspace_value_before_restore"] = ""
        diag["workspace_value_after_restore"] = ""
        diag["workspace_value_after_enforcement"] = ""

    diag["identity_header_source"] = _resolve_header_identity_source(session_state)
    diag["last_workspace_mutator"] = str(session_state.get(IDENTITY_LAST_MUTATOR_KEY) or "").strip()
    return diag


def enforce_identity_after_state_apply(
    session_state: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
    reason: str = "",
    last_mutator: str = "",
    st: Any | None = None,
) -> dict[str, Any]:
    """
    Restore protected browser identity after room/league/disk/cloud apply, then hard-clamp workspace.

    Shared league documents may identify the commissioner; they must never replace the signed-in
    browser account or active workspace for a participant.
    """
    before = str(session_state.get("_suite_active_workspace_id") or "").strip()
    restore_protected_browser_identity(session_state, snapshot)
    after_restore = str(session_state.get("_suite_active_workspace_id") or "").strip()

    try:
        from suite_auth import enforce_workspace_ownership

        enforce_workspace_ownership(session_state)
    except ImportError:
        pass

    after_enforce = str(session_state.get("_suite_active_workspace_id") or "").strip()
    mutator = str(last_mutator or reason or "enforce_identity_after_state_apply").strip()
    if after_enforce != before and mutator:
        session_state[IDENTITY_LAST_MUTATOR_KEY] = mutator

    trace = {
        "reason": str(reason or "").strip(),
        "last_mutator": mutator,
        "workspace_value_before_restore": before or str((snapshot or {}).get("active_workspace_before") or ""),
        "workspace_value_after_restore": after_restore,
        "workspace_value_after_enforcement": after_enforce,
        "auth_external_id": str(session_state.get("_suite_auth_external_id") or "").strip(),
        "active_workspace_id": after_enforce,
    }
    session_state[IDENTITY_GUARD_DIAG_KEY] = trace
    return trace


def guard_session_mutation(
    session_state: dict[str, Any],
    mutator: str,
    *,
    st: Any | None = None,
    league_context: dict[str, Any] | None = None,
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Entry guard: snapshot identity, run caller work elsewhere, then call enforce in finally."""
    snapshot = snapshot_protected_browser_identity(session_state)
    session_state["_suite_identity_guard_pending"] = {
        "snapshot": snapshot,
        "mutator": str(mutator or "").strip(),
    }
    return snapshot


def finalize_session_mutation_guard(
    session_state: dict[str, Any],
    *,
    st: Any | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Exit guard after a guarded mutation block."""
    pending = session_state.pop("_suite_identity_guard_pending", None)
    snapshot = None
    mutator = str(reason or "").strip()
    if isinstance(pending, dict):
        snapshot = pending.get("snapshot")
        mutator = str(pending.get("mutator") or mutator or "").strip()
    return enforce_identity_after_state_apply(
        session_state,
        snapshot=snapshot if isinstance(snapshot, dict) else None,
        reason=reason or mutator,
        last_mutator=mutator,
        st=st,
    )


def apply_state_with_identity_guard(
    st: Any,
    apply_state: Any,
    state: dict[str, Any],
    *,
    reason: str,
    last_mutator: str = "",
) -> dict[str, Any]:
    """Wrap workspace blob apply with snapshot → apply → identity enforcement."""
    snapshot = snapshot_protected_browser_identity(st.session_state)
    apply_state(st, state)
    return enforce_identity_after_state_apply(
        st.session_state,
        snapshot=snapshot,
        reason=reason,
        last_mutator=last_mutator or reason,
        st=st,
    )


def render_identity_guard_diagnostic_panel(
    st: Any,
    session_state: dict[str, Any],
    *,
    title: str = "Account / workspace identity (Developer Mode)",
    league_context: dict[str, Any] | None = None,
    room: dict[str, Any] | None = None,
    expanded: bool = False,
) -> None:
    """Temporary diagnostic panel for post-draft and Saved Draft Library acceptance."""
    try:
        from suite_workspace import developer_mode_checkbox_enabled
    except ImportError:
        return
    if not developer_mode_checkbox_enabled(st=st):
        return

    diag = build_identity_guard_diagnostics(
        session_state,
        st=st,
        league_context=league_context,
        room=room,
    )
    rows = [
        ("auth_email", diag.get("auth_email") or "—"),
        ("auth_user_id", diag.get("auth_user_id") or "—"),
        ("auth_external_id", diag.get("auth_external_id") or "—"),
        ("cloud_user_id", diag.get("cloud_user_id") or "—"),
        ("active_workspace_id", diag.get("active_workspace_id") or "—"),
        ("owned_workspace_id", diag.get("owned_workspace_id") or "—"),
        ("allowed_workspaces", ", ".join(diag.get("allowed_workspaces") or ()) or "—"),
        ("account_scoped_workspace_target", diag.get("account_scoped_workspace_target") or "—"),
        ("workspace_access_allowed", diag.get("workspace_access_allowed")),
        ("scoped_cloud_app_key", diag.get("scoped_cloud_app_key") or "—"),
        ("live_draft_participant_id", diag.get("live_draft_participant_id") or "—"),
        ("live_draft_participant_team", diag.get("live_draft_participant_team") or "—"),
        ("room_host_user_id", diag.get("room_host_user_id") or "—"),
        ("league_commissioner_user_id", diag.get("league_commissioner_user_id") or "—"),
        ("workspace_value_before_restore", diag.get("workspace_value_before_restore") or "—"),
        ("workspace_value_after_restore", diag.get("workspace_value_after_restore") or "—"),
        ("workspace_value_after_enforcement", diag.get("workspace_value_after_enforcement") or "—"),
        ("identity_header_source", diag.get("identity_header_source") or "—"),
        ("last_workspace_mutator", diag.get("last_workspace_mutator") or "—"),
    ]
    with st.expander(title, expanded=expanded):
        import pandas as pd

        st.dataframe(
            pd.DataFrame([{"field": k, "value": v} for k, v in rows]),
            width="stretch",
            hide_index=True,
        )
        st.caption("Tokens are never shown. Header uses auth session first, not commissioner metadata.")
