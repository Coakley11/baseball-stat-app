"""Offline regression checks; every provider request is intercepted."""
from pathlib import Path
import runpy

import pytest
import requests

PROBE = Path(__file__).resolve().parents[1] / 'baseball_stripe_scope_probe.py'
FAKE_KEY = 'sk_test_fixture_only_not_a_real_credential'


@pytest.fixture
def probe_env(monkeypatch):
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME', 'baseball-billing-staging.onrender.com')
    monkeypatch.setenv('BASEBALL_BILLING_ROLLOUT', 'test')
    monkeypatch.setenv('BASEBALL_STRIPE_MODE', 'test')
    monkeypatch.setenv('STRIPE_SECRET_KEY', FAKE_KEY)
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected network access')
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)


def transport(monkeypatch, *, status=200, payload=None, error=None):
    calls = []
    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append((url, kwargs, self.trust_env))
            if error: raise error
            class Response:
                status_code = status
                def json(self): return payload
            return Response()
    monkeypatch.setattr(requests, 'Session', Session)
    return calls


@pytest.mark.parametrize('name,value', [
    ('RENDER_EXTERNAL_HOSTNAME', ''),
    ('RENDER_EXTERNAL_HOSTNAME', 'baseball-stat-app.onrender.com'),
    ('RENDER_EXTERNAL_HOSTNAME', 'music-billing-staging.onrender.com'),
    ('BASEBALL_BILLING_ROLLOUT', 'off'),
    ('BASEBALL_BILLING_ROLLOUT', 'preview'),
    ('BASEBALL_STRIPE_MODE', 'live'),
    ('STRIPE_SECRET_KEY', ''),
    ('STRIPE_SECRET_KEY', 'sk_live_fixture'),
    ('STRIPE_SECRET_KEY', 'rk_test_fixture'),
    ('STRIPE_SECRET_KEY', 'sk_test_'),
])
def test_unsafe_startup_has_no_requests(probe_env, monkeypatch, name, value, capsys):
    monkeypatch.setenv(name, value)
    calls = transport(monkeypatch)
    with pytest.raises(RuntimeError, match='guard rejected startup'):
        runpy.run_path(str(PROBE))
    assert calls == []
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('account,comparison', [
    ('acct_1Ub8HEGSM5yahQur', 'SAME_AS_MUSIC'),
    ('acct_BaseballFixture', 'DIFFERENT_FROM_MUSIC'),
])
def test_single_pinned_get_and_existing_app(probe_env, monkeypatch, capsys, account, comparison):
    from baseball_billing_service import app
    routes = [(r.path, r.methods) for r in app.routes]
    calls = transport(monkeypatch, payload={'id': account, 'email': 'must_not_be_logged'})
    result = runpy.run_path(str(PROBE))
    assert result['app'] is app
    assert [(r.path, r.methods) for r in app.routes] == routes
    assert calls == [('https://api.stripe.com/v1/account', {
        'auth': (FAKE_KEY, ''), 'timeout': 10, 'allow_redirects': False}, False)]
    assert capsys.readouterr().out == (
        f'STRIPE_SCOPE_CHECK account_id={account} comparison={comparison}\n')


@pytest.mark.parametrize('status,payload,error,expected', [
    (302, {'id': 'acct_other'}, None, 'http_status=302'),
    (401, {'message': FAKE_KEY}, None, 'http_status=401'),
    (200, {'id': 'acct_bad\nsecret'}, None, 'invalid_account_id'),
    (200, {'id': None}, None, 'invalid_account_id'),
    (200, [], None, 'details_suppressed'),
    (200, None, requests.ConnectionError(FAKE_KEY), 'details_suppressed'),
])
def test_failures_are_sanitized_and_app_survives(probe_env, monkeypatch, capsys,
                                               status, payload, error, expected):
    calls = transport(monkeypatch, status=status, payload=payload, error=error)
    result = runpy.run_path(str(PROBE))
    assert result['app'] is not None
    assert len(calls) == 1
    assert capsys.readouterr().out == f'STRIPE_SCOPE_CHECK failed {expected}\n'
