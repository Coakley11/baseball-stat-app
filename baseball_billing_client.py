"""Narrow Streamlit client for the trusted billing service."""
from __future__ import annotations
import requests
from baseball_billing_config import RolloutMode, load_client_billing_config
from baseball_monetization import authenticated_subject

_HEALTH_TIMEOUT = 60
_POST_TIMEOUT = 45

def _warm_billing_service(base_url):
    try:
        response = requests.get(base_url.rstrip("/") + "/billing/health", timeout=_HEALTH_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("Billing service did not wake within 60 seconds. No request was sent.") from exc
    except requests.RequestException as exc:
        raise RuntimeError("Billing service could not be reached. No request was sent.") from exc
    if not response.ok:
        raise RuntimeError("Billing service is not ready. No request was sent.")

def _post_once(base_url, path, token, payload):
    _warm_billing_service(base_url)
    try:
        return requests.post(
            base_url.rstrip("/") + path,
            headers={"Authorization": "Bearer " + token},
            json=payload,
            timeout=_POST_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise RuntimeError("Billing request timed out after 45 seconds. It was not retried.") from exc
    except requests.RequestException as exc:
        raise RuntimeError("Billing request failed. It was not retried.") from exc

def billing_ui_state(session,environ=None):
    c=load_client_billing_config(environ); _,authenticated,_=authenticated_subject(session)
    if c.rollout is RolloutMode.OFF: return {"action":"disabled","message":"Purchasing is not enabled yet."}
    if c.rollout is RolloutMode.PREVIEW: return {"action":"disabled","message":"Billing preview only — Checkout remains disabled."}
    if not authenticated: return {"action":"signin","message":"Sign in with your Baseball account before purchasing Pro."}
    if not c.client_checkout_enabled: return {"action":"disabled","message":"Checkout is not ready. No charge can be created."}
    return {"action":"checkout","message":"Stripe test Checkout is available." if c.test_mode else "Checkout is available."}

def create_checkout_url(session,environ=None):
    c=load_client_billing_config(environ); state=billing_ui_state(session,environ)
    if state["action"]!="checkout": raise RuntimeError(state["message"])
    _,_,token=authenticated_subject(session)
    r=_post_once(c.billing_service_url,"/billing/checkout",token,{"intent":"pro"})
    if r.status_code==409: raise RuntimeError("This account already has a subscription. Use Manage Subscription to update your payment method or plan.")
    if not r.ok: raise RuntimeError("Checkout could not be created")
    url=str((r.json() or {}).get("url") or "")
    if not url.startswith("https://checkout.stripe.com/"): raise RuntimeError("Billing service returned an invalid Checkout URL")
    return url

def create_portal_url(session,environ=None):
    c=load_client_billing_config(environ); _,authenticated,token=authenticated_subject(session)
    if not authenticated or not c.billing_service_url: raise RuntimeError("Billing portal is unavailable")
    r=_post_once(c.billing_service_url,"/billing/portal",token,{})
    if not r.ok: raise RuntimeError("Billing portal could not be opened")
    url=str((r.json() or {}).get("url") or "")
    if not url.startswith("https://billing.stripe.com/"): raise RuntimeError("Billing service returned an invalid portal URL")
    return url
