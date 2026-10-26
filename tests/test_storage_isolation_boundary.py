"""A test or QA run of Baseball can never write into a real sibling Command Center store.

Each case runs suite_activity_client from a throwaway "checkout" next to a fake sibling
daniel-ai-command-center and a fake ~/Documents/GitHub/daniel-ai-command-center, whose suite_storage.py
only records that it was used. HOME/USERPROFILE point at the fake home, so the real one is never involved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = textwrap.dedent("""
    from pathlib import Path
    def _mark(*args, **kwargs):
        (Path(__file__).parent / "USED").write_text("written", encoding="utf-8")
    record_activity = _mark
    def __getattr__(name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _mark
""")


class StorageIsolationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.checkout = self.tmp / "baseball-checkout"
        self.checkout.mkdir()
        for name in ("suite_activity_client.py", "activity_time.py"):
            shutil.copy(ROOT / name, self.checkout / name)
        self.sibling = self.tmp / "daniel-ai-command-center"
        self.home_cc = self.tmp / "home" / "Documents" / "GitHub" / "daniel-ai-command-center"
        for cc in (self.sibling, self.home_cc):
            cc.mkdir(parents=True)
            (cc / "suite_storage.py").write_text(SENTINEL, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, **env_extra: str) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in ("SUITE_STORAGE_ISOLATED", "SUITE_COMMAND_CENTER_ROOT")}
        env.update({"HOME": str(self.tmp / "home"), "USERPROFILE": str(self.tmp / "home"), **env_extra})
        code = textwrap.dedent("""
            import json, sys
            import suite_activity_client as c
            c.record_activity("baseball", "qa_probe", page="Home", metrics={"k": 1}, summary="probe")
            print(json.dumps({"pytest_loaded": "pytest" in sys.modules,
                              "roots": [str(r) for r in c.command_center_root_candidates()]}))
        """)
        out = subprocess.run([sys.executable, "-E", "-s", "-c", code], cwd=self.checkout, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def _used(self) -> dict:
        return {"sibling": (self.sibling / "USED").exists(), "home": (self.home_cc / "USED").exists()}

    def test_isolated_run_without_a_shim_never_reaches_a_sibling_store(self) -> None:
        res = self._run(SUITE_STORAGE_ISOLATED="1")
        self.assertFalse(res["pytest_loaded"])
        self.assertEqual(res["roots"], [str(self.checkout.resolve())])
        self.assertEqual(self._used(), {"sibling": False, "home": False})
        fallback = list((self.checkout / "data").glob("*activity_fallback.json"))
        self.assertTrue(fallback, "the write lands in this checkout's own JSON fallback")

    def test_isolated_run_uses_the_checkouts_own_private_store(self) -> None:
        (self.checkout / "suite_storage.py").write_text(SENTINEL, encoding="utf-8")
        self._run(SUITE_STORAGE_ISOLATED="1")
        self.assertTrue((self.checkout / "USED").exists())
        self.assertEqual(self._used(), {"sibling": False, "home": False})

    def test_explicit_root_is_the_only_store(self) -> None:
        private = self.tmp / "qa-private-cc"
        private.mkdir()
        (private / "suite_storage.py").write_text(SENTINEL, encoding="utf-8")
        res = self._run(SUITE_COMMAND_CENTER_ROOT=str(private))
        self.assertEqual(res["roots"], [str(private.resolve())])
        self.assertTrue((private / "USED").exists())
        self.assertEqual(self._used(), {"sibling": False, "home": False})

    def test_normal_local_run_still_uses_the_sibling_command_center(self) -> None:
        # Unchanged non-test behaviour: with no shim and no isolation, the sibling Command Center store is used.
        self._run()
        self.assertEqual(self._used(), {"sibling": True, "home": False})

    def test_pytest_itself_isolates_this_process(self) -> None:
        import suite_activity_client as c

        self.assertTrue(c.storage_isolated())
        self.assertEqual(os.environ.get("SUITE_STORAGE_ISOLATED"), "1", "conftest exports isolation to subprocesses")
        roots = c.command_center_root_candidates()
        self.assertEqual(roots, (Path(c.__file__).resolve().parent,))
        self.assertFalse(any("daniel-ai-command-center" in str(r) for r in roots))


if __name__ == "__main__":
    unittest.main()
