"""Parent-page registry for Solo countdown iframe instances (RV binding ladder)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

RV_INSTANCE_REGISTRY_KEY = "_solo_rv_instance_registry_log"


def render_rv_instance_registry_listener(st: Any, session: dict[str, Any]) -> None:
    """Install parent message listener with unique event IDs and current-iframe matching."""
    if not session.get("_solo_rv_ladder_step") and not session.get("_solo_rv_instance_registry_force"):
        return
    run_id = str(session.get("_solo_rv_run_id") or session.get("_solo_p6_run_id") or "")[:80]
    st.components.v1.html(
        f"""
<script>
(function() {{
  const RUN_ID = {json.dumps(run_id)};
  const LS = "__solo_rv_instance_registry_v1";
  if (!window[LS]) {{
    window[LS] = {{
      run_id: RUN_ID,
      current_production_instance_id: "",
      current_widget_key: "solo_countdown_wake_solo_persistent",
      instances: {{}},
      raw_events: [],
      logical_sends: [],
      seq: 0,
    }};
    window.addEventListener("message", function(ev) {{
      const reg = window[LS];
      if (!reg) return;
      const d = ev.data;
      if (!d || typeof d !== "object") return;
      reg.seq += 1;
      const eventId = "pev_" + reg.seq + "_" + Date.now();
      let iframeIdx = -1;
      let instanceFromDom = "";
      let connected = false;
      const iframes = document.querySelectorAll("iframe");
      for (let i = 0; i < iframes.length; i++) {{
        try {{
          if (iframes[i].contentWindow === ev.source) {{
            iframeIdx = i;
            connected = true;
            const doc = iframes[i].contentDocument;
            const solo = doc && doc.getElementById("solo-expire-client");
            if (solo) instanceFromDom = String(solo.getAttribute("data-iframe-instance") || "");
            break;
          }}
        }} catch (e) {{}}
      }}
      if (d.type === "solo:rvCountdownRegister") {{
        const iid = String(d.instance_id || "");
        reg.instances[iid] = {{
          instance_id: iid,
          registered_at: Date.now(),
          widget_key: String(d.widget_key || ""),
          expected_token: String(d.expected_token || ""),
          run_id: String(d.run_id || RUN_ID),
          draft_id: String(d.draft_id || ""),
          pick_index: String(d.pick_index || ""),
          iframe_dom_index: iframeIdx,
          connected: connected,
        }};
        reg.current_production_instance_id = iid;
        reg.raw_events.push({{ event_id: eventId, kind: "register", instance_id: iid, iframe_idx: iframeIdx }});
        return;
      }}
      if (d.type !== "streamlit:setComponentValue") return;
      const token = String((d.value !== undefined ? d.value : "") || "").slice(0, 400);
      const sendEventId = String(d.browser_send_event_id || d.send_event_id || "");
      const instanceId = String(d.iframe_instance || instanceFromDom || "");
      const isCurrent = instanceId && instanceId === reg.current_production_instance_id;
      const row = {{
        event_id: eventId,
        browser_send_event_id: sendEventId,
        ts: Date.now(),
        token: token,
        instance_id: instanceId,
        iframe_dom_index: iframeIdx,
        source_connected: connected,
        is_current_registered_instance: isCurrent,
        counts_as_logical_delivery: isCurrent && connected && !!token,
        widget_key: String(d.widget_key || ""),
      }};
      reg.raw_events.push(row);
      if (row.counts_as_logical_delivery) {{
        reg.logical_sends.push(row);
      }}
      try {{
        localStorage.setItem(LS, JSON.stringify({{
          run_id: reg.run_id,
          current: reg.current_production_instance_id,
          raw_count: reg.raw_events.length,
          logical_count: reg.logical_sends.length,
          last: reg.raw_events.slice(-40),
          logical: reg.logical_sends.slice(-20),
          instances: reg.instances,
        }}));
      }} catch (e) {{}}
    }});
  }}
}})();
</script>
""",
        height=0,
        width=0,
    )


def note_rv_registry_from_session(session: dict[str, Any], payload: dict[str, Any]) -> None:
    log = list(session.get(RV_INSTANCE_REGISTRY_KEY) or [])
    log.append({"ts": time.time(), **payload})
    session[RV_INSTANCE_REGISTRY_KEY] = log[-200:]


def render_rv_instance_registry_probe(st: Any, session: dict[str, Any]) -> None:
    if not session.get("_solo_rv_ladder_step") and not session.get("_solo_rv_instance_registry_force"):
        return
    snapshot = {
        "python_side": list(session.get(RV_INSTANCE_REGISTRY_KEY) or [])[-40:],
        "step": str(session.get("_solo_rv_ladder_step") or ""),
        "run_id": str(session.get("_solo_rv_run_id") or ""),
    }
    payload = json.dumps(snapshot, default=str)[:12000]
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    st.markdown(
        f'<div id="solo-rv-instance-registry" data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )
