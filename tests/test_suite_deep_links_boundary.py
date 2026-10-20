"""Command Center deep links work from a Baseball checkout alone.

``suite_deep_links`` is a shared suite module. Its Music branch uses ``music_resume_payload``,
which only the Music-facing apps ship. A top-level import made every deep link (and so every
Command Center handoff: Get full analysis, the Baseball Insight box, Hall of Fame case sends,
per-page sends) fail in Baseball. These run in a fresh interpreter that ignores the environment
and refuses to import ``music_resume_payload`` from anywhere."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BLOCK_MUSIC = textwrap.dedent("""
    import importlib.abc, sys
    class _NoMusic(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "music_resume_payload":
                raise ModuleNotFoundError("No module named 'music_resume_payload' (blocked by test)")
            return None
    sys.meta_path.insert(0, _NoMusic())
""")


def _run(code: str, *, extra_path: str = "", block_music: bool = True) -> dict:
    script = (BLOCK_MUSIC if block_music else "") + textwrap.dedent(f"""
        import json, sys
        sys.path.insert(0, {str(ROOT)!r})
        {"sys.path.insert(0, " + repr(extra_path) + ")" if extra_path else ""}
    """) + textwrap.dedent(code)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONIOENCODING"] = "utf-8"
    out = subprocess.run([sys.executable, "-E", "-s", "-c", script], cwd=str(ROOT), env=env,
                         capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


class DeepLinksWithoutMusicModuleTests(unittest.TestCase):
    def test_baseball_and_command_center_links_build(self):
        result = _run("""
            from suite_deep_links import build_resume_action_url
            from suite_analytical_question import build_applied_math_resume_url
            payload = {"question": "Who hit the most home runs in 2022?", "question_id": "q1", "source_app": "baseball",
                       "resume_key": "ami:q1", "context": {"page": "Historical Explorer"}}
            print(json.dumps({
                "ami": build_applied_math_resume_url(payload),
                "baseball": build_resume_action_url("baseball", resume_key="compare:Aaron Judge:Juan Soto"),
                "hof": build_resume_action_url("baseball", resume_key="hof:ami:q3", page="Career Totals",
                                               metrics={"target_player": "Andruw Jones", "hof_case_mode": True}),
                "music_plain": build_resume_action_url("music", resume_key="song:pick-1", metrics={"pick_key": "pick-1"}),
            }))
        """)
        self.assertIn("suite_resume=ami%3Aq1", result["ami"])
        self.assertIn("suite_page=Solve+a+Problem", result["ami"])
        self.assertIn("Who+hit+the+most+home+runs", result["ami"])
        self.assertIn("suite_resume=compare%3AAaron", result["baseball"])
        self.assertIn("suite_page=Career+Totals", result["hof"])
        self.assertIn("suite_pick_key=pick-1", result["music_plain"], "a Music link without a typed payload needs nothing")

    def test_every_caller_module_imports(self):
        result = _run("""
            import importlib
            mods = ["suite_deep_links", "suite_analytical_question", "suite_activity_client", "baseball_hof_activity",
                    "applied_math_return_insight", "suite_workspace_deep_link_audit", "baseball_ami_sidebar"]
            print(json.dumps({m: bool(importlib.import_module(m)) for m in mods}))
        """)
        self.assertTrue(all(result.values()), result)

    def test_music_names_stay_reachable_where_the_module_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "music_resume_payload.py").write_text(textwrap.dedent("""
                def encode_payload_b64(p): return "ENC"
                def decode_payload_b64(s): return {"decoded": s}
                def legacy_resume_key_for_payload(p): return "song:" + str(p.get("pick_key"))
                def normalize_resume_kind(k): return k or "song"
            """), encoding="utf-8")
            result = _run("""
                import suite_deep_links as d
                url = d.build_resume_action_url("music", resume_key="backing:pick-9",
                                                metrics={"resume_payload": {"resume_kind": "backing", "pick_key": "pick-9"}})
                print(json.dumps({"url": url, "decode": d.decode_payload_b64("x")}))
            """, extra_path=tmp, block_music=False)
        self.assertIn("suite_resume_payload=ENC", result["url"])
        self.assertIn("suite_resume=song%3Apick-9", result["url"])
        self.assertEqual(result["decode"], {"decoded": "x"})

    def test_a_music_payload_link_still_needs_the_music_module(self):
        result = _run("""
            import suite_deep_links as d
            try:
                d.build_music_continue_url({"resume_kind": "backing", "pick_key": "p"}, base_url="https://m.example")
                print(json.dumps({"raised": False}))
            except ModuleNotFoundError:
                print(json.dumps({"raised": True}))
        """)
        self.assertTrue(result["raised"], "only the Music-payload path depends on the Music module")


if __name__ == "__main__":
    unittest.main()
