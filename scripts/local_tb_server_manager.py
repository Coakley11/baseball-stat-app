"""Reliable local two-client Streamlit launcher for Shared Draft browser proofs.

Windows harness shells (Cursor/agent) often kill process trees when a command ends
or is force-stopped. Streamlit children that remain descendants of that tree die
even when healthy (``HARNESS_CHILD_PROCESS_LIFETIME_DEFECT``).

This manager spawns each server through a short-lived intermediate that exits
immediately after ``Popen``, so Streamlit is reparented off the harness tree.
Logs go to files opened for the child (no parent-owned pipes).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INTERMEDIATE = Path(__file__).resolve().parent / "local_tb_streamlit_intermediate.py"
DEFAULT_OUT = ROOT / "data" / "tb_probe" / "server_manager"

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

HOST_PORT = 8511
GUEST_PORT = 8512


@dataclass
class ServerSpec:
    name: str
    port: int
    workspace_id: str
    device_id: str
    backend: str = "local"


@dataclass
class ServerHandle:
    name: str
    port: int
    pid: int
    log_path: str
    pid_path: str
    workspace_id: str
    device_id: str
    room_store: str
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def room_store_path() -> Path:
    return (ROOT / "data" / "draft_rooms").resolve()


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return str(pid) in out and "No tasks" not in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def http_status(port: int, timeout: float = 3.0) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return {"ok": True, "status": int(resp.status), "url": url}
    except urllib.error.HTTPError as exc:
        return {"ok": True, "status": int(exc.code), "url": url}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "url": url}


def wait_http(port: int, *, timeout_s: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"ok": False}
    while time.time() < deadline:
        last = http_status(port)
        if last.get("ok"):
            last["waited_s"] = round(timeout_s - (deadline - time.time()), 2)
            return last
        time.sleep(0.5)
    last["timeout_s"] = timeout_s
    return last


def _free_port(port: int) -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | "
                f"ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        pass


def start_server(
    spec: ServerSpec,
    *,
    out_dir: Path | None = None,
    wait_ready_s: float = 60.0,
    free_port_first: bool = True,
) -> ServerHandle:
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / f"{spec.name}_{spec.port}.log"
    pid_path = out / f"{spec.name}_{spec.port}.pid"
    meta_path = out / f"{spec.name}_{spec.port}.json"
    if free_port_first:
        _free_port(spec.port)
        time.sleep(0.5)
    env_pairs = [
        f"BASEBALL_SHARED_DRAFT_ROOM_BACKEND={spec.backend}",
        f"SUITE_WORKSPACE_ID={spec.workspace_id}",
        f"BASEBALL_DEVICE_ID={spec.device_id}",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    # Intermediate exits immediately after spawning Streamlit (reparent pattern).
    subprocess.check_call(
        [
            sys.executable,
            str(INTERMEDIATE),
            str(ROOT),
            str(spec.port),
            str(log_path),
            str(pid_path),
            *env_pairs,
        ],
        cwd=str(ROOT),
        creationflags=creationflags,
    )
    deadline = time.time() + 15.0
    pid = 0
    while time.time() < deadline:
        if pid_path.is_file():
            raw = pid_path.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                pid = int(raw)
                break
        time.sleep(0.1)
    if not pid:
        raise RuntimeError(f"{spec.name}: intermediate did not write pid file {pid_path}")
    ready = wait_http(spec.port, timeout_s=wait_ready_s)
    if not ready.get("ok"):
        tail = ""
        if log_path.is_file():
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(
            f"{spec.name}: HTTP not ready on {spec.port} (pid={pid}). last={ready} log_tail={tail!r}"
        )
    handle = ServerHandle(
        name=spec.name,
        port=spec.port,
        pid=pid,
        log_path=str(log_path.resolve()),
        pid_path=str(pid_path.resolve()),
        workspace_id=spec.workspace_id,
        device_id=spec.device_id,
        room_store=str(room_store_path()),
    )
    meta_path.write_text(json.dumps(handle.to_dict(), indent=2), encoding="utf-8")
    return handle


def stop_server(handle: ServerHandle | dict[str, Any], *, timeout_s: float = 10.0) -> dict[str, Any]:
    data = handle.to_dict() if isinstance(handle, ServerHandle) else dict(handle)
    pid = int(data.get("pid") or 0)
    port = int(data.get("port") or 0)
    result: dict[str, Any] = {"pid": pid, "port": port, "stopped": False}
    if not pid:
        return result
    if not process_alive(pid):
        result["stopped"] = True
        result["already_dead"] = True
        return result
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}:{exc}"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not process_alive(pid):
            result["stopped"] = True
            break
        time.sleep(0.2)
    if port:
        result["http_after_stop"] = http_status(port, timeout=1.5)
    return result


def start_host_guest(
    *,
    out_dir: Path | None = None,
    wait_ready_s: float = 60.0,
) -> dict[str, ServerHandle]:
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    host = start_server(
        ServerSpec(
            name="host",
            port=HOST_PORT,
            workspace_id="daniel",
            device_id="host-two-browser-qa",
        ),
        out_dir=out,
        wait_ready_s=wait_ready_s,
    )
    guest = start_server(
        ServerSpec(
            name="guest",
            port=GUEST_PORT,
            workspace_id="guest",
            device_id="guest-two-browser-qa",
        ),
        out_dir=out,
        wait_ready_s=wait_ready_s,
    )
    # Topology contract: same absolute room store.
    if Path(host.room_store) != Path(guest.room_store):
        stop_server(host)
        stop_server(guest)
        raise RuntimeError(f"room store mismatch: {host.room_store} vs {guest.room_store}")
    return {"host": host, "guest": guest}


def stop_all(handles: dict[str, ServerHandle | dict[str, Any]]) -> dict[str, Any]:
    return {name: stop_server(h) for name, h in handles.items()}


def status_snapshot(handles: dict[str, ServerHandle | dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, h in handles.items():
        data = h.to_dict() if isinstance(h, ServerHandle) else dict(h)
        pid = int(data.get("pid") or 0)
        port = int(data.get("port") or 0)
        out[name] = {
            **data,
            "alive": process_alive(pid),
            "http": http_status(port),
        }
    return out


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Local Shared Draft Streamlit manager")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p_stat = sub.add_parser("status")
    p_stat.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    state_path = Path(args.out) / "handles.json"
    if args.cmd == "start":
        handles = start_host_guest(out_dir=args.out)
        payload = {k: v.to_dict() for k, v in handles.items()}
        state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "handles": payload, "status": status_snapshot(handles)}, indent=2))
        return 0
    if not state_path.is_file():
        print(json.dumps({"ok": False, "error": f"missing {state_path}"}))
        return 1
    handles = json.loads(state_path.read_text(encoding="utf-8"))
    if args.cmd == "status":
        print(json.dumps(status_snapshot(handles), indent=2))
        return 0
    if args.cmd == "stop":
        print(json.dumps(stop_all(handles), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
