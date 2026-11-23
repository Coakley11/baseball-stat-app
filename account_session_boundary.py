"""The one account boundary for a browser session (security hotfix 2026-11-23).

Account data may enter or stay in a Streamlit session only for the *verified* identity: a complete
Supabase auth session (session flag, user id, and both tokens, set by a successful sign-in or token
restore in this server session). Raw user ids, restored workspace labels, query parameters and
workspace blobs are never proof of identity.

``enforce_account_session_boundary`` runs at the start of every script run, before any workspace,
draft, strategy, league or settings data is loaded:

* a half-signed-in session (session flag without a complete auth session) is reduced to a guest;
* the account whose data the session holds is tracked; when the verified identity differs from it
  (sign-out, failed or partial restore, another account signing in) every account-scoped key is
  cleared before anything else runs, so the next identity starts like a fresh browser;
* a guest's active workspace is always its own private temporary workspace.

``account_data_load_allowed`` is the check the workspace loaders call before applying a blob.
"""

from __future__ import annotations

from typing import Any

SESSION_DATA_OWNER_KEY = "_suite_session_data_owner"
BOUNDARY_LAST_CHANGE_KEY = "_suite_session_boundary_last_change"
GUEST_OWNER = ""


def _auth():
    import suite_auth  # noqa: WPS433 (lazy: suite_auth imports heavy modules)

    return suite_auth


def verified_account_id(session: Any) -> str:
    """The signed-in account id only when this session holds a complete auth session; else "".

    With sign-in disabled (single-user install) the configured local owner is the identity.
    """
    try:
        sa = _auth()
    except ImportError:
        return ""
    try:
        if not sa.is_auth_enabled():
            return "local"
        if not sa.auth_session_complete(session):
            return GUEST_OWNER
        return str(session.get(sa.AUTH_USER_ID_KEY) or "").strip()
    except Exception:
        return GUEST_OWNER


def account_data_load_allowed(session: Any) -> bool:
    """Whether saved account data may be applied to this session (a verified identity exists)."""
    return bool(verified_account_id(session))


def _demote_partial_sign_in(session: Any, st: Any | None) -> bool:
    """A session flag without a complete auth session is not a sign-in: clear the auth keys."""
    try:
        sa = _auth()
        if not sa.is_auth_enabled() or not session.get(sa.AUTH_SESSION_KEY):
            return False
        if sa.auth_session_complete(session):
            return False
        sa._clear_auth_session(session, st=st, invalidate_bridge=False)
        return True
    except Exception:
        return False


def _clear_account_scoped_state(session: Any) -> None:
    try:
        _auth()._clear_previous_session_work(session)
    except Exception:
        try:
            from suite_user_persistence import clear_account_session_state

            clear_account_session_state(session)
        except Exception:
            pass
    for key in (
        "_baseball_warm_startup_fp",
        "_suite_owned_workspace_id",
        "_suite_owned_workspace_label",
        "_suite_cloud_user_id",
        "_suite_post_auth_workflow_hydrate",
        "_suite_post_auth_workflow_hydration_rerun_done",
        "_suite_startup_restored_workspace_id",
    ):
        session.pop(key, None)
    session["_suite_workspace_force_sync"] = True


def _pin_guest_workspace(session: Any) -> None:
    try:
        sa = _auth()
        from suite_workspace import SESSION_KEY

        if sa.is_auth_enabled():
            session[SESSION_KEY] = sa.guest_workspace_id(session)
    except Exception:
        pass


def enforce_account_session_boundary(session: Any, *, st: Any | None = None) -> dict[str, Any]:
    """Apply the boundary for this run. Returns what happened (no secrets, ids shortened)."""
    demoted = _demote_partial_sign_in(session, st)
    current = verified_account_id(session)
    if current == "local":
        session[SESSION_DATA_OWNER_KEY] = current
        return {"changed": False, "demoted": demoted}
    has_prior = SESSION_DATA_OWNER_KEY in session
    prior = str(session.get(SESSION_DATA_OWNER_KEY) or "") if has_prior else None
    # A new server session holds no account data yet; afterwards any identity change clears it.
    changed = bool(has_prior and prior != current) or demoted
    if changed:
        _clear_account_scoped_state(session)
        session[BOUNDARY_LAST_CHANGE_KEY] = f"{(prior or '-')[:8]}->{(current or 'guest')[:8]}"
    if current == GUEST_OWNER:
        _pin_guest_workspace(session)
    session[SESSION_DATA_OWNER_KEY] = current
    return {"changed": changed, "demoted": demoted}
