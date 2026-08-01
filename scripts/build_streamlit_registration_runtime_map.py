"""Write Streamlit registration runtime map artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from live_draft_streamlit_registration_hooks import (
    discover_registration_runtime_map,
    write_registration_runtime_map_files,
)


def main() -> int:
    mapping = discover_registration_runtime_map()
    json_path, txt_path = write_registration_runtime_map_files(mapping, root=ROOT)
    print(json_path)
    print(txt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
