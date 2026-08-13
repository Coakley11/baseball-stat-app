"""Duplicate room_id diagnostic kwargs + fail-safe sibling exception checkpoint."""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from live_draft_control_center_ui import (  # noqa: E402
    _safe_emit_sibling_render_exception,
    render_live_draft_control_center,
)
from live_draft_stage1_pause_sibling_probe import (  # noqa: E402
    LABEL_PAUSE_SIBLING,
    PAUSE_SIBLING_DECL_PRE_DOM_ID,
    PAUSE_SIBLING_SETUP_CHECKPOINT_DOM_ID,
    PAUSE_SIBLING_SETUP_CHECKPOINTS_KEY,
    _emit_setup_checkpoint,
    _emit_sibling_declaration,
    render_stage1_pause_sibling_return_probe,
)
from live_draft_stage1_s3_process_global_diag import module_ledger_rows  # noqa: E402

ROOM = "A867DB7E"
SID = "test-sibling-decl-dup-sid"
WK = f"stage1_pause_sibling_return_{ROOM}_diag"


class _FakeSt:
    def __init__(self) -> None:
        self.markdowns: list[str] = []
        self.buttons: list[tuple[str, dict]] = []

    def markdown(self, html: str, unsafe_allow_html: bool = False) -> None:
        self.markdowns.append(str(html))

    def button(self, label: str, **kwargs):
        self.buttons.append((str(label), dict(kwargs)))
        return False

    def caption(self, *_a, **_k) -> None:
        return None

    def columns(self, *_a, **_k):
        return [_Ctx(), _Ctx()]

    def container(self, **_k):
        return _Ctx()

    def fragment(self, fn):
        return fn


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class OriginalRenderError(RuntimeError):
    pass


class CheckpointError(RuntimeError):
    pass


def _explicit_and_star_duplicate_room_id(source: str, *, call_names: frozenset[str]) -> list[str]:
    tree = ast.parse(source)
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name not in call_names:
            continue
        explicit_room = any(kw.arg == "room_id" for kw in node.keywords if kw.arg)
        stars = [kw.value for kw in node.keywords if kw.arg is None]
        if not (explicit_room and stars):
            continue
        excludes_room = False
        for exp in stars:
            generators = getattr(exp, "generators", None) or []
            for gen in generators:
                for cond in getattr(gen, "ifs", None) or []:
                    text = ast.unparse(cond)
                    if "room_id" in text and "not in" in text:
                        excludes_room = True
        if not excludes_room:
            issues.append(f"{name}:L{node.lineno}")
    return issues


class DeclarationEmitterTests(unittest.TestCase):
    def test_a_declaration_emitter_no_duplicate_room_id(self) -> None:
        st = _FakeSt()
        session: dict = {"_solo_stage1_run_id": "run-a", "_solo_stage1_script_run_seq": 3}
        with patch(
            "live_draft_stage1_pause_sibling_probe._streamlit_session_id",
            return_value=SID,
        ):
            _emit_sibling_declaration(
                st,
                session,
                phase="SIBLING_BUTTON_DECLARATION_ENTRY",
                room_id=ROOM,
                widget_key=WK,
                data={"declaration_reached": True, "declaration_invocation_id": "inv-a"},
            )
        rows = [r for r in module_ledger_rows(SID) if r.get("phase") == "SIBLING_BUTTON_DECLARATION_ENTRY"]
        self.assertTrue(rows, "SIBLING_BUTTON_DECLARATION_ENTRY module event missing")
        self.assertEqual(str(rows[-1].get("room_id") or ""), ROOM)
        blob = "\n".join(st.markdowns)
        self.assertIn(PAUSE_SIBLING_DECL_PRE_DOM_ID, blob)
        self.assertIn("SIBLING_BUTTON_DECLARATION_ENTRY", blob)

    def test_b_setup_checkpoint_emitter_no_duplicate_room_id(self) -> None:
        st = _FakeSt()
        session: dict = {"_solo_stage1_run_id": "run-b", "_solo_stage1_script_run_seq": 4}
        with patch(
            "live_draft_stage1_pause_sibling_probe._streamlit_session_id",
            return_value=SID,
        ):
            _emit_setup_checkpoint(
                st,
                session,
                event="SIBLING_BUTTON_CALL_RETURNED",
                room_id=ROOM,
                widget_key=WK,
                extra={"declaration_invocation_id": "inv-b", "returned_value": False},
            )
        rows = [r for r in module_ledger_rows(SID) if r.get("phase") == "SIBLING_BUTTON_CALL_RETURNED"]
        self.assertTrue(rows, "checkpoint module event missing")
        self.assertEqual(str(rows[-1].get("room_id") or ""), ROOM)
        self.assertTrue(session.get(PAUSE_SIBLING_SETUP_CHECKPOINTS_KEY))
        blob = "\n".join(st.markdowns)
        self.assertIn(PAUSE_SIBLING_SETUP_CHECKPOINT_DOM_ID, blob)
        self.assertIn("SIBLING_BUTTON_CALL_RETURNED", blob)

    def test_c_render_path_reaches_st_button(self) -> None:
        st = _FakeSt()
        session: dict = {
            "_solo_component_diag_enabled": True,
            "_solo_stage1_run_id": "run-c",
            "_solo_stage1_script_run_seq": 5,
        }
        room = {"draft_room_id": ROOM}
        with (
            patch(
                "live_draft_stage1_pause_sibling_probe._solo_diag_evidence",
                return_value={"solo_diag_enabled_final": True},
            ),
            patch(
                "live_draft_stage1_pause_sibling_probe._streamlit_session_id",
                return_value=SID,
            ),
            patch(
                "live_draft_stage1_fragment_identity_runtime.snapshot_fragment_identity",
                return_value={},
            ),
            patch("live_draft_streamlit_widget_metadata_diag.install_streamlit_register_widget_probe"),
            patch("live_draft_stage1_s3_server_diag.install_s3_server_diagnostics"),
            patch("live_draft_stage1_s3_server_diag.post_registration_server_snapshot", return_value={}),
            patch("live_draft_stage1_s3_server_diag.emit_s3_dom_ledger"),
        ):
            render_stage1_pause_sibling_return_probe(st, session, room)
        decl_rows = [r for r in module_ledger_rows(SID) if r.get("phase") == "SIBLING_BUTTON_DECLARATION_ENTRY"]
        self.assertTrue(decl_rows)
        self.assertTrue(any(PAUSE_SIBLING_DECL_PRE_DOM_ID in m for m in st.markdowns))
        self.assertTrue(st.buttons)
        self.assertEqual(st.buttons[0][0], LABEL_PAUSE_SIBLING)
        self.assertEqual(st.buttons[0][1].get("key"), WK)

    def test_d_exception_checkpoint_does_not_mask_original(self) -> None:
        original = OriginalRenderError("render failed")
        st = _FakeSt()
        session: dict = {}
        room = {"draft_room_id": ROOM}

        with patch(
            "live_draft_stage1_pause_sibling_probe.emit_sibling_setup_checkpoint",
            side_effect=CheckpointError("diag boom"),
        ):
            _safe_emit_sibling_render_exception(st, session, room, original)

            def _outer() -> None:
                try:
                    raise original
                except Exception as exc:
                    _safe_emit_sibling_render_exception(st, session, room, exc)
                    raise

            with self.assertRaises(OriginalRenderError) as caught:
                _outer()
            self.assertIs(caught.exception, original)

        with (
            patch(
                "live_draft_control_center_ui._resolve_commissioner",
                return_value=(True, None),
            ),
            patch(
                "live_draft_canonical_snapshot.get_live_draft_paint_snapshot",
                return_value={"team_on_clock": ""},
            ),
            patch("live_draft_cloud_diagnostics.note_control_center_mount"),
            patch("live_draft_stage1_pause_sibling_callsite_diag.emit_sibling_callsite_marker"),
            patch(
                "live_draft_stage1_pause_sibling_probe.render_stage1_pause_sibling_return_probe",
                side_effect=OriginalRenderError("render failed"),
            ),
            patch(
                "live_draft_stage1_pause_sibling_probe.emit_sibling_setup_checkpoint",
                side_effect=CheckpointError("diag boom"),
            ),
        ):
            with self.assertRaises(OriginalRenderError):
                render_live_draft_control_center(
                    st,
                    session,
                    room,
                    cfg={"timer_seconds": 60},
                    persist_room=lambda *_a, **_k: None,
                )

    def test_e_duplicate_key_static_audit(self) -> None:
        probe_src = (ROOT / "live_draft_stage1_pause_sibling_probe.py").read_text(encoding="utf-8")
        cc_src = (ROOT / "live_draft_control_center_ui.py").read_text(encoding="utf-8")
        meta_src = (ROOT / "live_draft_streamlit_widget_metadata_diag.py").read_text(encoding="utf-8")
        issues = []
        issues.extend(
            _explicit_and_star_duplicate_room_id(
                probe_src,
                call_names=frozenset({"_append_sibling_module_event", "append_module_event", "append_s3_event"}),
            )
        )
        issues.extend(
            _explicit_and_star_duplicate_room_id(
                cc_src,
                call_names=frozenset({"append_module_event", "_append_sibling_module_event"}),
            )
        )
        issues.extend(
            _explicit_and_star_duplicate_room_id(
                meta_src,
                call_names=frozenset({"append_s3_event", "append_module_event"}),
            )
        )
        self.assertEqual(issues, [], f"duplicate room_id kwargs: {issues}")
        decl_src = inspect.getsource(_emit_sibling_declaration)
        ckpt_src = inspect.getsource(_emit_setup_checkpoint)
        self.assertIn('"room_id"', decl_src)
        self.assertIn('"room_id"', ckpt_src)


if __name__ == "__main__":
    unittest.main()
