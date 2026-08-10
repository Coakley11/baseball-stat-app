"""Runtime.handle_backmsg ingress (process-global, diagnostic-only)."""

from __future__ import annotations

import threading
from typing import Any


def install_runtime_backmsg_probe(st: Any | None, session: dict[str, Any]) -> None:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    try:
        from streamlit.runtime.runtime import Runtime
    except ImportError:
        return

    from live_draft_stage1_s3_process_global_diag import append_module_event, mark_global_wrapper

    if getattr(Runtime.handle_backmsg, "_solo_runtime_backmsg_wrapped", False):
        return
    orig = Runtime.handle_backmsg

    def wrapped_handle_backmsg(self: Any, session_id: str, msg: Any) -> Any:
        from live_draft_stage1_s3_process_global_diag import scan_widget_states_proto

        sid = str(session_id or "")[:64]
        fields: dict[str, Any] = {
            "runtime_session_id": sid,
            "thread_id": threading.get_ident(),
        }
        try:
            msg_type = msg.WhichOneof("type")
            fields["backmsg_type"] = str(msg_type or "")
            fields["rerun_script"] = msg_type == "rerun_script"
            if msg_type == "rerun_script":
                cs = msg.rerun_script
                fields["wire_rerun_target_fragment_id"] = str(getattr(cs, "fragment_id", "") or "")
                if cs.HasField("widget_states"):
                    scan = scan_widget_states_proto(cs.widget_states)
                    fields.update(
                        {
                            "incoming_widget_count": scan.get("incoming_widget_count"),
                            "activated_triggers": scan.get("activated_triggers"),
                            "pause_sibling_present": scan.get("pause_sibling_present"),
                            "pause_sibling_proto": scan.get("pause_sibling_proto"),
                            "pause_present": scan.get("pause_present"),
                            "pause_proto": scan.get("pause_proto"),
                        }
                    )
        except Exception:
            pass
        if sid:
            append_module_event(sid, "RUNTIME_BACKMSG_ENTRY", **fields)
        return orig(self, session_id, msg)

    wrapped_handle_backmsg._solo_runtime_backmsg_wrapped = True  # type: ignore[attr-defined]
    Runtime.handle_backmsg = wrapped_handle_backmsg  # type: ignore[method-assign]
    mark_global_wrapper("runtime_handle_backmsg")
