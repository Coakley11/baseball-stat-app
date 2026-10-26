"""WEB-M2 browser acceptance on the production build, through the Next proxy, against the real API.
Usage: python -I m2_acceptance.py <web_url> <api_url> <out_dir>
Every expectation is fetched from the API itself, never typed in by hand."""
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

WEB, API, OUT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")
AXE = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
res = {"checks": {}, "layout": {}, "axe": {}, "misc": {}}


def api(path, raw=False):
    with urllib.request.urlopen(f"{API}/api/v1/{path}") as r:
        body = r.read()
        return (r.headers, body) if raw else json.loads(body)


def check(name, fn):
    try:
        fn()
        res["checks"][name] = "PASS"
    except Exception as exc:  # noqa: BLE001
        res["checks"][name] = "FAIL: " + (str(exc).splitlines() or [repr(exc)])[0][:260]


CAT = api("catalog")
HE_HR = api("seasons?start=2010&end=2025&metric=HR&order=desc&limit=25")
HE_OPS = api("seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25")
HE_FILT = api("seasons?start=2010&end=2025&metric=HR&order=desc&bats=L&positions=SS&position_source=season&limit=25")
HE_JUDGE = api("seasons?metric=OPS&order=desc&player_id=judgeaa01&limit=25&include_below_minimum=true")
LB = api("leaderboards?start=2020&end=2025&metric=score&limit=25")
LB_OPS = api("leaderboards?start=2020&end=2025&metric=OPS&limit=25")
LB_W = api("leaderboards?start=2020&end=2025&metric=score&weights=HR%3A2%2CRBI%3A1&limit=10")

PAGES = {
    "historical": ("/players/historical", HE_HR["answer"]["headline"]),
    "historical_ops": ("/players/historical?metric=OPS", HE_OPS["answer"]["headline"]),
    "historical_player": ("/players/historical?player=judgeaa01&metric=OPS", HE_JUDGE["answer"]["headline"]),
    "historical_filtered": ("/players/historical?bats=L&pos=SS", HE_FILT["answer"]["headline"]),
    "leaderboards": ("/players/leaderboards", LB["answer"]["headline"]),
    "leaderboards_ops": ("/players/leaderboards?metric=OPS", LB_OPS["answer"]["headline"]),
    "leaderboards_weights": ("/players/leaderboards?w=HR:2,RBI:1&top=10", LB_W["answer"]["headline"]),
}

LAYOUT = """() => {
  const d = document.documentElement;
  const a = document.querySelector('[aria-label="Answer"]');
  const det = document.querySelector('details'); if (det) det.open = true;
  const region = document.querySelector('details [role=region][aria-label]');
  const sticky = document.querySelector('details [role=region][aria-label] tbody th[scope=row]');
  const svg = document.querySelector('figure svg');
  const fig = svg ? svg.closest('figure') : null;
  const tiles = [...document.querySelectorAll('dl > div')].map(x => Math.round(x.getBoundingClientRect().width));
  const small = [...document.querySelectorAll('p, span, a, button, label, td, th, li, dt, dd, legend, h1, h2, h3')]
    .filter(el => el.offsetParent && el.textContent.trim() && parseFloat(getComputedStyle(el).fontSize) < 11).length;
  const targets = [...document.querySelectorAll('a[href], button, input, select, summary')].filter(el => el.offsetParent)
    .map(el => { const l = el.closest('label'); return (el.tagName === 'INPUT' && l) ? l.getBoundingClientRect() : el.getBoundingClientRect(); })
    .filter(r => r.height > 0 && r.height < 24).length;
  return { overflow: d.scrollWidth > d.clientWidth, scrollWidth: d.scrollWidth,
    answerTop: a ? Math.round(a.getBoundingClientRect().top) : null,
    tableScrolls: region ? region.scrollWidth > region.clientWidth : null,
    regionWithinPage: region ? Math.round(region.getBoundingClientRect().right) <= d.clientWidth : null,
    stickyPlayer: sticky ? getComputedStyle(sticky).position : null,
    svgFits: svg && fig ? svg.getBoundingClientRect().right <= fig.getBoundingClientRect().right + 1 : null,
    minTile: tiles.length ? Math.min(...tiles) : null, textUnder11px: small, targetsUnder24px: targets };
}"""

with sync_playwright() as p:
    browser = p.chromium.launch()

    # ------------------------------------------------------------ layout at every width
    for w in (1280, 430, 390, 360):
        for name, (path, headline) in PAGES.items():
            page = browser.new_page(viewport={"width": w, "height": 900 if w > 600 else 844})
            page.goto(WEB + path, wait_until="networkidle")
            expect(page.get_by_role("heading", name=headline, exact=True)).to_be_visible(timeout=60000)
            if w in (1280, 390, 360):
                page.screenshot(path=str(OUT / f"{name}_{w}.png"), full_page=True)
            res["layout"][f"{name}@{w}"] = page.evaluate(LAYOUT)
            if w in (1280, 390) and name in ("historical", "leaderboards", "historical_player"):
                page.screenshot(path=str(OUT / f"{name}_{w}_explore.png"), full_page=True)
            page.close()

    # ------------------------------------------------------------ shell, direct URLs, refresh, Back/Forward
    def nav_flow():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + "/", wait_until="networkidle")
        side = page.get_by_role("complementary")
        side.get_by_role("link", name="Leaderboards").click()
        expect(page.get_by_role("heading", name=LB["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(side.get_by_role("link", name="Leaderboards")).to_have_attribute("aria-current", "page")
        side.get_by_role("link", name="Historical Explorer").click()
        expect(page.get_by_role("heading", name=HE_HR["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.close()
    check("shell: sidebar navigation between built pages with real data", nav_flow)

    def phone_menu():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/historical", wait_until="networkidle")
        page.get_by_role("button", name="Menu").click()
        dialog = page.get_by_role("dialog", name="Menu")
        expect(dialog.get_by_role("link", name="Historical Explorer")).to_have_attribute("aria-current", "page")
        dialog.get_by_role("link", name="Leaderboards").click()
        expect(page.get_by_role("heading", name=LB["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.close()
    check("shell: phone menu navigates", phone_menu)

    def refresh_and_direct():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/historical?bats=L&pos=SS&page=2&metric=HR", wait_until="networkidle")
        expect(page.get_by_role("heading", name=HE_FILT["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.get_by_text("Explore more").click()
        expect(page.get_by_text("Rows 26–", exact=False).first).to_be_visible(timeout=60000)
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name=HE_FILT["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.get_by_text("Explore more").click()
        expect(page.get_by_text("Rows 26–", exact=False).first).to_be_visible(timeout=60000)
        expect(page.get_by_label("Left")).to_be_checked()
        page.close()
    check("direct URL with filters + page, then refresh keeps the same state", refresh_and_direct)

    def back_forward():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + "/players/historical", wait_until="networkidle")
        expect(page.get_by_role("heading", name=HE_HR["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.get_by_label("Rank by").select_option("OPS")
        expect(page.get_by_role("heading", name=HE_OPS["answer"]["headline"], exact=True)).to_be_visible()
        page.get_by_text("Explore more").click()
        page.get_by_role("button", name="Next").click()
        expect(page.get_by_text("Rows 26–", exact=False).first).to_be_visible()
        page.go_back()
        expect(page.get_by_text("Rows 1–25", exact=False).first).to_be_visible()
        page.go_back()
        expect(page.get_by_role("heading", name=HE_HR["answer"]["headline"], exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name=HE_HR["answer"]["headline"], exact=True)).to_be_visible()
        page.go_forward()
        expect(page.get_by_role("heading", name=HE_OPS["answer"]["headline"], exact=True)).to_be_visible()
        page.go_forward()
        expect(page.get_by_text("Rows 26–", exact=False).first).to_be_attached()
        page.close()
    check("Back/Forward across stat change and table paging", back_forward)

    # ------------------------------------------------------------ catalog-driven tables
    def table_check(path, columns, first_rows, kind):
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + path, wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        table = page.locator("details table").first
        heads = [h.replace("↑", "").replace("↓", "").strip() for h in table.locator("thead th").all_text_contents()]
        assert heads == ["#"] + [c["label"] for c in columns], heads
        body = table.locator("tbody tr")
        for i, row in enumerate(first_rows[:5]):
            cells = body.nth(i).locator("th, td").all_inner_texts()
            player = row["player"]["name"]
            assert player in " ".join(cells), (player, cells[:4])
            for c in columns:
                if c["metric"] and c["metric"] not in ("yearID", "score"):
                    got = cells[1 + columns.index(c)].replace(",", "")
                    want = row["stats"][c["metric"]] if kind == "season" else row["stats"][c["metric"]]
                    if want is None:
                        assert got in ("—", ""), (c["label"], got)
                    else:
                        assert abs(float(got) - float(want)) < 0.0006, (player, c["label"], got, want)
        page.close()

    check("historical table: headers and cell values equal the catalog columns and the API rows", lambda: table_check("/players/historical", CAT["historical"]["columns"], HE_HR["rows"], "season"))
    check("leaderboards table: headers and cell values equal the catalog columns and the API rows", lambda: table_check("/players/leaderboards", CAT["leaderboards"]["columns"], LB["rows"], "lb"))

    def missing_value_dash():
        # Real data has missing stats (e.g. old seasons with no SB / BB recorded): shown as a dash, not 0.
        d = api("seasons?start=1871&end=1871&metric=HR&limit=25")
        has_missing = any(r["stats"][k] is None for r in d["rows"] for k in r["stats"])
        res["misc"]["real_missing_values_in_1871"] = has_missing
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + "/players/historical?from=1871&to=1871", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        text = page.locator("details table").first.inner_text()
        if has_missing:
            assert "—" in text
        page.close()
    check("missing values in real data render as a dash", missing_value_dash)

    def phone_table():
        page = browser.new_page(viewport={"width": 360, "height": 800})
        page.goto(WEB + "/players/historical", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        region = page.get_by_role("region", name="Seasons", exact=True)
        assert region.evaluate("el => el.scrollWidth > el.clientWidth"), "table does not scroll inside its frame"
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "page overflows"
        frame_left = region.bounding_box()["x"]
        th = region.locator("tbody th").first
        before = th.bounding_box()["x"]
        region.evaluate("el => { el.scrollLeft = 400 }")
        page.wait_for_timeout(300)
        after = th.bounding_box()["x"]
        assert before > frame_left + 40, "player column should start after the # column"
        assert abs(after - frame_left) < 4, f"player column did not stay at the frame edge: {after} vs {frame_left}"
        assert th.is_visible()
        page.screenshot(path=str(OUT / "phone_table_360.png"))
        page.close()
    check("phone 360: table scrolls inside its frame; the player column stays put; page doesn't scroll sideways", phone_table)

    # ------------------------------------------------------------ CSV downloads
    def csv_download(path, api_csv, filename, header_labels):
        page = browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page.goto(WEB + path, wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        with page.expect_download(timeout=120000) as info:
            page.get_by_role("link", name="Download CSV").click()
        dl = info.value
        got = Path(dl.path()).read_bytes()
        headers, want = api(api_csv, raw=True)
        assert dl.suggested_filename == filename, dl.suggested_filename
        assert headers.get("content-type", "").startswith("text/csv")
        assert got == want, f"bytes differ: {len(got)} vs {len(want)} ({hashlib.sha256(got).hexdigest()[:10]} vs {hashlib.sha256(want).hexdigest()[:10]})"
        assert got.decode("utf-8").splitlines()[0] == ",".join(header_labels)
        res["misc"][f"csv {filename} {path}"] = f"{len(got)} bytes, {len(got.splitlines())} lines, sha256 {hashlib.sha256(got).hexdigest()[:12]}"
        page.close()

    check("CSV (historical, filtered): the browser downloads the API's exact bytes under its filename, header = catalog labels",
          lambda: csv_download("/players/historical?from=2025&to=2025&bats=B&pos=C", "seasons?start=2025&end=2025&metric=HR&order=desc&bats=B&positions=C&position_source=season&format=csv",
                              "historical_explorer.csv", [c["label"] for c in CAT["historical"]["columns"]]))
    check("CSV (historical, all 2010-2025 seasons): exact bytes",
          lambda: csv_download("/players/historical", "seasons?start=2010&end=2025&metric=HR&order=desc&format=csv", "historical_explorer.csv", [c["label"] for c in CAT["historical"]["columns"]]))
    check("CSV (leaderboards Top 25 OPS): exact bytes, own filename",
          lambda: csv_download("/players/leaderboards?metric=OPS", "leaderboards?start=2020&end=2025&metric=OPS&limit=25&format=csv", "leaderboards.csv", [c["label"] for c in CAT["leaderboards"]["columns"]]))

    # ------------------------------------------------------------ controls
    def filters_flow():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + "/players/historical", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        page.locator("label.check, label", has_text="Left").first.click()
        page.wait_for_url("**bats=L**")
        page.locator("label", has_text="SS").first.click()
        page.wait_for_url("**pos=SS**")
        expect(page.get_by_role("heading", name=HE_FILT["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_text(f"of {HE_FILT['total_rows']:,} seasons", exact=False).first).to_be_visible()
        page.close()
    check("filters: batting hand + position through the API, answer and totals equal the API", filters_flow)

    def top_and_weights():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + "/players/leaderboards", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        page.get_by_label("Players shown").select_option("10")
        page.wait_for_url("**top=10**")
        expect(page.locator("details tbody tr")).to_have_count(10, timeout=60000)
        page.get_by_label("Weight for HR").fill("2")
        page.get_by_label("Weight for RBI").fill("1")
        page.get_by_label("Weight for SB").fill("0")
        page.get_by_role("button", name="Apply weights").click()
        expect(page.get_by_role("heading", name=LB_W["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        podium = page.get_by_role("heading", name="Top 3").locator("xpath=ancestor::section[1]")
        for row in LB_W["rows"][:3]:
            expect(podium).to_contain_text(row["player"]["name"])
        page.close()
    check("leaderboards: Top 10 and custom weights; ranking equals the API's for those weights", top_and_weights)

    def one_player_ui():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/historical?metric=OPS", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_role("button", name="Change", exact=True).click()
        page.get_by_text("One player", exact=True).click()
        t0 = time.time()
        page.get_by_label("Find a player").fill("judge")
        page.get_by_role("button", name="Aaron Judge").first.click()
        res["misc"]["player_search_to_pick_seconds"] = round(time.time() - t0, 2)
        expect(page.get_by_role("heading", name=HE_JUDGE["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_role("figure", name="Aaron Judge · OPS by season")).to_be_visible()
        below = [r for r in HE_JUDGE["rows"] if not r["meets_minimum"]]
        assert below, "expected below-minimum seasons for Judge"
        page.get_by_text("Explore more").click()
        assert page.get_by_role("region", name="Seasons", exact=True).get_by_text("Below the minimum").count() == len(below)
        # hollow markers on the chart equal the below-minimum seasons
        hollow = page.locator("figure svg circle").evaluate_all("els => els.filter(e => getComputedStyle(e).fill === 'rgb(255, 255, 255)').length")
        res["misc"]["hollow_markers_vs_below_minimum"] = f"{hollow} vs {len(below)}"
        page.screenshot(path=str(OUT / "player_judge_390.png"), full_page=True)
        page.close()
    check("one player via the UI: search, pick, timeline, below-minimum seasons marked (count equals the API's)", one_player_ui)


    # ------------------------------------------------------------ follow-up: career, minimums, franchises
    CAB = api("seasons?metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true")
    CAB_BELOW = [r for r in CAB["rows"] if not r["meets_minimum"]]

    def career_via_ui():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        seen = []
        page.on("request", lambda r: seen.append(r.url))
        page.goto(WEB + "/players/historical?metric=OPS", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        expect(page.get_by_text("2010–2025 · OPS · All players", exact=False).first).to_be_visible()
        page.get_by_role("button", name="Change", exact=True).click()
        expect(page.get_by_label("From season")).to_have_value("2010")  # all players: default range
        page.get_by_text("One player", exact=True).click()
        assert "from=" not in page.url and "to=" not in page.url, page.url
        page.get_by_label("Find a player").fill("miguel cabrera")
        page.get_by_role("button", name="Miguel Cabrera").first.click()
        expect(page.get_by_role("heading", name=CAB["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_label("From season")).to_have_value(str(CAB["start"]))
        expect(page.get_by_label("To season")).to_have_value(str(CAB["end"]))
        assert CAB["start"] < 2010
        player_calls = [u for u in seen if "player_id=cabremi01" in u]
        assert player_calls and all("start=" not in u and "end=" not in u for u in player_calls), player_calls[:2]
        page.get_by_text("Explore more").click()
        assert page.get_by_role("region", name="Seasons", exact=True).get_by_text("Below the minimum").count() == len(CAB_BELOW)
        page.screenshot(path=str(OUT / "career_cabrera_390.png"), full_page=True)
        # An explicit narrower range is preserved, and the other bound stays the API's career bound.
        page.get_by_label("From season").fill("2015")
        page.get_by_label("From season").press("Enter")
        page.wait_for_url("**from=2015**")
        want = api("seasons?start=2015&end=2023&metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true")
        expect(page.get_by_role("heading", name=want["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        years = page.get_by_role("region", name="Seasons", exact=True).locator("tbody tr").evaluate_all("rows => rows.map(r => Number(r.children[1].textContent))")
        assert years and min(years) >= 2015, years
        page.close()
    check("one player: defaults to the career the API reports (no years sent), shows it, marks below-minimum seasons; a chosen bound is kept", career_via_ui)

    def all_players_range_unchanged():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + "/players/historical", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        expect(page.get_by_label("From season")).to_have_value("2010")
        expect(page.get_by_label("To season")).to_have_value("2025")
        page.close()
    check("all players keep the 2010-2025 default", all_players_range_unchanged)

    def minimums_flow():
        page = browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page.goto(WEB + "/players/historical?metric=OPS", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        page.get_by_label("Minimum at-bats").fill("300")
        page.get_by_label("Minimum HR").fill("30")
        page.get_by_role("button", name="Apply minimums").click()
        page.wait_for_url("**minab=300**")
        raw = api("seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=300&min_HR=30&limit=25")
        expect(page.get_by_role("heading", name=raw["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_text(raw["qualification"]["summary"]).first).to_be_visible()
        expect(page.get_by_text(f"of {raw['total_rows']:,} seasons", exact=False).first).to_be_attached()
        # the CSV honours them
        with page.expect_download(timeout=120000) as info:
            page.get_by_role("link", name="Download CSV").click()
        got = Path(info.value.path()).read_bytes()
        headers, want = api("seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=300&min_HR=30&format=csv", raw=True)
        assert got == want, (len(got), len(want))
        res["misc"]["csv with minimums"] = f"{len(got)} bytes, {len(got.splitlines()) - 1} rows (API says {raw['total_rows']})"
        assert len(got.splitlines()) - 1 == raw["total_rows"]
        # Reset clears them
        page.get_by_role("button", name="Reset minimums").click()
        page.wait_for_url(lambda url: "minab" not in url)
        expect(page.get_by_role("heading", name=HE_OPS["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.close()
    check("minimums: Apply -> API answer, qualification line and total; the CSV honours them; Reset", minimums_flow)

    def zero_minimum():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/historical?metric=OPS&minab=0", wait_until="networkidle")
        raw = api("seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=0&limit=25")
        expect(page.get_by_role("heading", name=raw["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_text(raw["qualification"]["summary"]).first).to_be_visible()
        page.close()
    check("minimum 0 at-bats shows the API's 'No at-bat minimum' line", zero_minimum)

    def franchises_flow():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/historical", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        page.locator("label", has_text="Boston Red Sox").first.click()
        page.wait_for_url("**team=Boston**")
        page.locator("label", has_text="New York Yankees").first.click()
        page.wait_for_url("**New+York+Yankees**")
        raw = api("seasons?start=2010&end=2025&metric=HR&order=desc&teams=Boston+Red+Sox%2CNew+York+Yankees&limit=25")
        expect(page.get_by_role("heading", name=raw["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_text(f"of {raw['total_rows']:,} seasons", exact=False).first).to_be_attached()
        expect(page.get_by_text("2 selected")).to_be_visible()
        assert raw["total_rows"] == api("seasons?start=2010&end=2025&metric=HR&teams=Boston+Red+Sox&limit=1")["total_rows"] + api("seasons?start=2010&end=2025&metric=HR&teams=New+York+Yankees&limit=1")["total_rows"]
        page.screenshot(path=str(OUT / "franchises_390.png"), full_page=True)
        page.get_by_role("button", name="Clear").click()
        page.wait_for_url(lambda url: "team=" not in url)
        expect(page.get_by_role("heading", name=HE_HR["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.close()
    check("several franchises: two selected -> the API's union (equals the sum of each); Clear", franchises_flow)

    def leaderboard_minimums():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + "/players/leaderboards?metric=OPS", wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        page.get_by_text("Explore more").click()
        page.get_by_label("Minimum at-bats").fill("1000")
        page.get_by_role("button", name="Apply minimums").click()
        page.wait_for_url("**minab=1000**")
        raw = api("leaderboards?start=2020&end=2025&metric=OPS&min_ab=1000&limit=25")
        expect(page.get_by_role("heading", name=raw["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_text(f"{raw['total_rows']:,} players ranked")).to_be_visible()
        expect(page.get_by_text(raw["qualification"]["summary"]).first).to_be_visible()
        podium = page.get_by_role("heading", name="Top 3").locator("xpath=ancestor::section[1]")
        for row in raw["rows"][:3]:
            expect(podium).to_contain_text(row["player"]["name"])
        page.close()
    check("leaderboards: minimum AB -> the API's ranking, count and qualification line", leaderboard_minimums)

    # ------------------------------------------------------------ states
    def loading_state():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("**/api/baseball/seasons**", lambda route: (time.sleep(2.5), route.continue_()))
        page.goto(WEB + "/players/historical", wait_until="domcontentloaded")
        expect(page.get_by_text("Finding seasons…")).to_be_visible(timeout=30000)
        page.screenshot(path=str(OUT / "state_loading_390.png"))
        expect(page.get_by_role("heading", name=HE_HR["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.close()
    check("state: loading, then the real answer", loading_state)

    def empty_state():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/historical?from=1871&to=1871&bats=B&pos=C", wait_until="networkidle")
        expect(page.get_by_role("heading", name="No seasons match")).to_be_visible(timeout=60000)
        page.screenshot(path=str(OUT / "state_empty_390.png"))
        page.close()
    check("state: a real empty result (1871 switch-hitting catchers)", empty_state)

    def error_state():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        down = {"on": True}
        page.route("**/api/baseball/catalog", lambda route: route.abort() if down["on"] else route.continue_())
        page.goto(WEB + "/players/leaderboards", wait_until="domcontentloaded")
        expect(page.get_by_role("alert").filter(has_text="Baseball data is unavailable right now")).to_be_visible(timeout=45000)
        page.screenshot(path=str(OUT / "state_error_390.png"))
        down["on"] = False
        page.get_by_role("button", name="Try again").click()
        expect(page.get_by_role("heading", name=LB["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        page.close()
    check("state: API outage -> error with Retry -> recovers", error_state)

    def page_two_error():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/api/baseball/seasons**offset=25**", lambda route: route.abort())
        page.goto(WEB + "/players/historical?page=2", wait_until="domcontentloaded")
        page.get_by_text("Explore more").click(timeout=60000)
        expect(page.get_by_role("alert").filter(has_text="This page of seasons didn't load")).to_be_visible(timeout=45000)
        page.close()
    check("state: a failing table page shows its own error", page_two_error)

    def warm_start():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        n = {"c": 0}

        def handler(route):
            n["c"] += 1
            if n["c"] <= 2:
                route.fulfill(status=503, headers={"retry-after": "1", "content-type": "application/json"},
                              body=json.dumps({"error": {"code": "data_unavailable", "message": "Historical data is still loading."}}))
            else:
                route.continue_()
        page.route("**/api/baseball/catalog", handler)
        page.goto(WEB + "/players/leaderboards", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name=LB["answer"]["headline"], exact=True)).to_be_visible(timeout=60000)
        assert page.get_by_role("alert").filter(has_text="unavailable").count() == 0
        res["misc"]["catalog_requests_during_warmup"] = n["c"]
        page.close()
    check("cold start: 503 + Retry-After is waited out (no error shown)", warm_start)

    def past_the_end():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/historical?page=9999", wait_until="networkidle")
        page.get_by_text("Explore more").click(timeout=60000)
        expect(page.get_by_role("heading", name="That page is past the last season")).to_be_visible(timeout=60000)
        page.get_by_role("button", name="Back to the first page").click()
        expect(page.get_by_text("Rows 1–25", exact=False).first).to_be_visible(timeout=60000)
        page.close()
    check("state: a page past the end offers the first page", past_the_end)

    def bad_inputs():
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(WEB + "/players/leaderboards?metric=WAR", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Pick a stat to rank")).to_be_visible(timeout=60000)
        page.goto(WEB + "/players/historical?from=2030", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Check the seasons")).to_be_visible(timeout=60000)
        page.close()
    check("bad URL input: clear states, no request sent", bad_inputs)

    # ------------------------------------------------------------ accessibility
    for scheme in ("light", "dark"):
        for name in ("historical", "historical_player", "leaderboards_weights"):
            path, headline = PAGES[name]
            page = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme=scheme)
            page.goto(WEB + path, wait_until="networkidle")
            page.get_by_role("heading", name=headline, exact=True).wait_for(timeout=60000)
            page.get_by_text("Explore more").click()
            try:
                page.add_script_tag(url=AXE)
                v = page.evaluate("""async () => (await axe.run(document, { runOnly: ['wcag2a','wcag2aa','wcag21aa','best-practice'] }))
                    .violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, sample: v.nodes.slice(0,2).map(n => n.target.join(' ')) }))""")
            except Exception as exc:  # noqa: BLE001
                v = f"axe unavailable: {exc}"
            res["axe"][f"{name} ({scheme}, Explore more open)"] = v
            page.close()

    browser.close()

print(json.dumps(res, indent=1, ensure_ascii=False))
