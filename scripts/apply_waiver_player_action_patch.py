"""Apply minimal Player Action waiver patches to streamlit_app.py from HEAD."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    text = subprocess.check_output(["git", "show", "HEAD:streamlit_app.py"], cwd=ROOT).decode("utf-8")

    old1 = (
        '        "waiver_enabled": False,\n'
        '        "is_unrostered": False,\n'
        '        "block_message": msg or "Trade actions require an active shared league with multiple claimed owners.",\n'
        '        "trade_away_help": msg or "",\n'
        '        "acquire_help": msg or "",\n'
        '        "waiver_message": "",\n'
    )
    new1 = (
        '        "waiver_enabled": False,\n'
        '        "plan_add_enabled": False,\n'
        '        "plan_drop_enabled": False,\n'
        '        "is_unrostered": False,\n'
        '        "block_message": msg or "Trade actions require an active shared league with multiple claimed owners.",\n'
        '        "trade_away_help": msg or "",\n'
        '        "acquire_help": msg or "",\n'
        '        "plan_add_help": msg or "",\n'
        '        "plan_drop_help": msg or "",\n'
        '        "waiver_message": "",\n'
    )
    if old1 not in text:
        raise SystemExit("eligibility block missing")
    text = text.replace(old1, new1, 1)

    waiver_fn = (
        "\n\ndef _start_player_waiver_action(session, *, player_name: str, mode: str) -> str:\n"
        '    fn = getattr(player_trade_bridge, "start_player_waiver_action", None)\n'
        "    if callable(fn):\n"
        "        return fn(session, player_name=player_name, mode=mode)\n"
        "    return (\n"
        '        "Waiver action unavailable: player_trade_bridge is missing start_player_waiver_action. "\n'
        '        f"{player_trade_bridge.trade_import_error_message()}".strip()\n'
        "    )\n\n"
    )
    needle = "import projection_calibration as proj_cal"
    if needle not in text:
        raise SystemExit("projection_calibration import missing")
    text = text.replace(needle, waiver_fn + needle, 1)

    plan_clicks = (
        "\n\ndef _on_player_plan_add_click(*, player_raw: str):\n"
        '    display = fullname_base_from_label(str(player_raw or "").strip()) or str(player_raw or "").strip()\n'
        "    if not is_active_current_player(display):\n"
        "        st.session_state[wf_sb.SESSION_SIDEBAR_FLASH] = (\n"
        '            f"{display} is historical/inactive and cannot be added to a current waiver workflow."\n'
        "        )\n"
        "        st.rerun()\n"
        "        return\n"
        "    msg = _start_player_waiver_action(\n"
        "        st.session_state,\n"
        "        player_name=display,\n"
        '        mode="plan_add",\n'
        "    )\n"
        "    st.session_state[wf_sb.SESSION_SIDEBAR_FLASH] = msg\n"
        "    try:\n"
        "        from baseball_persistent_state import force_save_baseball_state\n\n"
        '        force_save_baseball_state(st, reason="player_action_plan_add_handoff")\n'
        "    except Exception:\n"
        "        pass\n"
        "    st.rerun()\n\n\n"
        "def _on_player_plan_drop_click(*, player_raw: str):\n"
        '    display = fullname_base_from_label(str(player_raw or "").strip()) or str(player_raw or "").strip()\n'
        "    if not is_active_current_player(display):\n"
        "        st.session_state[wf_sb.SESSION_SIDEBAR_FLASH] = (\n"
        '            f"{display} is historical/inactive and cannot be added to a current waiver workflow."\n'
        "        )\n"
        "        st.rerun()\n"
        "        return\n"
        "    msg = _start_player_waiver_action(\n"
        "        st.session_state,\n"
        "        player_name=display,\n"
        '        mode="plan_drop",\n'
        "    )\n"
        "    st.session_state[wf_sb.SESSION_SIDEBAR_FLASH] = msg\n"
        "    try:\n"
        "        from baseball_persistent_state import force_save_baseball_state\n\n"
        '        force_save_baseball_state(st, reason="player_action_plan_drop_handoff")\n'
        "    except Exception:\n"
        "        pass\n"
        "    st.rerun()\n\n"
    )
    nav_needle = "def _schedule_player_action_page_nav(target_page: str) -> None:"
    if nav_needle not in text:
        raise SystemExit("schedule nav missing")
    text = text.replace(nav_needle, plan_clicks + nav_needle, 1)

    old_trade = (
        '        if trade_eligibility.get("waiver_enabled"):\n'
        "            trade_actions.append(\n"
        "                (\n"
        '                    page_option_label("Waiver Wire / Add-Drop Center"),\n'
        "                    True,\n"
        '                    str(trade_eligibility.get("waiver_message") or trade_eligibility.get("block_message") or ""),\n'
        '                    "waiver",\n'
        "                )\n"
        "            )\n\n"
    )
    new_trade = (
        "        trade_actions.append(\n"
        "            (\n"
        '                "Plan Add",\n'
        '                bool(trade_eligibility.get("plan_add_enabled")),\n'
        '                str(trade_eligibility.get("plan_add_help") or trade_eligibility.get("waiver_message") or ""),\n'
        '                "plan_add",\n'
        "            )\n"
        "        )\n"
        "        trade_actions.append(\n"
        "            (\n"
        '                "Plan Drop",\n'
        '                bool(trade_eligibility.get("plan_drop_enabled")),\n'
        '                str(trade_eligibility.get("plan_drop_help") or ""),\n'
        '                "plan_drop",\n'
        "            )\n"
        "        )\n\n"
    )
    if old_trade not in text:
        raise SystemExit("waiver trade action block missing")
    text = text.replace(old_trade, new_trade, 1)

    old_btn = (
        '                if slug == "waiver":\n'
        "                    st.button(\n"
        "                        label,\n"
        '                        key=f"plr_act_{act_suffix}_{slug}_button",\n'
        "                        use_container_width=True,\n"
        "                        disabled=not enabled,\n"
        "                        on_click=_on_player_action_click,\n"
        '                        kwargs={**kwargs_base, "action": "Open Waiver Wire"},\n'
        "                    )\n"
        '                elif slug == "trade_away":\n'
    )
    new_btn = (
        '                if slug == "plan_add":\n'
        "                    st.button(\n"
        "                        label,\n"
        '                        key=f"plr_act_{act_suffix}_{slug}_button",\n'
        "                        use_container_width=True,\n"
        "                        disabled=not enabled,\n"
        "                        on_click=_on_player_plan_add_click,\n"
        '                        kwargs={"player_raw": player_raw},\n'
        "                    )\n"
        '                elif slug == "plan_drop":\n'
        "                    st.button(\n"
        "                        label,\n"
        '                        key=f"plr_act_{act_suffix}_{slug}_button",\n'
        "                        use_container_width=True,\n"
        "                        disabled=not enabled,\n"
        "                        on_click=_on_player_plan_drop_click,\n"
        '                        kwargs={"player_raw": player_raw},\n'
        "                    )\n"
        '                elif slug == "trade_away":\n'
    )
    if old_btn not in text:
        raise SystemExit("waiver button block missing")
    text = text.replace(old_btn, new_btn, 1)

    compile(text, "streamlit_app.py", "exec")
    (ROOT / "streamlit_app.py").write_text(text, encoding="utf-8", newline="\n")
    print("patched streamlit_app.py ok")


if __name__ == "__main__":
    main()
