"""Harness regression: Streamlit launched via server manager survives parent-tree kill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from local_tb_server_manager import (  # noqa: E402
    ServerSpec,
    http_status,
    process_alive,
    start_server,
    stop_server,
)


class LocalTbServerManagerTests(unittest.TestCase):
    def test_room_store_is_absolute_shared_path(self) -> None:
        from local_tb_server_manager import room_store_path

        path = room_store_path()
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.name, "draft_rooms")
        self.assertTrue(str(path).endswith(str(Path("data") / "draft_rooms")))

    def test_reparented_server_survives_wrapper_tree_kill(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows Job/tree-kill regression")
        port = 8593
        out = ROOT / "data" / "tb_probe" / "harness_reg"
        out.mkdir(parents=True, exist_ok=True)
        wrapper = out / "tree_kill_wrapper.py"
        marker = out / "tree_kill_ready.json"
        if marker.exists():
            marker.unlink()
        wrapper.write_text(
            f"""
import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(r"{str(ROOT)}")
sys.path.insert(0, str(ROOT / "scripts"))
from local_tb_server_manager import ServerSpec, start_server, http_status
out = Path(r"{str(out)}")
handle = start_server(
    ServerSpec(name="harness", port={port}, workspace_id="diag", device_id="harness-reg"),
    out_dir=out,
    wait_ready_s=90.0,
)
(out / "tree_kill_ready.json").write_text(json.dumps(handle.to_dict()), encoding="utf-8")
(out / "tree_kill_wrapper.pid").write_text(str(os.getpid()), encoding="utf-8")
while True:
    time.sleep(30)
""",
            encoding="utf-8",
        )
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        wrap_proc = subprocess.Popen(
            [sys.executable, str(wrapper)],
            cwd=str(ROOT),
            creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        )
        handle = None
        try:
            deadline = time.time() + 120.0
            while time.time() < deadline:
                if marker.is_file():
                    handle = json.loads(marker.read_text(encoding="utf-8"))
                    break
                if wrap_proc.poll() is not None:
                    self.fail(f"wrapper exited early: {wrap_proc.returncode}")
                time.sleep(0.5)
            self.assertIsNotNone(handle, "server never became ready")
            assert handle is not None
            pid = int(handle["pid"])
            self.assertTrue(process_alive(pid))
            self.assertTrue(http_status(port).get("ok"))
            # Kill the wrapper tree the way Cursor/agent cleanup does.
            subprocess.run(
                ["taskkill", "/PID", str(wrap_proc.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
            time.sleep(3.0)
            self.assertTrue(
                process_alive(pid),
                "Streamlit died with wrapper tree — reparent/breakaway failed",
            )
            self.assertTrue(http_status(port).get("ok"), "HTTP died after wrapper kill")
        finally:
            if handle:
                stop_server(handle)
            if process_alive(wrap_proc.pid):
                subprocess.run(
                    ["taskkill", "/PID", str(wrap_proc.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                )


if __name__ == "__main__":
    unittest.main()
