"""Harness: focused-only mode must not chain Stage 1A-CORE."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_production_p8_binding_diagnostic import (  # noqa: E402
    focused_only_mode_enabled,
    main,
)


def test_focused_only_flag_and_env() -> None:
    assert focused_only_mode_enabled(["--focused-only"])
    assert not focused_only_mode_enabled([])
    with mock.patch.dict("os.environ", {"P8_FOCUSED_ONLY": "1"}):
        assert focused_only_mode_enabled([])


def test_focused_pass_does_not_invoke_stage1_core_when_focused_only() -> None:
    report = {"focused_p8_outcome": "FOCUSED_P8_BINDING_PASS", "required_cloud_sha": "007c39a", "p8_ladder": {}}
    with mock.patch(
        "run_production_p8_binding_diagnostic.run_diagnostic",
        return_value=report,
    ), mock.patch("run_production_stage1_authenticated.main") as core_mock:
        rc = main(["--focused-only"])
    assert rc == 0
    core_mock.assert_not_called()


def test_focused_pass_still_chains_core_by_default() -> None:
    report = {"focused_p8_outcome": "FOCUSED_P8_BINDING_PASS", "required_cloud_sha": "007c39a", "p8_ladder": {}}
    with mock.patch(
        "run_production_p8_binding_diagnostic.run_diagnostic",
        return_value=report,
    ), mock.patch("run_production_stage1_authenticated.main", return_value=0) as core_mock:
        rc = main([])
    assert rc == 0
    core_mock.assert_called_once()
