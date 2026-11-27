"""Temporary, GET-only Stripe scope probe for the Baseball staging process."""
import os
import re

import requests

from baseball_billing_config import BillingConfig

EXPECTED_HOST = "baseball-billing-staging.onrender.com"
MUSIC_ACCOUNT = "acct_1Ub8HEGSM5yahQur"


def report_account_scope(config):
    """Emit only a nonsecret scope identifier; never log provider payloads/errors."""
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                "https://api.stripe.com/v1/account",
                auth=(config.stripe_secret_key, ""),
                timeout=10,
                allow_redirects=False,
            )
        if response.status_code != 200:
            print("STRIPE_SCOPE_CHECK failed "
                  f"http_status={response.status_code}", flush=True)
            return
        account_id = response.json().get("id")
        if (not isinstance(account_id, str)
                or not re.fullmatch(r"acct_[A-Za-z0-9]+", account_id)):
            print("STRIPE_SCOPE_CHECK failed invalid_account_id", flush=True)
            return
        comparison = ("SAME_AS_MUSIC" if account_id == MUSIC_ACCOUNT
                      else "DIFFERENT_FROM_MUSIC")
        print(f"STRIPE_SCOPE_CHECK account_id={account_id} "
              f"comparison={comparison}", flush=True)
    except Exception:
        print("STRIPE_SCOPE_CHECK failed details_suppressed", flush=True)


config = BillingConfig.from_environ()
if (os.environ.get("RENDER_EXTERNAL_HOSTNAME") != EXPECTED_HOST
        or not config.test_mode
        or not config.stripe_secret_key.startswith("sk_test_")
        or len(config.stripe_secret_key) <= len("sk_test_")):
    raise RuntimeError("Staging account diagnostic guard rejected startup")

# Existing application is exported unchanged; no new HTTP route is introduced.
from baseball_billing_service import app  # noqa: E402

if app is None:
    raise RuntimeError("Existing billing application is unavailable")
report_account_scope(config)
