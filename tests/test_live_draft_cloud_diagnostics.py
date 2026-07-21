"""Cloud diagnostics query-param normalization."""

from __future__ import annotations

from live_draft_cloud_diagnostics import _qp_flag, _qp_get, bootstrap_cloud_accept_mode


class _QP:
    def __init__(self, data):
        self._data = data

    def get(self, name):
        return self._data.get(name)


class _St:
    def __init__(self, data):
        self.query_params = _QP(data)


def test_qp_get_normalizes_list_values():
    st = _St({"ld_accept": ["1"], "ld_canary": ["1"]})
    assert _qp_get(st, "ld_accept") == "1"
    assert _qp_flag(st, "ld_accept") is True
    assert _qp_flag(st, "ld_canary") is True


def test_bootstrap_cloud_accept_mode_from_paired_canary_params():
    st = _St({"ld_accept": ["1"], "ld_canary": ["1"]})
    session: dict = {}
    assert bootstrap_cloud_accept_mode(st, session) is True
    assert session.get("_live_draft_cloud_accept_mode") is True
    assert session.get("_live_draft_cloud_canary_mode") is True
