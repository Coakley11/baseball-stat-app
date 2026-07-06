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


def backend_health_ok(base_url: str) -> tuple[bool, str]:
    """True when Streamlit Python process is serving /_stcore/health (not just CDN shell)."""
    url = base_url.rstrip("/") + "/_stcore/health"
    try:
        status, body = fetch_body(url, max_bytes=500)
        snippet = body.strip()[:80]
        ok = status == 200 and snippet.lower() == "ok"
        return ok, snippet
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


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

    ok, snippet = backend_health_ok(BASEBALL_URL)
    print(f"backend_stcore_health_ok={ok} body={snippet!r}")
    try:
        status, body = fetch_body(BASEBALL_URL.rstrip("/") + "/healthz", max_bytes=200)
        print(f"platform_healthz status={status} body={body.strip()[:80]!r}")
    except Exception as exc:
        print(f"platform_healthz error={type(exc).__name__}:{exc}")

    if not ok:
        print("ACTION: Streamlit Cloud Manage app -> Reboot app (backend not serving _stcore/health).")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
