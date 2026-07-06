#!/usr/bin/env python3
"""Probe Supabase ``suite_app_current_state`` from local secrets or env."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from suite_app_current_state_health import probe_suite_app_current_state_health  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-key", default="", help="Scoped cloud app key (default: workspace baseball key)")
    parser.add_argument("--no-write", action="store_true", help="Read-only GET probe")
    parser.add_argument("--size-ladder", action="store_true", help="POST increasing payload sizes until failure")
    args = parser.parse_args()

    health = probe_suite_app_current_state_health(
        run_write_probe=not args.no_write,
        run_size_ladder=bool(args.size_ladder),
        scoped_app_key=str(args.app_key or ""),
    )
    print(json.dumps(health, indent=2, default=str))

    if not health.get("configured"):
        print("\nSupabase not configured — copy .streamlit/secrets.toml.example or set SUITE_SUPABASE_* env.", file=sys.stderr)
        return 2
    if not health.get("table_reachable"):
        print("\nFAIL: suite_app_current_state not reachable.", file=sys.stderr)
        return 1
    if args.no_write:
        print("\nOK: table reachable (read-only).", file=sys.stderr)
        return 0
    if not health.get("minimal_write_ok"):
        print("\nFAIL: minimal upsert failed — Supabase project/PostgREST likely unhealthy.", file=sys.stderr)
        if health.get("likely_cause") == "gateway_upstream_reset":
            print("Hint: restart the Supabase project (Settings → General → Restart).", file=sys.stderr)
        return 1
    if args.size_ladder and health.get("size_ladder"):
        failed = next((row for row in health["size_ladder"] if not row.get("ok")), None)
        if failed:
            print(f"\nWARN: size ladder failed at ~{failed.get('actual_bytes')} bytes.", file=sys.stderr)
            return 1
    print("\nOK: minimal upsert succeeded.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
