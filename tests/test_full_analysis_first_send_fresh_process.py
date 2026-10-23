"""The first Full Analysis in a fresh process reaches the local Command Center store (no activity recorded yet)."""

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
STORE = textwrap.dedent("""
    import json
    from pathlib import Path
    LOG = Path(__file__).parent / "writes.jsonl"
    def _w(kind, *a, **k):
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "args": [str(x) for x in a]}) + chr(10))
    def upsert_resume_item(*a, **k): _w("resume", *a)
    def upsert_saved_item(*a, **k): _w("saved", *a); return {"write_mode": "upsert"}
    def record_activity(*a, **k): _w("activity", *a)
    def __getattr__(name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None
""")
CODE = textwrap.dedent("""
    import json, sys
    sys.path.insert(0, ".")
    from suite_analytical_question import submit_analytical_question
    r = submit_analytical_question(source_app="baseball", source_page="Career Totals",
                                   question="Who has the most career HR since 2010?",
                                   context={"page": "Career Totals"}, session_state={})
    print(json.dumps({"save_failed": r["save_failed"]}))
""")


class FirstSendInFreshProcessTests(unittest.TestCase):
    def _run(self, store: Path | None) -> dict:
        env = {k: v for k, v in os.environ.items() if k != "SUITE_COMMAND_CENTER_ROOT"}
        env["SUITE_STORAGE_ISOLATED"] = "1"
        if store is not None:
            env["SUITE_COMMAND_CENTER_ROOT"] = str(store)
        out = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_first_send_saves_to_the_explicit_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            (store / "suite_storage.py").write_text(STORE, encoding="utf-8")
            res = self._run(store)
            kinds = [json.loads(l)["kind"] for l in (store / "writes.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertFalse(res["save_failed"])
        self.assertEqual(kinds.count("resume"), 1)
        self.assertEqual(kinds.index("resume"), 0, "the Continue card is the first write")

    def test_isolated_run_without_a_store_still_fails_closed(self) -> None:
        if (ROOT / "suite_storage.py").exists():
            self.skipTest("this checkout has its own suite_storage.py")
        self.assertTrue(self._run(None)["save_failed"])


if __name__ == "__main__":
    unittest.main()
