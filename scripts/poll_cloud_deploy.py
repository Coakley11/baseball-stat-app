"""Poll Streamlit Cloud until deploy_commit.txt SHA is live in page HTML."""
from __future__ import annotations

import re
import sys
import time
import urllib.request

URL = (
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    "?ld_accept=1&active_page=Live%20Draft%20Room"
)
TARGET = sys.argv[1] if len(sys.argv) > 1 else "815f6a9"


def fetch_build() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": "deploy-poll"})
    html = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
    m = re.search(r"baseball-dev-([a-f0-9]{7})", html, re.I)
    return m.group(1).lower() if m else ""


def main() -> int:
    for i in range(45):
        try:
            found = fetch_build()
            print(f"poll {i + 1}: build={found or 'unknown'}", flush=True)
            if found == TARGET.lower():
                print("DEPLOY_READY", flush=True)
                return 0
        except Exception as exc:
            print(f"poll {i + 1}: error {exc}", flush=True)
        time.sleep(20)
    print("DEPLOY_TIMEOUT", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
