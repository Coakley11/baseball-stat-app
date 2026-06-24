"""Deploy marker for Baseball app — commit resolved at runtime, not hardcoded."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_DEPLOY_COMMIT_FILE = _ROOT / "deploy_commit.txt"
STREAMLIT_ENTRYPOINT = "streamlit_app.py"
MP_DRAFT_CODE_GENERATION = "2026-06-mp-v1"
TREND_ACTIVITY_DIAGNOSTICS_LIVE = True

_ENV_COMMIT_KEYS = (
    "STREAMLIT_CLOUD_COMMIT",
    "SOURCE_VERSION",
    "COMMIT_SHA",
    "GIT_COMMIT",
    "VERCEL_GIT_COMMIT_SHA",
    "GITHUB_SHA",
)

_ENV_BRANCH_KEYS = (
    "STREAMLIT_CLOUD_BRANCH",
    "GITHUB_REF_NAME",
    "GIT_BRANCH",
)


@lru_cache(maxsize=1)
def resolve_git_commit_short() -> str:
    """Best-effort short SHA for the deployed revision."""
    for key in _ENV_COMMIT_KEYS:
        val = os.environ.get(key, "").strip()
        if val:
            return val[:7] if len(val) > 7 else val
    if _DEPLOY_COMMIT_FILE.is_file():
        for line in _DEPLOY_COMMIT_FILE.read_text(encoding="utf-8").splitlines():
            token = line.strip().split("#", 1)[0].strip()
            if token and token.lower() != "unknown":
                return token[:7] if len(token) > 7 else token
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        ).strip()
    except Exception:
        pass
    return "unknown"


@lru_cache(maxsize=1)
def resolve_git_branch() -> str:
    for key in _ENV_BRANCH_KEYS:
        val = os.environ.get(key, "").strip()
        if val:
            return val.replace("refs/heads/", "")
    if _DEPLOY_COMMIT_FILE.is_file():
        for line in _DEPLOY_COMMIT_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().lower().startswith("branch:"):
                token = line.split(":", 1)[1].strip()
                if token:
                    return token
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        ).strip()
    except Exception:
        pass
    return "dev"


@lru_cache(maxsize=1)
def resolve_commit_source() -> str:
    for key in _ENV_COMMIT_KEYS:
        if os.environ.get(key, "").strip():
            return f"env:{key}"
    if _DEPLOY_COMMIT_FILE.is_file():
        for line in _DEPLOY_COMMIT_FILE.read_text(encoding="utf-8").splitlines():
            token = line.strip().split("#", 1)[0].strip()
            if token and token.lower() != "unknown":
                return "deploy_commit.txt"
    try:
        subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return "git"
    except Exception:
        pass
    return "unknown"


def format_build_label() -> str:
    return f"baseball-dev-{resolve_git_commit_short()}"


def format_deploy_caption() -> str:
    return (
        f"Build `{format_build_label()}` · commit `{resolve_git_commit_short()}` · "
        f"branch `{resolve_git_branch()}` · entry `{STREAMLIT_ENTRYPOINT}`"
    )


def runtime_feature_verification() -> dict[str, str]:
    """Confirm multiplayer fix modules are loaded in this process."""
    flags: dict[str, str] = {
        "deploy_commit": resolve_git_commit_short(),
        "deploy_commit_source": resolve_commit_source(),
        "deploy_branch": resolve_git_branch(),
        "entrypoint": STREAMLIT_ENTRYPOINT,
        "mp_draft_code_generation": MP_DRAFT_CODE_GENERATION,
    }
    try:
        from draft_room_participant_state import mark_participant_left_room

        flags["leave_room_fix"] = "present" if callable(mark_participant_left_room) else "missing"
    except ImportError:
        flags["leave_room_fix"] = "missing"
    try:
        from draft_room_context import active_participant_team, leave_shared_draft_room

        flags["leave_shared_draft_room"] = "present" if callable(leave_shared_draft_room) else "missing"
        flags["active_participant_team"] = "present" if callable(active_participant_team) else "missing"
    except ImportError:
        flags["leave_shared_draft_room"] = "missing"
        flags["active_participant_team"] = "missing"
    try:
        import draft_room_runtime_diagnostics as drd

        flags["runtime_diagnostics"] = (
            "present" if hasattr(drd, "render_runtime_diagnostic_table") else "missing"
        )
    except ImportError:
        flags["runtime_diagnostics"] = "missing"
    return flags


# Backward-compatible module-level aliases (resolved once at import).
GIT_COMMIT_SHORT = resolve_git_commit_short()
GIT_BRANCH = resolve_git_branch()
SUITE_BUILD_LABEL = format_build_label()
