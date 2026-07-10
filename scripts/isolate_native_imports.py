#!/usr/bin/env python3
"""Isolate native-extension imports to localize segfaults on the deploy Python version.

Usage (local or Streamlit Cloud shell):
  PYTHONFAULTHANDLER=1 python scripts/isolate_native_imports.py
"""

from __future__ import annotations

import faulthandler
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NATIVE_MODULES: tuple[str, ...] = (
    "streamlit",
    "numpy",
    "pandas",
    "pyarrow",
    "scipy",
    "sklearn",
    "matplotlib",
)


def _import_one(name: str) -> tuple[bool, str]:
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    version = getattr(module, "__version__", "n/a")
    return True, str(version)


def _verify_entrypoint() -> tuple[bool, str]:
    source = ROOT / "streamlit_app.py"
    if not source.is_file():
        return False, "streamlit_app.py not found"
    try:
        code = source.read_text(encoding="utf-8")
        compile(code, str(source), "exec")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, "compiled"


def main() -> int:
    faulthandler.enable()
    print(f"Python: {sys.version}")
    print(f"Executable: {sys.executable}")
    print(f"PYTHONFAULTHANDLER={os.environ.get('PYTHONFAULTHANDLER', '')}")
    print(f"CWD: {os.getcwd()}")
    print("--- native import isolation ---")

    failures = 0
    for name in NATIVE_MODULES:
        print(f"import {name} ...", flush=True)
        ok, detail = _import_one(name)
        if ok:
            print(f"  OK  {name} {detail}")
        else:
            print(f"  FAIL {name} {detail}")
            failures += 1

    print("verify streamlit_app.py (compile-only; full startup in smoke_streamlit_startup.py) ...", flush=True)
    ok, detail = _verify_entrypoint()
    if ok:
        print(f"  OK  streamlit_app {detail}")
    else:
        print(f"  FAIL streamlit_app {detail}")
        failures += 1

    if failures:
        print(f"FAILED: {failures} import(s)")
        return 1
    print("ALL PASS — native imports and entrypoint loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
