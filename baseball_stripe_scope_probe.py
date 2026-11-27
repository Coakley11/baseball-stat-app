"""Temporary, GET-only Stripe scope probe for the Baseball staging process."""
import os
import re
import subprocess
import threading
from pathlib import Path

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


# This revision must be the immediate child of the reviewed first diagnostic.
DIAGNOSTIC_PARENT = "371543c3901453872e793a8c85b3362b10897f93"
_attempted = False
_lock = threading.Lock()


def _deployed_revision_matches():
    """Fail closed if Render metadata or the checkout's Git evidence is missing."""
    deployed = os.environ.get('RENDER_GIT_COMMIT', '')
    if not re.fullmatch(r'[0-9a-f]{40}', deployed):
        return False
    root = Path(__file__).resolve().parent
    try:
        revision = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD', 'HEAD^'], cwd=root,
            stderr=subprocess.DEVNULL, timeout=3, text=True).splitlines()
        activation = subprocess.check_output(
            ['git', 'log', '-1', '--format=%H', '--',
             'baseball_billing_service.py', 'baseball_stripe_scope_probe.py'],
            cwd=root, stderr=subprocess.DEVNULL, timeout=3, text=True).strip()
        return revision == [deployed, DIAGNOSTIC_PARENT] and activation == deployed
    except Exception:
        return False


def run_startup_probe():
    """At most one diagnostic attempt per process; no import-time network calls."""
    global _attempted
    config = BillingConfig.from_environ()
    if (os.environ.get('RENDER_EXTERNAL_HOSTNAME') != EXPECTED_HOST
            or not config.test_mode
            or not config.stripe_secret_key.startswith('sk_test_')
            or len(config.stripe_secret_key) <= len('sk_test_')
            or not _deployed_revision_matches()):
        print('STRIPE_SCOPE_CHECK skipped safety_guard', flush=True)
        return
    with _lock:
        if _attempted:
            return
        _attempted = True
    report_account_scope(config)
