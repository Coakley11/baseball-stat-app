"""Run AMI draft solver locally for instant Baseball Insight on submit."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent


def _ami_repo_candidates() -> list[Path]:
    env_path = str(os.environ.get("AMI_REPO_PATH") or os.environ.get("STREAMLIT_AMI_REPO") or "").strip()
    names = (
        "Applied-mathematical-intelligence",
        "applied-mathematical-intelligence",
        "Applied_mathematical_intelligence",
    )
    out: list[Path] = []
    if env_path:
        out.append(Path(env_path))
    for base in (_REPO_ROOT.parent, _REPO_ROOT, Path("/mount/src")):
        for name in names:
            out.append(base / name)
    seen: set[str] = set()
    unique: list[Path] = []
    for path in out:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def ami_solver_availability() -> dict[str, Any]:
    """Report whether the AMI solver stack is importable on this runtime."""
    for path in _ami_repo_candidates():
        if not path.is_dir():
            continue
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        try:
            from components.applied_math_solvers import solve_suite_question  # noqa: F401

            return {
                "repo_found": True,
                "repo_path": str(path),
                "reason": "ok",
            }
        except Exception as exc:
            log.debug("AMI import failed from %s: %s", path, exc)
            continue
    return {
        "repo_found": False,
        "repo_path": "",
        "reason": "ami_repo_not_found",
    }


def _ensure_ami_path() -> bool:
    return bool(ami_solver_availability().get("repo_found"))


def solve_instant_baseball_insight(
    question: str,
    context: dict[str, Any] | None,
) -> tuple[Any, Any] | None:
    """Return (route, SolverResult) or None if solver unavailable."""
    avail = ami_solver_availability()
    if not avail.get("repo_found"):
        log.warning("AMI repo not found for instant solve (%s)", avail.get("reason"))
        return None
    try:
        from components.applied_math_solvers import solve_suite_question

        return solve_suite_question(
            str(question or "").strip(),
            source_app="baseball",
            context=dict(context or {}),
        )
    except Exception:
        log.exception("instant AMI solve failed")
        return None
