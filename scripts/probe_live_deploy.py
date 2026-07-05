"""Quick probe: GitHub dev HEAD vs live Streamlit deploy marker."""
from __future__ import annotations

import re
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, build_opener, HTTPSHandler

ROOT = Path(__file__).resolve().parents[1]
BASEBALL_URL = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
EXPECTED = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0].split()[0]


def github_dev_short() -> str:
    out = subprocess.check_output(
        ["git", "rev-parse", "--short", "origin/dev"],
        cwd=ROOT,
        text=True,
    )
    return out.strip()


def fetch_body(url: str, max_bytes: int = 20000) -> tuple[int, str]:
    ctx = ssl.create_default_context()
    opener = build_opener(HTTPSHandler(context=ctx))
    req = Request(url, headers={"User-Agent": "baseball-deploy-probe/1.0"})
    resp = opener.open(req, timeout=25)
    body = resp.read(max_bytes).decode("utf-8", "replace")
    return int(resp.status), body


def main() -> int:
    print(f"expected_deploy_commit={EXPECTED}")
    try:
        remote = github_dev_short()
        print(f"github_origin_dev={remote}")
    except Exception as exc:
        print(f"github_origin_dev_error={type(exc).__name__}:{exc}")
        remote = ""

    for suffix in ("/_stcore/health", "/?embed=true", ""):
        url = BASEBALL_URL.rstrip("/") + suffix
        try:
            status, body = fetch_body(url)
            commits = sorted(set(re.findall(r"\b[0-9a-f]{7}\b", body)))
            hit = EXPECTED in body or EXPECTED in commits
            print(f"probe url={url} status={status} len={len(body)} expected_found={hit}")
            if commits:
                print(f"  sha_candidates={commits[:12]}")
        except Exception as exc:
            print(f"probe url={url} error={type(exc).__name__}:{exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
