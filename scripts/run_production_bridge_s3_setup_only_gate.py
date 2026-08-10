"""Production SETUP-ONLY gate — stops before sibling click / R3 (localization pass)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

if __name__ == "__main__":
    os.environ["STAGE1_S3_SETUP_ONLY"] = "1"
    from run_production_bridge_s3_server_registry_gate import main

    raise SystemExit(main())
