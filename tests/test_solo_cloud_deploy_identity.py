"""Tests for Cloud deploy identity logging and diagnostic deploy probe."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class SoloCloudDeployIdentityTests(unittest.TestCase):
    def test_deploy_commit_pin_reads_71fac8b(self) -> None:
        from solo_cloud_deploy_identity import read_deploy_commit_pin

        pin, err = read_deploy_commit_pin()
        self.assertFalse(err, err)
        self.assertEqual(pin, "71fac8b")

    def test_git_identity_failure_logged_explicitly(self) -> None:
        from solo_cloud_deploy_identity import collect_git_identity, emit_startup_identity_once

        solo_cloud_deploy_identity = __import__("solo_cloud_deploy_identity")
        solo_cloud_deploy_identity._STARTUP_IDENTITY_EMITTED = False
        buf = io.StringIO()
        with mock.patch(
            "solo_cloud_deploy_identity._run_git",
            side_effect=lambda args, cwd: ("", "CalledProcessError:git failed"),
        ):
            with redirect_stdout(buf):
                emit_startup_identity_once(str(ROOT / "streamlit_app.py"))
        out = buf.getvalue()
        self.assertIn("SOLO_CLOUD_DEPLOY_IDENTITY", out)
        self.assertIn("git_head_error=", out)

    def test_probe_import_failure_not_swallowed(self) -> None:
        from solo_cloud_deploy_identity import log_deploy_probe_import_status

        buf = io.StringIO()
        with mock.patch.dict(
            "sys.modules",
            {"live_draft_solo_expire_chain": None},
        ):
            with redirect_stdout(buf):
                log_deploy_probe_import_status()
        out = buf.getvalue()
        self.assertIn("SOLO_DEPLOY_PROBE_IMPORT_FAILED", out)

    def test_probe_import_ok_line(self) -> None:
        from solo_cloud_deploy_identity import log_deploy_probe_import_status

        buf = io.StringIO()
        with redirect_stdout(buf):
            log_deploy_probe_import_status()
        self.assertIn("SOLO_DEPLOY_PROBE_IMPORT_OK", buf.getvalue())

    def test_registered_context_markers_detected(self) -> None:
        from solo_cloud_deploy_identity import registered_context_implementation_present

        self.assertTrue(registered_context_implementation_present(ROOT))

    def test_diag_caption_shows_sha_build(self) -> None:
        from solo_cloud_deploy_identity import render_visible_deploy_diag_caption

        st = mock.MagicMock()
        session = {"_solo_component_diag_enabled": True}
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            render_visible_deploy_diag_caption(
                st,
                session,
                sha="71fac8b",
                build="baseball-dev-71fac8b",
            )
        st.caption.assert_called_once()
        arg = st.caption.call_args[0][0]
        self.assertIn("solo-deploy-build", arg)
        self.assertIn("71fac8b", arg)
        self.assertIn("baseball-dev-71fac8b", arg)

    def test_diag_caption_hidden_when_not_diag(self) -> None:
        from solo_cloud_deploy_identity import render_visible_deploy_diag_caption

        st = mock.MagicMock()
        session: dict = {}
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=False,
        ):
            render_visible_deploy_diag_caption(
                st,
                session,
                sha="71fac8b",
                build="baseball-dev-71fac8b",
            )
        st.caption.assert_not_called()

    def test_render_solo_deploy_probe_invoked_with_session(self) -> None:
        from live_draft_solo_expire_chain import render_solo_deploy_probe

        st = mock.MagicMock()
        session = {"_solo_component_diag_enabled": True}
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            render_solo_deploy_probe(st, session)
        st.markdown.assert_called()
        joined = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("solo-deploy-build", joined)


if __name__ == "__main__":
    unittest.main()
