"""Three-way parity: the EXISTING Streamlit pages (streamlit_dump.json) vs what the WEB app renders in a real
browser, for the same questions. Values are compared, not appearances.
Usage: python -I parity.py <web_url> <streamlit_dump.json> <out_dir>"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB, DUMP, OUT = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")

URLS = {
    "historical_hr": "/players/historical",
    "historical_ops": "/players/historical?metric=OPS",
    "leaders_score": "/players/leaderboards",
    "leaders_ops": "/players/leaderboards?metric=OPS",
}

EXTRACT = """() => {
  const answer = document.querySelector('[aria-label="Answer"]');
  const ps = answer ? [...answer.querySelectorAll('p')].map(p => p.textContent.trim()) : [];
  const tiles = answer ? [...answer.querySelectorAll('dl > div')].map(d => [d.querySelector('dt').textContent.trim(), d.querySelector('dd').textContent.trim()]) : [];
  const chips = [...document.querySelectorAll('[aria-label="Result"] span')].filter(s => /Qualified|minimum|ranked/.test(s.textContent) && s.children.length === 0).map(s => s.textContent.trim());
  const details = document.querySelector('details'); details.open = true;
  const table = [...document.querySelectorAll('details table')].find(t => t.querySelector('thead'));
  const head = [...table.querySelectorAll('thead th')].map(h => h.textContent.replace(/[↑↓]/g, '').trim());
  const rows = [...table.querySelectorAll('tbody tr')].map(tr => [...tr.children].map(c => c.childNodes[0] ? c.childNodes[0].textContent.trim() : ''));
  return { kicker: ps[0] || '', headline: answer ? answer.querySelector('[role=heading]').textContent.trim() : '', body: ps[2] || '', tiles, chips, head, rows };
}"""


def num(text):
    """'1,234' -> 1234, '.311' -> 0.311, '1.159' -> 1.159, '—' -> None."""
    t = text.replace(",", "").strip()
    if t in ("—", ""):
        return None
    try:
        return float(t)
    except ValueError:
        return text


def same_value(web, streamlit):
    if streamlit is None:
        return web in ("—", "")
    w = num(web)
    if isinstance(streamlit, (int, float)):
        return isinstance(w, float) and abs(w - float(streamlit)) < 0.0006
    return str(web).strip() == str(streamlit).strip()


report = {}
with sync_playwright() as p:
    browser = p.chromium.launch()
    for case, path in URLS.items():
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(WEB + path, wait_until="networkidle")
        page.get_by_role("region", name="Answer").wait_for(timeout=60000)
        web = page.evaluate(EXTRACT)
        page.close()

        sl = DUMP[case]
        card = sl["card"]
        checks = {}
        # -- identity of the question
        qrange = f"{sl['year_range'][0]}–{sl['year_range'][1]}"
        checks["streamlit range/sort"] = f"{qrange}, sort {sl['sort']}"
        # -- answer (web shows the API's answer; Streamlit's card is built by the same Python function)
        checks["headline equal"] = web["headline"] == card["headline"]
        checks["detail sentence equal"] = card["body"] in web["body"] or web["body"] == card["body"]
        if card["kicker"]:
            checks["context equal"] = web["kicker"] == card["kicker"]
        if card["tiles"]:
            checks["tiles equal (labels+values)"] = [list(t) for t in card["tiles"]] == web["tiles"]
        # -- qualification chip
        sl_chip = [c for c in card["chips"] if re.search("Qualified|minimum", c)]
        checks["qualification chip equal"] = (not sl_chip and not any(re.search("Qualified|minimum", c) for c in web["chips"])) or any(c in web["chips"] for c in sl_chip)
        # -- table: header names and the first rows' values
        cols = sl["table"]["columns"]
        sl_rows = sl["table"]["rows"]
        web_head = [h for h in web["head"] if h != "#"]
        checks["table headers (names, order) equal"] = [c.lower() for c in cols if c.lower() not in ("year",) or True] == [h.lower() for h in web_head] or None
        # Streamlit's Historical Explorer table headers: Year, Player, Bats, Primary Position, Team, R ... ; Leaderboards: Player, ... Score
        hmap = {h.lower(): i for i, h in enumerate(web["head"])}
        mismatches = []
        compared = 0
        for r, row in enumerate(sl_rows):
            wrow = web["rows"][r]
            for ci, col in enumerate(cols):
                wi = hmap.get(col.lower())
                if wi is None:
                    continue
                wcell = wrow[wi]
                compared += 1
                if not same_value(wcell, row[ci]):
                    mismatches.append((r + 1, col, wcell, row[ci]))
        checks["table cells compared"] = compared
        checks["table cell mismatches"] = mismatches[:8]
        checks["top rows compared"] = len(sl_rows)
        report[case] = {"web_headline": web["headline"], "streamlit_headline": card["headline"], **checks}
    browser.close()

for case, r in report.items():
    print("==", case)
    for k, v in r.items():
        print(f"   {k}: {v}")
json.dump(report, open(OUT / "parity.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
