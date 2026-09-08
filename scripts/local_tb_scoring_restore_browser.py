"""Browser acceptance: fresh normal Solo Draft recommendation cards after scoring restore."""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "data" / "tb_probe" / "scoring_restore_browser"
URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
WS = Path(__file__).resolve().parents[1] / "data" / "workspaces" / "daniel" / "baseball_user_state.json"


def scrub_workspace() -> dict:
    if not WS.is_file():
        return {"ok": False}
    raw = json.loads(WS.read_text(encoding="utf-8"))
    state = raw.get("state") if isinstance(raw.get("state"), dict) else raw
    cleared = []
    for k in list(state.keys()):
        kl = k.lower()
        if "live_draft" in kl or k in ("active_shared_draft_room_code", "draft_room_shared_meta"):
            state.pop(k, None)
            cleared.append(k)
    pfs = state.get("page_filter_state")
    if isinstance(pfs, dict):
        ldr = pfs.get("Live Draft Room")
        if isinstance(ldr, dict):
            ldr["live_draft_setup_mode"] = "solo"
            for rk in ("live_draft_room", "live_draft_state"):
                if rk in ldr:
                    ldr.pop(rk, None)
                    cleared.append(f"pfs.{rk}")
    WS.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return {"ok": True, "cleared": cleared}


def wait_ready(page) -> None:
    page.wait_for_selector("[data-testid=stSidebar]", timeout=90000)
    for _ in range(50):
        text = page.locator("body").inner_text()
        if "Choose Page" in text or "Live Draft" in text:
            return
        page.wait_for_timeout(1000)


def go_live_draft(page) -> None:
    try:
        btn = page.get_by_role("button", name=re.compile(r"Return to Live Draft", re.I))
        if btn.count() and btn.first.is_visible():
            btn.first.click(timeout=5000)
            page.wait_for_timeout(6000)
            return
    except Exception:
        pass
    page.locator("[data-testid=stSidebar] label").filter(has_text="Live Draft Room").first.click(
        timeout=12000
    )
    page.wait_for_timeout(6000)


def end_if_active(page, report: dict) -> None:
    body = page.locator("[data-testid=stMain]").inner_text()
    if "Start New Live Draft" in body and "Why Recommended" not in body:
        report["already_setup"] = True
        return
    for label in (
        r"Disregard Saved Draft and Start New",
        r"Leave Room",
        r"Return to Setup",
        r"End Draft",
    ):
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=4000)
                page.wait_for_timeout(2000)
                report.setdefault("cleanup_clicks", []).append(label)
                conf = page.locator("button").filter(has_text=re.compile(r"^(Yes|Confirm)", re.I))
                if conf.count():
                    conf.first.click(timeout=3000)
                    page.wait_for_timeout(2500)
        except Exception:
            pass
    for pat in (r"Draft controls \(Pause", r"Control Center", r"Draft controls"):
        try:
            page.get_by_text(re.compile(pat, re.I)).first.click(timeout=2000)
            page.wait_for_timeout(600)
        except Exception:
            pass
    for _ in range(6):
        end = page.locator("button").filter(has_text=re.compile(r"End/Delete Draft for Everyone", re.I))
        if not end.count():
            end = page.locator("button").filter(has_text=re.compile(r"End/Delete Draft", re.I))
        if end.count():
            try:
                end.first.scroll_into_view_if_needed(timeout=4000)
            except Exception:
                pass
            end.first.click(timeout=5000)
            page.wait_for_timeout(1200)
        for label in (
            "Confirm End/Delete",
            "Yes, end draft",
            "Yes, delete",
            "Confirm",
            "Yes",
        ):
            conf = page.locator("button").filter(has_text=label)
            if conf.count():
                conf.first.click(timeout=4000)
                page.wait_for_timeout(5000)
                report["ended"] = True
                break
        else:
            try:
                page.get_by_role("checkbox").first.check(timeout=1000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
        if "Start New Live Draft" in page.locator("[data-testid=stMain]").inner_text():
            report["ended"] = True
            return
    report["ended"] = "Start New Live Draft" in page.locator("[data-testid=stMain]").inner_text()
    if not report["ended"]:
        scrub_workspace()
        page.reload(wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(8000)
        report["reloaded_after_scrub"] = True
        report["ended"] = "Start New Live Draft" in page.locator("[data-testid=stMain]").inner_text()


def configure_and_start(page, report: dict) -> None:
    for label in ("Solo Draft", "Solo"):
        try:
            page.get_by_role("radio", name=re.compile(rf"^{re.escape(label)}$", re.I)).first.check(
                timeout=3000
            )
            report["solo"] = label
            break
        except Exception:
            try:
                page.locator("label").filter(has_text=label).first.click(timeout=3000)
                report["solo"] = label
                break
            except Exception:
                continue
    page.wait_for_timeout(800)
    for label, value in (("Number of Teams", "10"), ("Picks per Team", "15")):
        try:
            page.get_by_label(re.compile(label, re.I)).fill(value)
            page.wait_for_timeout(250)
        except Exception as exc:
            report.setdefault("fill_err", []).append(f"{label}:{exc}")
    for label, value in (
        ("C", "1"),
        ("1B", "1"),
        ("2B", "1"),
        ("3B", "1"),
        ("SS", "1"),
        ("OF", "3"),
        ("DH / UTIL", "1"),
        ("Bench Spots", "5"),
    ):
        try:
            page.get_by_label(re.compile(rf"^{re.escape(label)}$", re.I)).fill(value)
            report.setdefault("slots_set", []).append(label)
            page.wait_for_timeout(150)
        except Exception:
            pass
    page.wait_for_timeout(800)
    pre = page.locator("[data-testid=stMain]").inner_text()
    report["pre_positions"] = next(
        (ln for ln in pre.splitlines() if "Required starting positions" in ln), ""
    )
    btn = page.locator("button").filter(has_text="Start New Live Draft")
    if not btn.count():
        page.screenshot(path=str(OUT / "00_no_start.png"), full_page=True)
        report["no_start_snip"] = page.locator("[data-testid=stMain]").inner_text()[:2500]
        raise RuntimeError("Start New Live Draft missing")
    btn.first.click(timeout=8000)
    report["started_click"] = True


def wait_for_projection_recs(page, report: dict, *, seconds: int = 180) -> str:
    main = ""
    for i in range(max(1, seconds // 3)):
        page.wait_for_timeout(3000)
        try:
            ret = page.get_by_role("button", name=re.compile(r"Return to Live Draft", re.I))
            if ret.count() and ret.first.is_visible():
                ret.first.click(timeout=3000)
                page.wait_for_timeout(4000)
                report["used_return"] = True
        except Exception:
            pass
        main = page.locator("[data-testid=stMain]").inner_text()
        if "Why Recommended" in main and "Player Grade" in main and "Decision Score" in main:
            scores = [float(x) for x in re.findall(r"Decision Score:\s*([0-9.]+)", main)[:6]]
            report["wait_iters"] = i + 1
            report["decision_scores"] = scores
            # Wait for projection upgrade if still market-proxy-ish (all ~60-70).
            if scores and max(scores) >= 80:
                report["projection_grades_ready"] = True
                return main
            report["projection_grades_ready"] = False
            if "Preparing" in main or "projection" in main.lower() or "Loading" in main:
                report["saw_upgrade_spinner"] = True
    report["recs_ready"] = "Why Recommended" in main
    return main


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"url": URL, "scrub": scrub_workspace()}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 960})
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        wait_ready(page)
        try:
            page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=2000)
        except Exception:
            pass
        go_live_draft(page)
        end_if_active(page, report)
        if "Start New Live Draft" not in page.locator("[data-testid=stMain]").inner_text():
            scrub_workspace()
            page.goto(URL, wait_until="domcontentloaded", timeout=120000)
            wait_ready(page)
            go_live_draft(page)
            report["second_scrub_nav"] = True
        configure_and_start(page, report)
        main_text = wait_for_projection_recs(page, report, seconds=180)
        page.screenshot(path=str(OUT / "01_solo_recs.png"), full_page=False)
        cards = page.locator(".ld-rec-card-header")
        card_texts = []
        for i in range(min(cards.count(), 8)):
            try:
                card_texts.append(cards.nth(i).inner_text(timeout=3000)[:800])
            except Exception:
                pass
        names = re.findall(
            r"(Aaron Judge|Juan Soto|Bobby Witt|Shohei Ohtani|Francisco Lindor|Gunnar Henderson|Ben Williamson)",
            main_text,
            flags=re.I,
        )
        report["metrics"] = {
            "header": next(
                (ln for ln in main_text.splitlines() if re.search(r"Pick \d+ of \d+", ln)),
                "",
            ),
            "positions_line": next(
                (ln for ln in main_text.splitlines() if "Required starting positions" in ln),
                "",
            ),
            "card_count": cards.count(),
            "card_texts": card_texts,
            "player_grades": re.findall(r"Player Grade:\s*([0-9.]+)", main_text)[:12],
            "decision_scores": re.findall(r"Decision Score:\s*([0-9.]+)", main_text)[:12],
            "roster_fits": re.findall(r"Roster Fit(?: Score)?:\s*([0-9.]+)", main_text)[:12],
            "scarcity": re.findall(r"Positional Scarcity:\s*([0-9.]+)", main_text)[:12],
            "has_player_grade": "Player Grade" in main_text,
            "has_decision": "Decision Score" in main_text,
            "has_roster_fit": "Roster Fit" in main_text,
            "has_scarcity": "Positional Scarcity" in main_text or "Scarcity" in main_text,
            "has_why": "Why Recommended" in main_text,
            "has_draft": page.locator("button").filter(has_text="Draft Player").count() > 0,
            "has_queue": page.locator("button").filter(has_text="Add to Queue").count() > 0,
            "named_hits": names[:20],
            "ben_first": bool(card_texts and re.search(r"ben williamson", card_texts[0], re.I)),
            "judge_visible": bool(re.search(r"aaron judge", main_text, re.I)),
            "snip": main_text[:3500],
        }
        page.screenshot(path=str(OUT / "02_full.png"), full_page=True)
        browser.close()
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("metrics", "projection_grades_ready", "pre_positions", "solo", "scrub")}, indent=2))


if __name__ == "__main__":
    main()
