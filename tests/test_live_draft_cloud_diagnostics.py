"""Cloud diagnostics query-param normalization."""

from __future__ import annotations

from live_draft_cloud_diagnostics import (
    _qp_flag,
    _qp_get,
    bootstrap_cloud_accept_mode,
    control_center_mount_summary,
    get_acceptance_snapshot,
    note_control_center_mount,
    note_expiration_commit,
    note_manual_panel_mount,
)


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


def test_control_center_mount_summary():
    session: dict = {}
    note_control_center_mount(session, source="render_live_draft_control_center")
    summary = control_center_mount_summary(session)
    assert "render_live_draft_control_center" in summary
    assert "mounts=1" in summary


def test_qp_get_falls_back_to_context_url_when_query_params_omit_flag():
    class _Ctx:
        url = (
            "https://app/?active_page=Live+Draft+Room&solo_component_diag=1"
            "&solo_stage1_parent_boundary=1&suite_sid=sid-1"
        )

    st = _St({})
    st.context = _Ctx()
    from live_draft_cloud_diagnostics import _qp_flag, _qp_from_context_url, _qp_get

    assert _qp_from_context_url(st, "solo_stage1_parent_boundary") == "1"
    assert _qp_get(st, "solo_stage1_parent_boundary") == "1"
    assert _qp_flag(st, "solo_stage1_parent_boundary") is True
    assert _qp_flag(st, "solo_component_diag") is True


def test_qp_get_prefers_query_params_over_context_url():
    class _Ctx:
        url = "https://app/?solo_stage1_parent_boundary=1"

    st = _St({"solo_stage1_parent_boundary": "0"})
    st.context = _Ctx()
    from live_draft_cloud_diagnostics import _qp_get

    assert _qp_get(st, "solo_stage1_parent_boundary") == "0"


def test_acceptance_snapshot_tracks_mounts_and_expirations():
    session: dict = {}
    note_control_center_mount(session, source="render_live_draft_control_center")
    note_manual_panel_mount(session, source="render_live_manual_draft_panel")
    note_expiration_commit(session, source="solo_heartbeat")
    snap = get_acceptance_snapshot(session)
    assert snap["control_center_mounts"] == 1
    assert snap["manual_panel_mounts"] == 1
    assert snap["expiration_commits"] == 1
