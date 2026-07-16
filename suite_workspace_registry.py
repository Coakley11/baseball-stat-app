"""
Owned workspace registry — one default workspace per authenticated account.

Local JSON registry (Phase 2) keyed by ``owner_user_id`` from ``suite_user``.
Supabase ``suite_workspaces`` can be added later; local registry is authoritative offline.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from activity_time import utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
REGISTRY_FILE = DATA_DIR / "workspaces" / "_ownership_registry.json"
ACTIVE_DIR = DATA_DIR / "workspaces" / "_active"

OWNER_USER_ID_KEY = "owner_user_id"
OWNER_EXTERNAL_ID_KEY = "owner_external_id"
WORKSPACE_ID_KEY = "workspace_id"
WORKSPACE_LABEL_KEY = "label"
CREATED_AT_KEY = "created_at"
UPDATED_AT_KEY = "updated_at"

SESSION_OWNED_WORKSPACE_KEY = "_suite_owned_workspace_id"
SESSION_OWNED_WORKSPACE_LABEL_KEY = "_suite_owned_workspace_label"

# Authorized admin accounts — email local-part is the immutable identity key.
# Resolved suite external_id ``daniel`` is NOT an admin grant by itself; it only
# describes the workspace/profile id inferred for daniel.cohen11@… emails.
ADMIN_EMAIL_LOCAL_PARTS = frozenset({"coakley11", "daniel.cohen11"})
ADMIN_ACCOUNTS = ADMIN_EMAIL_LOCAL_PARTS  # public alias used by tests/docs
_ADMIN_EXTERNAL_IDS = ADMIN_EMAIL_LOCAL_PARTS  # backward-compatible alias
_COAKLEY_EXTERNAL_ID = "coakley11"
_DANIEL_RESOLVED_EXTERNAL_ID = "daniel"
_DEMO_WORKSPACE_IDS = frozenset({"guest", "test_user"})
_ADMIN_DEMO_WORKSPACES = ("daniel", "ariel", "guest", "test_user")


def _normalize_identity(value: str) -> str:
    return str(value or "").strip().lower()


def _email_local_part(email: str) -> str:
    text = _normalize_identity(email)
    if "@" in text:
        return text.split("@", 1)[0]
    return text


def _admin_locals_from_email(email: str) -> set[str]:
    local = _email_local_part(email)
    return {local} if local else set()


def _is_admin_from_verified_locals(locals_: set[str]) -> bool:
    cleaned = {x for x in locals_ if x and x not in ("default",)}
    return bool(cleaned & ADMIN_EMAIL_LOCAL_PARTS)


def _session_mapping(session_state: Any) -> Any | None:
    """Accept dicts and Streamlit SessionState (mapping-like); reject None."""
    if session_state is None:
        return None
    if hasattr(session_state, "get"):
        return session_state
    return None


def is_admin_user(
    *,
    session_state: dict[str, Any] | None = None,
    external_id: str = "",
    email: str = "",
) -> bool:
    """
    Server-side admin authorization for developer / diagnostics / ops tools.

    Grants access only when a **verified email local-part** is ``coakley11`` or
    ``daniel.cohen11``. Fail-safe: returns False when identity cannot be
    determined — never defaults to admin.

    Workspace ids, display names, account slugs, query params, unsigned/demo
    workspaces, and forged session ``external_id`` values never grant admin.
    Bare external_id ``daniel`` is never sufficient without the daniel.cohen11 email.
    """
    verified_locals: set[str] = set()
    auth_resolved = False
    ss = _session_mapping(session_state)

    if email:
        verified_locals |= _admin_locals_from_email(email)

    if ss is not None:
        try:
            from suite_auth import (
                current_auth_email,
                is_auth_enabled,
                is_authenticated,
            )

            if is_auth_enabled():
                if not is_authenticated(ss):
                    return False
                sess_email = current_auth_email(ss)
                if not sess_email:
                    return False
                # Auth path: email is authoritative. Ignore session external_id /
                # workspace / display-name fields — those are not immutable identity.
                verified_locals |= _admin_locals_from_email(sess_email)
                auth_resolved = True
        except Exception:
            if not verified_locals:
                return False

    if auth_resolved:
        return _is_admin_from_verified_locals(verified_locals)

    if verified_locals:
        return _is_admin_from_verified_locals(verified_locals)

    # Programmatic / secrets fallback — never treat bare ``daniel`` as admin.
    ext = _normalize_identity(external_id)
    if ext == _COAKLEY_EXTERNAL_ID:
        return True
    if ext == _DANIEL_RESOLVED_EXTERNAL_ID:
        return False

    if not ext:
        try:
            from suite_user import get_external_user_id, get_user_email

            secrets_email = get_user_email()
            if secrets_email:
                return _is_admin_from_verified_locals(_admin_locals_from_email(secrets_email))
            secrets_ext = _normalize_identity(get_external_user_id())
            # Secrets suite_user_id may be ``coakley11``; never elevate on ``daniel`` alone.
            return secrets_ext == _COAKLEY_EXTERNAL_ID
        except Exception:
            return False

    return False


def _utc_now_iso() -> str:
    return utc_now_iso()


def _safe_owner_file_key(owner_user_id: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(owner_user_id or "").strip())
    return text or "unknown"


def _read_registry() -> dict[str, Any]:
    if not REGISTRY_FILE.is_file():
        return {"by_owner": {}}
    try:
        raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"by_owner": {}}
    if not isinstance(raw, dict):
        return {"by_owner": {}}
    by_owner = raw.get("by_owner")
    if not isinstance(by_owner, dict):
        raw["by_owner"] = {}
    return raw


def _write_registry(payload: dict[str, Any]) -> bool:
    try:
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = REGISTRY_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(REGISTRY_FILE)
        return True
    except OSError:
        return False


def derive_workspace_slug(*, external_id: str = "", email: str = "", display_name: str = "") -> str:
    """Stable workspace slug from account identity."""
    from suite_workspace import normalize_workspace_id

    ext = str(external_id or "").strip().lower()
    if ext and ext not in ("default",):
        return normalize_workspace_id(ext)
    email_local = str(email or "").strip().lower().split("@", 1)[0]
    if email_local:
        return normalize_workspace_id(email_local)
    if display_name:
        return normalize_workspace_id(display_name)
    return normalize_workspace_id("user")


def derive_workspace_label(*, slug: str, email: str = "", display_name: str = "") -> str:
    if display_name:
        return str(display_name).strip()
    if email and "@" in email:
        local = email.split("@", 1)[0].replace(".", " ").replace("_", " ")
        return local.title()
    from suite_workspace import workspace_label

    return workspace_label(slug)


def is_admin_account(
    *,
    external_id: str = "",
    email: str = "",
    session_state: dict[str, Any] | None = None,
) -> bool:
    """Backward-compatible alias for :func:`is_admin_user`."""
    return is_admin_user(session_state=session_state, external_id=external_id, email=email)


def admin_allowed_workspaces(*, external_id: str = "") -> tuple[str, ...]:
    """Demo presets plus the account's own slug when it is not already a preset."""
    key = _normalize_identity(external_id)
    base = list(_ADMIN_DEMO_WORKSPACES)
    if key and key not in base and key not in ("default",):
        base.append(key)
    return tuple(base)


def can_switch_workspaces(*, session_state: dict[str, Any] | None = None) -> bool:
    """True when multi-workspace picker is allowed (authorized admin only when auth is on)."""
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        if not is_auth_enabled():
            # Shared secrets / local multi-profile mode — picker stays available.
            return True
        ss = _session_mapping(session_state)
        if ss is None or not is_authenticated(ss):
            return False
        return is_admin_user(session_state=ss)
    except Exception:
        return False


def get_registry_record(owner_user_id: str) -> dict[str, Any] | None:
    oid = str(owner_user_id or "").strip()
    if not oid:
        return None
    reg = _read_registry()
    row = reg.get("by_owner", {}).get(oid)
    return dict(row) if isinstance(row, dict) else None


def list_owned_workspace_ids(*, session_state: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Workspace ids this session may use."""
    try:
        from suite_auth import allowed_workspaces_for_session, is_auth_enabled, is_authenticated

        if isinstance(session_state, dict) and is_auth_enabled() and is_authenticated(session_state):
            return allowed_workspaces_for_session(session_state)
    except ImportError:
        pass
    try:
        from suite_workspace import WORKSPACE_PRESETS

        return tuple(p["id"] for p in WORKSPACE_PRESETS)
    except ImportError:
        return ("daniel", "ariel", "guest", "test_user")


def workspace_access_allowed(workspace_id: str, *, session_state: dict[str, Any] | None = None) -> bool:
    """Reject cross-account workspace access (stale URL/session keys)."""
    from suite_workspace import normalize_workspace_id

    wid = normalize_workspace_id(workspace_id)
    allowed = frozenset(list_owned_workspace_ids(session_state=session_state))
    return wid in allowed


def _account_context(session_state: dict[str, Any]) -> dict[str, str]:
    try:
        from suite_auth import current_auth_email, resolve_auth_external_id

        email = current_auth_email(session_state)
        external_id = resolve_auth_external_id(session_state)
    except ImportError:
        email = str(session_state.get("_suite_auth_user_email") or "").strip()
        external_id = str(session_state.get("_suite_auth_external_id") or "").strip().lower()
    owner_user_id = str(session_state.get("_suite_auth_user_id") or "").strip()
    if not owner_user_id:
        try:
            from suite_user import get_account_user_id

            owner_user_id = get_account_user_id()
        except ImportError:
            owner_user_id = f"local:{external_id or 'default'}"
    display_name = ""
    try:
        from suite_user import get_display_name

        display_name = get_display_name()
    except ImportError:
        pass
    return {
        "owner_user_id": owner_user_id,
        "owner_external_id": external_id,
        "email": email,
        "display_name": display_name,
    }


def ensure_owned_workspace_for_session(session_state: dict[str, Any]) -> dict[str, Any]:
    """
    Auto-create or fetch the account's owned workspace on login/restore.

    Stores slug on session for fast access; persists registry row by owner_user_id.
    """
    ctx = _account_context(session_state)
    owner_user_id = ctx["owner_user_id"]
    slug = derive_workspace_slug(
        external_id=ctx["owner_external_id"],
        email=ctx["email"],
        display_name=ctx["display_name"],
    )
    label = derive_workspace_label(slug=slug, email=ctx["email"], display_name=ctx["display_name"])
    existing = get_registry_record(owner_user_id)
    if existing and str(existing.get(WORKSPACE_ID_KEY) or "").strip():
        slug = str(existing[WORKSPACE_ID_KEY]).strip()
        label = str(existing.get(WORKSPACE_LABEL_KEY) or label)
    else:
        reg = _read_registry()
        by_owner = dict(reg.get("by_owner") or {})
        now = _utc_now_iso()
        by_owner[owner_user_id] = {
            OWNER_USER_ID_KEY: owner_user_id,
            OWNER_EXTERNAL_ID_KEY: ctx["owner_external_id"],
            WORKSPACE_ID_KEY: slug,
            WORKSPACE_LABEL_KEY: label,
            CREATED_AT_KEY: now,
            UPDATED_AT_KEY: now,
        }
        reg["by_owner"] = by_owner
        _write_registry(reg)
        from suite_workspace import workspace_dir

        workspace_dir(slug).mkdir(parents=True, exist_ok=True)
    session_state[SESSION_OWNED_WORKSPACE_KEY] = slug
    session_state[SESSION_OWNED_WORKSPACE_LABEL_KEY] = label
    return {
        OWNER_USER_ID_KEY: owner_user_id,
        OWNER_EXTERNAL_ID_KEY: ctx["owner_external_id"],
        WORKSPACE_ID_KEY: slug,
        WORKSPACE_LABEL_KEY: label,
    }


def get_owned_workspace_id(session_state: dict[str, Any] | None = None) -> str:
    """Owned workspace slug for authenticated session; empty when auth off."""
    if not isinstance(session_state, dict):
        return ""
    cached = str(session_state.get(SESSION_OWNED_WORKSPACE_KEY) or "").strip()
    if cached:
        return cached
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        if not is_auth_enabled() or not is_authenticated(session_state):
            return ""
    except ImportError:
        return ""
    record = ensure_owned_workspace_for_session(session_state)
    return str(record.get(WORKSPACE_ID_KEY) or "").strip()


def active_workspace_persist_path(*, owner_user_id: str = "") -> Path:
    """Per-account active workspace file; global fallback when no owner id."""
    if owner_user_id:
        ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
        return ACTIVE_DIR / f"{_safe_owner_file_key(owner_user_id)}.json"
    from suite_workspace import _PERSISTED_FILE

    return _PERSISTED_FILE


def load_persisted_workspace_for_account(*, session_state: dict[str, Any] | None = None) -> str:
    """
    Account-owned workspace resolution. Reads the per-account file directly and
    never calls back into ``load_persisted_workspace_id`` (avoids recursion).
    """
    from suite_workspace import normalize_workspace_id, _load_legacy_persisted_workspace_id, _read_json

    owner_user_id = ""
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        if isinstance(session_state, dict) and is_auth_enabled() and is_authenticated(session_state):
            ctx = _account_context(session_state)
            owner_user_id = ctx["owner_user_id"]
    except ImportError:
        pass

    if owner_user_id:
        path = active_workspace_persist_path(owner_user_id=owner_user_id)
        raw = _read_json(path)
        if isinstance(raw, dict):
            wid = normalize_workspace_id(str(raw.get("workspace_id") or raw.get("active_workspace_id") or ""))
            if wid:
                if not workspace_access_allowed(wid, session_state=session_state):
                    owned = get_owned_workspace_id(session_state)
                    return owned or wid
                return wid
        owned = get_owned_workspace_id(session_state)
        if owned:
            return owned

    # No account owner: fall back to the legacy global file directly (no callback).
    return _load_legacy_persisted_workspace_id()


def persist_active_workspace_for_account(workspace_id: str, *, session_state: dict[str, Any] | None = None) -> bool:
    from suite_workspace import _PERSISTED_FILE, normalize_workspace_id, workspace_label, _write_json

    ws = normalize_workspace_id(workspace_id)
    if isinstance(session_state, dict) and not workspace_access_allowed(ws, session_state=session_state):
        owned = get_owned_workspace_id(session_state)
        if owned:
            ws = normalize_workspace_id(owned)
        else:
            return False
    payload = {
        "workspace_id": ws,
        "label": workspace_label(ws),
    }
    owner_user_id = ""
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        if isinstance(session_state, dict) and is_auth_enabled() and is_authenticated(session_state):
            ctx = _account_context(session_state)
            owner_user_id = ctx["owner_user_id"]
            payload[OWNER_USER_ID_KEY] = owner_user_id
    except ImportError:
        pass
    if owner_user_id:
        path = active_workspace_persist_path(owner_user_id=owner_user_id)
        return _write_json(path, payload)
    return _write_json(_PERSISTED_FILE, payload)
