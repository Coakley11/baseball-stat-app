"""Server-log deployment identity and probe tracing (Cloud logs only)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent
_DEPLOY_COMMIT_FILE = _REPO_ROOT / "deploy_commit.txt"
_STARTUP_IDENTITY_EMITTED = False

REGISTERED_CONTEXT_MARKERS = (
    "validate_registered_declaration_context",
    "explicit_declaration_room",
    "validated_registered_declaration_context",
)


def _print_log(line: str) -> None:
    print(str(line).strip(), flush=True)


def _run_git(args: list[str], cwd: Path) -> tuple[str, str]:
    """Return (stdout, error_message). error_message empty on success."""
    try:
        out = subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=8,
        )
        return out.strip(), ""
    except Exception as exc:
        return "", f"{type(exc).__name__}:{exc}"


def read_deploy_commit_pin() -> tuple[str, str]:
    """Return (pin, error)."""
    if not _DEPLOY_COMMIT_FILE.is_file():
        return "", "deploy_commit.txt missing"
    try:
        line = _DEPLOY_COMMIT_FILE.read_text(encoding="utf-8").splitlines()[0]
        pin = line.split("#", 1)[0].strip()
        if not pin:
            return "", "deploy_commit.txt first line empty"
        return pin[:7] if len(pin) > 7 else pin, ""
    except Exception as exc:
        return "", f"{type(exc).__name__}:{exc}"


def registered_context_implementation_present(repo_root: Path | None = None) -> bool:
    root = repo_root or _REPO_ROOT
    path = root / "live_draft_solo_declaration_room_context.py"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    return all(marker in text for marker in REGISTERED_CONTEXT_MARKERS)


def collect_git_identity(repo_root: Path | None = None) -> dict[str, str]:
    root = repo_root or _REPO_ROOT
    head, head_err = _run_git(["rev-parse", "HEAD"], root)
    branch, branch_err = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    pin, pin_err = read_deploy_commit_pin()
    decl_path = root / "live_draft_solo_declaration_room_context.py"
    return {
        "git_head": head,
        "git_head_error": head_err,
        "branch": branch,
        "branch_error": branch_err,
        "deploy_pin": pin,
        "deploy_pin_error": pin_err,
        "cwd": str(Path.cwd().resolve()),
        "repo_root": str(root.resolve()),
        "declaration_room_context_exists": str(decl_path.is_file()),
        "registered_context_impl": str(registered_context_implementation_present(root)),
    }


def format_startup_identity_line(*, entry_file: str, identity: dict[str, str]) -> str:
    parts = [
        "SOLO_CLOUD_DEPLOY_IDENTITY",
        f"git_head={identity.get('git_head') or identity.get('git_head_error') or 'unknown'}",
        f"branch={identity.get('branch') or identity.get('branch_error') or 'unknown'}",
        f"deploy_pin={identity.get('deploy_pin') or identity.get('deploy_pin_error') or 'unknown'}",
        f"cwd={identity.get('cwd') or ''}",
        f"file={entry_file}",
        f"declaration_room_context_exists={identity.get('declaration_room_context_exists')}",
        f"registered_context_impl={identity.get('registered_context_impl')}",
    ]
    if identity.get("git_head_error"):
        parts.append(f"git_head_error={identity['git_head_error']}")
    if identity.get("branch_error"):
        parts.append(f"branch_error={identity['branch_error']}")
    if identity.get("deploy_pin_error"):
        parts.append(f"deploy_pin_error={identity['deploy_pin_error']}")
    return " ".join(parts)


def emit_startup_identity_once(entry_file: str) -> None:
    global _STARTUP_IDENTITY_EMITTED
    if _STARTUP_IDENTITY_EMITTED:
        return
    _STARTUP_IDENTITY_EMITTED = True
    try:
        identity = collect_git_identity()
        _print_log(format_startup_identity_line(entry_file=entry_file, identity=identity))
    except Exception as exc:
        _print_log(
            "SOLO_CLOUD_DEPLOY_IDENTITY "
            f"git_head=error branch=error deploy_pin=error "
            f"exception={type(exc).__name__}:{exc}"
        )
        _print_log(traceback.format_exc())


def log_deploy_probe_import_status() -> None:
    try:
        from live_draft_solo_expire_chain import render_solo_deploy_probe  # noqa: F401

        _print_log("SOLO_DEPLOY_PROBE_IMPORT_OK")
    except Exception as exc:
        _print_log(f"SOLO_DEPLOY_PROBE_IMPORT_FAILED {type(exc).__name__}: {exc}")
        _print_log(traceback.format_exc())


def _query_diag_value(st: Any | None, name: str) -> str:
    if st is None:
        return ""
    try:
        from live_draft_cloud_diagnostics import _qp_get

        return str(_qp_get(st, name) or "")
    except ImportError:
        try:
            params = st.query_params
            return str(params.get(name) or "")
        except Exception:
            return ""


def _suite_sid_present(session: dict[str, Any], st: Any | None) -> bool:
    if str(session.get("suite_sid") or "").strip():
        return True
    if st is not None:
        try:
            return "suite_sid=" in str(getattr(st, "context", None) and st.context.url or "")
        except Exception:
            pass
    return bool(_query_diag_value(st, "suite_sid"))


def log_ldr_branch_entered(st: Any, session: dict[str, Any], active_page: str) -> None:
    identity = collect_git_identity()
    pin, _ = read_deploy_commit_pin()
    head = identity.get("git_head") or identity.get("git_head_error") or "unknown"
    _print_log(
        "SOLO_LDR_BRANCH_ENTERED "
        f"git_head={head} "
        f"deploy_pin={pin or identity.get('deploy_pin_error') or 'unknown'} "
        f"active_page={active_page!s} "
        f"suite_sid={'present' if _suite_sid_present(session, st) else 'absent'} "
        f"solo_component_diag={_query_diag_value(st, 'solo_component_diag') or 'absent'} "
        f"ts={time.time()}"
    )


def log_deploy_probe_call_begin() -> None:
    _print_log("SOLO_DEPLOY_PROBE_CALL_BEGIN")


def log_deploy_probe_call_end() -> None:
    _print_log("SOLO_DEPLOY_PROBE_CALL_END")


def log_deploy_probe_call_failed(exc: BaseException) -> None:
    _print_log(f"SOLO_DEPLOY_PROBE_CALL_FAILED {type(exc).__name__}: {exc}")
    _print_log(traceback.format_exc())


def render_visible_deploy_diag_caption(st: Any, session: dict[str, Any], *, sha: str, build: str) -> None:
    """Plain visible caption for harness scrape; diagnostic URL/mode only."""
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled
    except ImportError:
        return
    if not solo_component_diag_enabled(st, session):
        return
    st.caption(f"solo-deploy-build {sha} {build}")


__all__ = [
    "collect_git_identity",
    "emit_startup_identity_once",
    "format_startup_identity_line",
    "log_deploy_probe_call_begin",
    "log_deploy_probe_call_end",
    "log_deploy_probe_call_failed",
    "log_deploy_probe_import_status",
    "log_ldr_branch_entered",
    "read_deploy_commit_pin",
    "registered_context_implementation_present",
    "render_visible_deploy_diag_caption",
]
