"""Run AMI draft solver locally for instant Baseball Insight on submit."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_AMI_REPO = Path(__file__).resolve().parent.parent / "Applied-mathematical-intelligence"


def _ensure_ami_path() -> bool:
    path = str(_AMI_REPO)
    if not _AMI_REPO.is_dir():
        log.warning("AMI repo not found at %s", _AMI_REPO)
        return False
    if path not in sys.path:
        sys.path.insert(0, path)
    return True


def solve_instant_baseball_insight(
    question: str,
    context: dict[str, Any] | None,
) -> tuple[Any, Any] | None:
    """Return (route, SolverResult) or None if solver unavailable."""
    if not _ensure_ami_path():
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
