#!/usr/bin/env python3
"""Keep streamlit_app.py and Streamlit_app.py identical for Linux deploys."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOWER = ROOT / "streamlit_app.py"
UPPER = ROOT / "Streamlit_app.py"


def main() -> int:
    if not LOWER.is_file():
        print(f"missing {LOWER}", file=sys.stderr)
        return 1
    data = LOWER.read_bytes()
    UPPER.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()[:12]
    print(f"Synced {LOWER.name} -> {UPPER.name} ({len(data)} bytes, sha256={digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
