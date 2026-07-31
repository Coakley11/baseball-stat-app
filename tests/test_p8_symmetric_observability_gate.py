"""Gate checks for symmetric observability commits."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from p8_canary_build_gate import commit_has_symmetric_observability, git_head_short


def test_symmetric_observability_on_head():
    sha = git_head_short()
    impl = commit_has_symmetric_observability(sha)
    assert impl.get("file_widget_identity_py")
    assert impl.get("declaration_identity_fields")
    assert impl.get("ultra_early_global_canary_hook")
    assert impl.get("ok"), impl
