"""Narrow Streamlit client for the trusted billing service."""
from __future__ import annotations
import requests
from baseball_billing_config import BillingConfig,RolloutMode
from baseball_monetization import authenticated_subject

def billing_ui_state(session,environ=None):
    c=BillingConfig.from_environ(environ); _,authenticated,_=authenticated_subject(session)
    if c.rollout is RolloutMode.OFF: return {"action":"disabled","message":"Purchasing is not enabled yet."}
    if c.rollout is RolloutMode.PREVIEW: return {"action":"disabled","message":"Billing preview only — Checkout remains disabled."}
    if not authenticated: return {"action":"signin","message":"Sign in with your Baseball account before purchasing Pro."}
    if not c.checkout_enabled or not c.billing_service_url: return {"action":"disabled","message":"Checkout is not ready. No charge can be created."}
    return {"action":"checkout","message":"Stripe test Checkout is available." if c.test_mode else "Checkout is available."}

def create_checkout_url(session,environ=None):
    c=BillingConfig.from_environ(environ); state=billing_ui_state(session,environ)
    if state["action"]!="checkout": raise RuntimeError(state["message"])
    _,_,token=authenticated_subject(session)
    r=requests.post(c.billing_service_url+"/billing/checkout",headers={"Authorization":"Bearer "+token},json={"intent":"pro"},timeout=15)
    if not r.ok: raise RuntimeError("Checkout could not be created")
    url=str((r.json() or {}).get("url") or "")
    if not url.startswith("https://checkout.stripe.com/"): raise RuntimeError("Billing service returned an invalid Checkout URL")
    return url

def create_portal_url(session,environ=None):
    c=BillingConfig.from_environ(environ); _,authenticated,token=authenticated_subject(session)
    if not authenticated or not c.billing_service_url: raise RuntimeError("Billing portal is unavailable")
    r=requests.post(c.billing_service_url+"/billing/portal",headers={"Authorization":"Bearer "+token},json={},timeout=15)
    if not r.ok: raise RuntimeError("Billing portal could not be opened")
    url=str((r.json() or {}).get("url") or "")
    if not url.startswith("https://billing.stripe.com/"): raise RuntimeError("Billing service returned an invalid portal URL")
    return url
