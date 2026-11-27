"""Offline checks for startup-only account lookup through the unchanged ASGI target."""
import subprocess

import pytest
import requests

import baseball_stripe_scope_probe as probe

FAKE_KEY = 'sk_test_fixture_only_not_a_real_credential'
DEPLOYED = 'f' * 40


@pytest.fixture
def probe_env(monkeypatch):
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME', probe.EXPECTED_HOST)
    monkeypatch.setenv('RENDER_GIT_COMMIT', DEPLOYED)
    monkeypatch.setenv('BASEBALL_BILLING_ROLLOUT', 'test')
    monkeypatch.setenv('BASEBALL_STRIPE_MODE', 'test')
    monkeypatch.setenv('STRIPE_SECRET_KEY', FAKE_KEY)
    monkeypatch.setattr(probe, '_attempted', False)
    monkeypatch.setattr(probe, '_deployed_revision_matches', lambda: True)
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
    probe.run_startup_probe()
    assert calls == []
    assert capsys.readouterr().out == 'STRIPE_SCOPE_CHECK skipped safety_guard\n'


@pytest.mark.parametrize('account,comparison', [
    ('acct_1Ub8HEGSM5yahQur', 'SAME_AS_MUSIC'),
    ('acct_BaseballFixture', 'DIFFERENT_FROM_MUSIC'),
])
def test_single_get_per_process(probe_env, monkeypatch, capsys, account, comparison):
    calls = transport(monkeypatch, payload={'id': account, 'email': 'must_not_be_logged'})
    probe.run_startup_probe()
    probe.run_startup_probe()
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
def test_failures_are_sanitized_without_retry(probe_env, monkeypatch, capsys,
                                            status, payload, error, expected):
    calls = transport(monkeypatch, status=status, payload=payload, error=error)
    probe.run_startup_probe()
    probe.run_startup_probe()
    assert len(calls) == 1
    assert capsys.readouterr().out == f'STRIPE_SCOPE_CHECK failed {expected}\n'


@pytest.mark.parametrize('deployed,revision,activation,valid', [
    (DEPLOYED, DEPLOYED+'\n'+probe.DIAGNOSTIC_PARENT+'\n', DEPLOYED, True),
    ('', '', '', False),
    ('bad', '', '', False),
    (DEPLOYED, 'a'*40+'\n'+probe.DIAGNOSTIC_PARENT, DEPLOYED, False),
    (DEPLOYED, DEPLOYED+'\n'+'b'*40, DEPLOYED, False),
    (DEPLOYED, DEPLOYED+'\n'+probe.DIAGNOSTIC_PARENT, 'c'*40, False),
])
def test_revision_guard(monkeypatch, deployed, revision, activation, valid):
    monkeypatch.setenv('RENDER_GIT_COMMIT', deployed)
    calls = []
    def command(args, **kwargs):
        calls.append((args, kwargs))
        return revision if args[1] == 'rev-parse' else activation
    monkeypatch.setattr(probe.subprocess, 'check_output', command)
    assert probe._deployed_revision_matches() is valid
    for args, kwargs in calls:
        assert args[0] == 'git'
        assert kwargs['timeout'] == 3
        assert kwargs['stderr'] is subprocess.DEVNULL


def test_missing_git_skips_without_network(monkeypatch, capsys):
    monkeypatch.setenv('RENDER_GIT_COMMIT', DEPLOYED)
    def missing(*args, **kwargs): raise FileNotFoundError(FAKE_KEY)
    monkeypatch.setattr(probe.subprocess, 'check_output', missing)
    assert probe._deployed_revision_matches() is False
    assert capsys.readouterr().out == ''


def test_existing_start_target_lifespan_and_routes(probe_env, monkeypatch, capsys):
    from starlette.testclient import TestClient
    from baseball_billing_service import app
    from baseball_billing_config import BillingConfig
    calls = transport(monkeypatch, payload={'id': 'acct_BaseballFixture'})
    assert [(r.path, r.methods) for r in app.routes] == [
        ('/billing/health', {'GET', 'HEAD'}),
        ('/billing/checkout', {'POST'}),
        ('/billing/portal', {'POST'}),
        ('/billing/webhooks/stripe', {'POST'}),
    ]
    with TestClient(app) as client:
        response = client.get('/billing/health')
        assert response.status_code == 200
        assert response.json() == BillingConfig.from_environ().public_status()
        assert len(calls) == 1
        client.get('/billing/health')
        assert len(calls) == 1
    with TestClient(app):
        assert len(calls) == 1
    assert 'comparison=DIFFERENT_FROM_MUSIC' in capsys.readouterr().out


def test_release_guard_skip_preserves_health(probe_env, monkeypatch, capsys):
    from starlette.testclient import TestClient
    from baseball_billing_service import app
    monkeypatch.setattr(probe, '_deployed_revision_matches', lambda: False)
    calls = transport(monkeypatch)
    with TestClient(app) as client:
        assert client.get('/billing/health').status_code == 200
    assert calls == []
    assert capsys.readouterr().out == 'STRIPE_SCOPE_CHECK skipped safety_guard\n'
