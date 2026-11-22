"""Read-only check that the Upgrade page's price label matches the configured Stripe price.

    STRIPE_READ_KEY=<sk_/rk_ key with read access> \
        python scripts/qa/verify_pro_price.py <price_id> "<label shown in the app>"

GET /v1/prices/<id> only: it never creates, changes or charges anything. Prints the price's
amount, currency, billing period, mode (test/live) and product, then MATCH or MISMATCH against the
label (amount and period must both appear in it, e.g. "$14.99/month"). The key is read from the
environment and never printed. Exit code 0 = match, 1 = mismatch, 2 = could not check.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

_SYMBOLS = {"usd": "$", "cad": "$", "aud": "$", "eur": "€", "gbp": "£"}


def describe(price: dict) -> dict:
    rec = price.get("recurring") or {}
    product = price.get("product")
    return {
        "id": price.get("id"),
        "mode": "live" if price.get("livemode") else "test",
        "active": price.get("active"),
        "currency": str(price.get("currency") or "").lower(),
        "unit_amount": price.get("unit_amount"),
        "interval": rec.get("interval"),
        "interval_count": rec.get("interval_count") or 1,
        "product": product.get("name") if isinstance(product, dict) else product,
    }


def label_matches(info: dict, label: str) -> bool:
    """The label must state the same amount and the same billing period as Stripe."""
    if info.get("unit_amount") is None or not info.get("interval"):
        return False
    amount = f"{info['unit_amount'] / 100:.2f}"
    text = str(label or "").lower().replace(",", "")
    if amount not in text:
        return False
    symbol = _SYMBOLS.get(info["currency"], "")
    if symbol and symbol not in text:
        return False
    period = info["interval"]
    if int(info.get("interval_count") or 1) != 1:
        return False  # "every 3 months" style labels need a human check
    return bool(re.search(rf"\b(/\s*)?(per\s+)?{period}(ly)?\b", text)) or (period == "month" and "/mo" in text)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    price_id, label = argv[1].strip(), argv[2]
    key = os.environ.get("STRIPE_READ_KEY", "").strip()
    if not key.startswith(("sk_test_", "rk_test_", "sk_live_", "rk_live_")):
        print("Set STRIPE_READ_KEY to a Stripe secret or restricted key (read access is enough).")
        return 2
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/prices/{price_id}?expand[]=product",
        headers={"Authorization": "Basic " + base64.b64encode((key + ":").encode()).decode()},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            info = describe(json.loads(r.read()))
    except urllib.error.HTTPError as exc:
        print(f"Stripe refused the read: HTTP {exc.code}")
        return 2
    print(json.dumps(info, indent=2))
    ok = label_matches(info, label)
    print(("MATCH" if ok else "MISMATCH") + f": label {label!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
