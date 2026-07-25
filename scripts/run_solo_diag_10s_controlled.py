"""Controlled 10-second Solo expiration diagnostic on production Cloud."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
DIAG_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_component_diag=1&solo_diag_timer=10"
)
OUT = Path(__file__).resolve().parent.parent / "data" / "solo_diag_10s_controlled.json"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

CLIENT_STAGES = [
    "iframe_script_loaded",
    "render_event_received",
    "token_received",
    "deadline_received",
    "countdown_started",
    "iframe_remount",
    "lifecycle_checkpoint",
    "browser_deadline_crossed",
    "setComponentValue_called",
    "component_value_sent",
]

PYTHON_STAGES = [
    "component_value_received",
    "wake_received",
    "expire_entered",
    "deadline_confirmed_expired",
    "autopick_attempted",
    "pick_committed",
    "commit_confirmed",
    "new_deadline_installed",
]


def scrape_snapshot(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const out = { hits: [], text: '' };
          function scan(root, path) {
            if (!root) return;
            const client = root.querySelector('#solo-expire-client');
            const mount = root.querySelector('#solo-component-mount-diag');
            const chain = root.querySelector('#solo-expire-chain');
            if (client || mount || chain) {
              out.hits.push({
                path,
                client: client ? {
                  last: client.getAttribute('data-last') || '',
                  chain: client.getAttribute('data-chain') || '',
                  remounts: client.getAttribute('data-remounts') || '',
                  deadline: client.getAttribute('data-deadline') || '',
                  token: client.getAttribute('data-token') || '',
                  remaining_ms: client.getAttribute('data-remaining-ms') || '',
                  checkpoint: client.getAttribute('data-checkpoint') || '',
                } : null,
                mount: mount ? {
                  mounted: mount.getAttribute('data-mounted') || '',
                  key: mount.getAttribute('data-key') || '',
                  deadline: mount.getAttribute('data-deadline') || '',
                  remaining: mount.getAttribute('data-remaining') || '',
                  diag_timer: mount.getAttribute('data-diag-timer') || '',
                  diag_remaining: mount.getAttribute('data-diag-remaining') || '',
                  diag_deadline: mount.getAttribute('data-diag-deadline') || '',
                  token: mount.getAttribute('data-token') || '',
                  mount_count: mount.getAttribute('data-mount-count') || '',
                } : null,
                chain: chain ? {
                  owner: chain.getAttribute('data-owner') || '',
                  commits: chain.getAttribute('data-commits') || '',
                  last: chain.getAttribute('data-last') || '',
                  chain: chain.getAttribute('data-chain') || '',
                } : null,
              });
            }
            if (root.body) out.text += root.body.innerText + '\\n';
            for (const f of root.querySelectorAll('iframe')) {
              try { if (f.contentDocument) scan(f.contentDocument, path + '>iframe'); } catch (e) {}
            }
          }
          scan(document, 'top');
          return out;
        }"""
    )


def client_hit(snapshot: dict[str, Any]) -> dict[str, Any]:
    for hit in snapshot.get("hits") or []:
        if hit.get("client"):
            return hit["client"]
    return {}


def mount_hit(snapshot: dict[str, Any]) -> dict[str, Any]:
    for hit in snapshot.get("hits") or []:
        if hit.get("mount"):
            return hit["mount"]
    return {}


def chain_hit(snapshot: dict[str, Any]) -> dict[str, Any]:
    for hit in snapshot.get("hits") or []:
        if hit.get("chain"):
            return hit["chain"]
    return {}


def stages_from_chain(chain: str) -> list[str]:
    return [p for p in str(chain or "").split("|") if p]


def extract_remount_events(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        client = client_hit(sample)
        chain = str(client.get("chain") or "")
        for stage in stages_from_chain(chain):
            if not stage.startswith("iframe_remount") and stage != "iframe_remount":
                continue
            for part in chain.split("|"):
                if part == "iframe_remount":
                    idx = chain.find(part)
                    extra = ""
                    m = re.search(r"iframe_remount\\|([^|]+)", chain)
                    if m:
                        extra = m.group(1)
                if part.startswith("iframe_remount") and part not in seen:
                    seen.add(part)
        for part in chain.split("|"):
            if part == "iframe_remount":
                continue
            if "rem_before_ms=" in part or (part == "iframe_remount"):
                pass
        for segment in re.findall(r"iframe_remount\\|([^|]*)", chain):
            key = segment
            if key in seen:
                continue
            seen.add(key)
            fields = dict(re.findall(r"(\\w+)=([^\\s]+)", segment))
            events.append({"raw": segment, **fields, "elapsed_s": sample.get("elapsed_s")})
    return events


def parse_remount_checkpoints(chain: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for segment in chain.split("|"):
        if segment == "iframe_remount":
            continue
        if segment.startswith("iframe_remount") or "rem_before_ms=" in segment:
            fields = {}
            for token in segment.replace("iframe_remount", "").split():
                if "=" in token:
                    k, v = token.split("=", 1)
                    fields[k.strip()] = v.strip()
            if fields:
                out.append(fields)
        if "rem_before_ms=" in segment:
            fields = dict(re.findall(r"(\\w+)=([^\\s]+)", segment))
            if fields:
                out.append(fields)
    return out


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake, scrape_deploy_sha_from_page
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import (
        click_btn,
        dom_counts,
        scrape_deploy_build,
        scrape_state,
        set_number,
    )

    report: dict[str, Any] = {
        "url": DIAG_URL,
        "expected_timer_seconds": 10,
        "observation_seconds": 36,
        "started_at": time.time(),
        "samples": [],
        "remount_events": [],
        "chain": {},
        "decision": "",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        goto_and_wake(page, DIAG_URL, timeout_s=240)
        report["deploy_sha"] = scrape_deploy_sha_from_page(page) or scrape_deploy_build(page)
        if "End/Delete Draft" in page.inner_text("body"):
            click_btn(page, "End/Delete Draft", wait_ms=5000)
        set_number(page, "Number of Teams", "2")
        set_number(page, "Picks per Team", "8")
        page.wait_for_timeout(1500)
        state_before = scrape_state(page)
        click_btn(page, "Start New Live Draft", wait_ms=2000)
        active = False
        t0 = time.time()
        while time.time() - t0 < 120:
            if int(dom_counts(page).get("Pause Draft") or 0) >= 1:
                active = True
                break
            page.wait_for_timeout(1000)
        report["draft_active"] = active

        poll_t0 = time.time()
        initial_remaining_ms: int | None = None
        initial_pick = state_before.get("pick")
        prev_client: dict[str, Any] = {}
        remount_log: list[dict[str, Any]] = []
        was_active_room = bool(active)
        returned_to_setup = False

        def _in_setup_lobby(text: str) -> bool:
            active = "Pause Draft" in text or "Solo live draft started" in text
            return (
                not active
                and "Start New Live Draft" in text
                and ("Draft Setup" in text or "Draft Mode" in text)
            )

        while time.time() - poll_t0 < 36:
            snap = scrape_snapshot(page)
            snap["elapsed_s"] = round(time.time() - poll_t0, 1)
            snap["state"] = scrape_state(page)
            body_text = str(snap.get("text") or "")
            if int(dom_counts(page).get("Pause Draft") or 0) >= 1 or "Solo live draft started" in body_text:
                was_active_room = True
            if was_active_room and _in_setup_lobby(body_text):
                returned_to_setup = True
            snap["setup_lobby"] = _in_setup_lobby(body_text)
            snap["was_active_room"] = was_active_room
            report["samples"].append(snap)
            client = client_hit(snap)
            if client:
                rem_ms = int(client.get("remaining_ms") or 0) if str(client.get("remaining_ms") or "").isdigit() else None
                if initial_remaining_ms is None:
                    m = re.search(r"initial_rem_ms=(\d+)", str(client.get("chain") or "") + str(client.get("checkpoint") or ""))
                    if m:
                        initial_remaining_ms = int(m.group(1))
                    elif rem_ms is not None:
                        initial_remaining_ms = rem_ms
                remounts = int(client.get("remounts") or 0)
                prev_remounts = int(prev_client.get("remounts") or 0)
                if remounts > prev_remounts and prev_client:
                    remount_log.append(
                        {
                            "elapsed_s": snap["elapsed_s"],
                            "remount_n": remounts,
                            "rem_before_ms": prev_client.get("remaining_ms"),
                            "rem_after_ms": client.get("remaining_ms"),
                            "deadline_before": prev_client.get("deadline"),
                            "deadline_after": client.get("deadline"),
                            "token_before": prev_client.get("token"),
                            "token_after": client.get("token"),
                            "checkpoint": client.get("checkpoint"),
                        }
                    )
                if "iframe_remount" in str(client.get("chain") or ""):
                    cp = str(client.get("checkpoint") or "")
                    if "rem_before_ms=" in cp:
                        fields = dict(re.findall(r"(\w+)=([^\s]+)", cp))
                        remount_log.append({"elapsed_s": snap["elapsed_s"], **fields, "source": "iframe_remount_checkpoint"})
                prev_client = dict(client)
            page.mouse.move(300, 300)
            page.wait_for_timeout(2000)

        report["state_final"] = scrape_state(page)
        browser.close()

    all_client_chains: list[str] = []
    all_server_chains: list[str] = []
    best_client: dict[str, Any] = {}
    best_chain: dict[str, Any] = {}
    best_mount: dict[str, Any] = {}
    first_zero_at: float | None = None

    for sample in report["samples"]:
        client = client_hit(sample)
        chain = chain_hit(sample)
        mount = mount_hit(sample)
        if mount.get("diag_timer"):
            best_mount = mount
        ch = str(client.get("chain") or "")
        if ch and ch not in all_client_chains:
            all_client_chains.append(ch)
        if client and len(ch) >= len(str(best_client.get("chain") or "")):
            best_client = client
        sch = str(chain.get("chain") or "")
        if sch and sch not in all_server_chains:
            all_server_chains.append(sch)
        if chain and len(sch) >= len(str(best_chain.get("chain") or "")):
            best_chain = chain
        if "browser_deadline_crossed" in ch and first_zero_at is None:
            first_zero_at = float(sample.get("elapsed_s") or 0)

    client = best_client
    mount = best_mount
    chain = best_chain
    client_chain = str(client.get("chain") or "")
    server_chain = str(chain.get("chain") or "")
    client_stages = set(stages_from_chain(client_chain))
    server_stages = set(stages_from_chain(server_chain))

    for sample in report["samples"]:
        client = client_hit(sample)
        cp = str(client.get("checkpoint") or "")
        if "rem_before_ms=" in cp and client.get("last") == "iframe_remount":
            fields = dict(re.findall(r"(\w+)=([^\s]+)", cp))
            if fields and fields not in remount_log:
                remount_log.append({"elapsed_s": sample.get("elapsed_s"), **fields, "source": "checkpoint"})

    report["initial_remaining_ms"] = initial_remaining_ms
    report["initial_remaining_s"] = round(initial_remaining_ms / 1000.0, 2) if initial_remaining_ms else None
    report["diag_timer_seconds"] = mount.get("diag_timer")
    report["diag_remaining_at_probe"] = mount.get("diag_remaining")
    report["remount_log"] = remount_log
    report["remount_count_final"] = int(client.get("remounts") or 0)
    report["token_final"] = client.get("token")
    report["deadline_final"] = client.get("deadline")

    pick_before = initial_pick
    pick_after = (report.get("state_final") or {}).get("pick")
    board_before = state_before.get("boardRows")
    board_after = (report.get("state_final") or {}).get("boardRows")
    pick_delta = None
    if pick_before is not None and pick_after is not None:
        pick_delta = int(pick_after) - int(pick_before)
    board_delta = int(board_after or 0) - int(board_before or 0)

    report["chain"] = {
        "client_stages_seen": sorted(client_stages),
        "server_stages_seen": sorted(server_stages),
        "client_chain_final": client_chain,
        "server_chain_final": server_chain,
        "client_last": client.get("last"),
        "server_last": chain.get("last"),
        "server_commits": chain.get("commits"),
    }

    report["pick_before"] = pick_before
    report["pick_after"] = pick_after
    report["pick_delta"] = pick_delta
    report["board_delta"] = board_delta
    report["duplicate_callback_count"] = client_chain.count("component_value_sent") - min(1, client_chain.count("component_value_sent"))
    report["duplicate_pick"] = pick_delta is not None and pick_delta > 1

    missing_client = [s for s in CLIENT_STAGES if s not in client_stages and s != "iframe_remount"]
    missing_python = [s for s in PYTHON_STAGES if s not in server_stages]

    report["missing_client_stages"] = missing_client
    report["missing_python_stages"] = missing_python
    report["browser_deadline_crossed"] = "browser_deadline_crossed" in client_stages
    report["component_value_sent"] = "component_value_sent" in client_stages
    report["python_on_change"] = "component_value_received" in server_stages or "wake_received" in server_stages
    report["expiration_processed"] = bool(
        {"pick_committed", "commit_confirmed", "autopick_attempted"} & server_stages
    )
    report["exactly_one_pick"] = pick_delta == 1 or board_delta == 1
    report["next_deadline_created"] = "new_deadline_installed" in server_stages or (
        pick_delta == 1 and int(client.get("remaining_ms") or 0) > 5000
    )

    ten_second_confirmed = (
        str(mount.get("diag_timer") or "") == "10"
        or any(
            str(mount_hit(s).get("diag_timer") or "") == "10"
            for s in report["samples"]
        )
    )
    report["ten_second_deadline_confirmed"] = ten_second_confirmed
    report["first_browser_deadline_crossed_at_s"] = first_zero_at
    report["server_diag_timer"] = mount.get("diag_timer")
    report["server_diag_remaining"] = mount.get("diag_remaining")
    report["server_diag_deadline"] = mount.get("diag_deadline")
    report["was_active_room"] = any(s.get("was_active_room") for s in report["samples"])
    report["returned_to_setup_during_observation"] = any(
        s.get("setup_lobby") and s.get("was_active_room") for s in report["samples"]
    )

    if not report.get("draft_active"):
        report["decision"] = "INVALID_draft_never_reached_active_room"
    elif report.get("returned_to_setup_during_observation"):
        report["decision"] = "INVALID_returned_to_setup_lobby_during_observation"
    elif not ten_second_confirmed:
        report["decision"] = "invalid_test_setup_timer_not_10s"
    elif report["browser_deadline_crossed"] and report["component_value_sent"] and report["exactly_one_pick"]:
        report["decision"] = "PASS_controlled_10s_expiration_one_pick"
    elif report["browser_deadline_crossed"] and report["component_value_sent"] and not report["python_on_change"]:
        report["decision"] = "FAIL_client_zero_crossed_python_callback_missing"
    elif report["browser_deadline_crossed"] and report["component_value_sent"] and report["python_on_change"] and not report["exactly_one_pick"]:
        report["decision"] = "FAIL_python_received_but_pick_not_committed"
    elif ten_second_confirmed and not report["browser_deadline_crossed"] and report["remount_count_final"] > 1:
        report["decision"] = "FAIL_remounts_observed_deadline_passed_without_zero_crossing"
    elif ten_second_confirmed and not report["browser_deadline_crossed"]:
        report["decision"] = "INCONCLUSIVE_no_zero_crossing_within_36s"
    else:
        report["decision"] = "FAIL_partial_chain"

    report["duration_s"] = round(time.time() - float(report["started_at"]), 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "deploy_sha",
                    "ten_second_deadline_confirmed",
                    "initial_remaining_s",
                    "diag_timer_seconds",
                    "browser_deadline_crossed",
                    "component_value_sent",
                    "python_on_change",
                    "exactly_one_pick",
                    "remount_count_final",
                    "first_browser_deadline_crossed_at_s",
                    "server_diag_timer",
                    "decision",
                    "missing_client_stages",
                    "missing_python_stages",
                )
            },
            indent=2,
        )
    )
    print("saved", OUT)
    invalid = report["decision"].startswith("INVALID") or report["decision"].startswith("invalid_")
    return 0 if report["decision"].startswith("PASS") else (2 if invalid else 1)


if __name__ == "__main__":
    raise SystemExit(main())
