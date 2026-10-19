"""WEB-M2 mobile question bar acceptance. Usage: python -I mobilebar.py <base_url> <out_dir>"""
import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
res: dict = {"checks": {}, "answerTop": {}}


def check(name, fn):
    try:
        fn()
        res["checks"][name] = "PASS"
    except Exception as exc:  # noqa: BLE001
        res["checks"][name] = f"FAIL: {str(exc).splitlines()[0][:300]}"


PAGES = {
    "historical": ("/players/historical", "2010–2025 · Home runs · All players"),
    "historical_player": ("/players/historical?player=judgeaa01&metric=OPS", "2010–2025 · OPS · Aaron Judge"),
    "leaderboards": ("/players/leaderboards", "2020–2025 · Weighted score"),
}

with sync_playwright() as p:
    browser = p.chromium.launch()

    for w in (360, 390, 430, 1280):
        for name, (path, summary) in PAGES.items():
            def run(w=w, name=name, path=path, summary=summary):
                page = browser.new_page(viewport={"width": w, "height": 844 if w < 600 else 900})
                page.goto(BASE + path, wait_until="networkidle")
                answer = page.get_by_role("region", name="Answer")
                expect(answer).to_be_visible()
                box = answer.bounding_box()
                vh = page.viewport_size["height"]
                res["answerTop"][f"{name}@{w}"] = {
                    "top": round(box["y"]), "headlineInFirstScreen": box["y"] + 90 < vh,
                    "overflow": page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"),
                }
                if w < 640:
                    expect(page.get_by_text(summary)).to_be_visible()
                    expect(page.get_by_label("Rank by")).to_be_hidden()
                    toggle = page.get_by_role("button", name="Change", exact=True)
                    expect(toggle).to_have_attribute("aria-expanded", "false")
                    page.screenshot(path=str(OUT / f"{name}_{w}_collapsed.png"), full_page=False)
                    toggle.click()
                    expect(page.get_by_label("Rank by")).to_be_visible()
                    expect(page.get_by_label("From season")).to_be_visible()
                    done = page.get_by_role("button", name="Done", exact=True)
                    expect(done).to_have_attribute("aria-expanded", "true")
                    page.screenshot(path=str(OUT / f"{name}_{w}_open.png"), full_page=False)
                    done.click()
                    expect(page.get_by_label("Rank by")).to_be_hidden()
                else:
                    expect(page.get_by_role("button", name="Change", exact=True)).to_be_hidden()
                    expect(page.get_by_text(summary)).to_be_hidden()
                    expect(page.get_by_label("Rank by")).to_be_visible()
                    expect(page.get_by_label("From season")).to_be_visible()
                    page.screenshot(path=str(OUT / f"{name}_{w}.png"), full_page=False)
                page.close()
            check(f"{name}@{w}: collapsed on phones / unchanged on desktop", run)

    def keyboard_change():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(BASE + "/players/leaderboards", wait_until="networkidle")
        expect(page.get_by_role("region", name="Answer")).to_be_visible()
        toggle = page.get_by_role("button", name="Change", exact=True)
        toggle.focus()
        assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none", "no focus ring"
        page.keyboard.press("Enter")
        expect(page.get_by_label("Rank by")).to_be_visible()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.getAttribute('aria-label') || document.activeElement.labels?.[0]?.textContent") is not None
        page.get_by_label("Rank by").select_option("HR")
        page.wait_for_url("**metric=HR")
        expect(page.get_by_role("heading", name="Aaron Judge leads 2020–2025 in home runs: 258")).to_be_visible()
        expect(page.get_by_text("2020–2025 · Home runs")).to_be_visible()
        expect(page.get_by_label("Rank by")).to_be_visible()  # stays open while the user is changing things
        page.close()
    check("keyboard: Change opens controls, change applies, summary updates", keyboard_change)

    def year_change_phone():
        page = browser.new_page(viewport={"width": 360, "height": 800})
        page.goto(BASE + "/players/historical", wait_until="networkidle")
        page.get_by_role("button", name="Change", exact=True).click()
        page.get_by_label("From season").fill("2020")
        page.get_by_label("From season").press("Enter")
        page.wait_for_url("**from=2020**")
        expect(page.get_by_text("2020–2025 · Home runs · All players")).to_be_visible()
        expect(page.get_by_role("heading", name="Aaron Judge, 2022: 62 home runs")).to_be_visible()
        page.close()
    check("phone 360: change seasons through the bar", year_change_phone)

    for name, path, heading in (
        ("needs_player", "/players/historical?scope=player", "Choose a player"),
        ("bad_metric_hist", "/players/historical?metric=WAR", "Pick a stat to rank"),
        ("bad_range_lb", "/players/leaderboards?from=2030", "Check the seasons"),
    ):
        def forced(path=path, heading=heading, name=name):
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(BASE + path, wait_until="networkidle")
            expect(page.get_by_role("heading", name=heading)).to_be_visible()
            expect(page.get_by_role("button", name="Change", exact=True)).to_have_count(0)
            expect(page.get_by_label("Rank by")).to_be_visible()
            page.screenshot(path=str(OUT / f"forced_{name}_390.png"), full_page=False)
            page.close()
        check(f"forced open at 390: {name}", forced)

    browser.close()

print(json.dumps(res, indent=1, ensure_ascii=False))
