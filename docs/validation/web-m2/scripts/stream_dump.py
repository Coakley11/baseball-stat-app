"""Dump what the EXISTING Streamlit pages show (via AppTest) for representative cases.

Run from the exported API tree (5ca7a26), which contains the full app:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python stream_dump.py <out.json>
Writes the answer card, chips, the year range / sort the page used, the row count and the first
rows of the table the page renders. Nothing here is computed: it reads the page's own output.
"""
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

os.environ.setdefault("BASEBALL_API_PRELOAD", "0")
ROOT = Path.cwd()
WS_ID = "guest"
WS_FILE = ROOT / "data" / "workspaces" / WS_ID / "baseball_user_state.json"
OUT = Path(sys.argv[1])


def text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def answer_card(at):
    out = {"kicker": "", "headline": "", "body": "", "tiles": [], "chips": []}
    for m in at.markdown:
        v = m.value
        if 'class="u1-answer' in v:
            for part in ("kicker", "headline"):
                f = re.search(rf'class="u1-{part}">(.*?)</div>', v, re.S)
                out[part] = text(f.group(1)) if f else ""
            f = re.search(r'class="u1-body">(.*?)</p>', v, re.S)
            out["body"] = text(f.group(1)) if f else ""
        elif 'class="u1-tiles"' in v and not out["tiles"]:
            out["tiles"] = [(text(a), text(b)) for a, b in re.findall(r'class="u1-l">(.*?)</div><div class="u1-v">(.*?)</div>', v, re.S)]
        elif 'class="u1-chips"' in v:
            out["chips"] += [text(c) for c in re.findall(r'class="u1-chip[^"]*">(.*?)</span>', v, re.S)]
    return out


def run_page(page, **selects):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=900)
    at.query_params["active_page"] = page
    at.query_params["suite_workspace"] = WS_ID
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    for key, value in selects.items():
        at.selectbox(key=key).set_value(value).run()
        assert not at.exception, [e.value for e in at.exception]
    return at


def records(df, n=25):
    head = df.head(n)
    return {"columns": [str(c) for c in head.columns], "rows": [[None if v != v else (v.item() if hasattr(v, "item") else v) for v in row] for row in head.itertuples(index=False)], "total_rows": int(len(df))}


CASES = [
    ("historical_hr", "Historical Explorer", {}, "historical"),
    ("historical_ops", "Historical Explorer", {"historical_sort_stat_filter": "OPS"}, "historical"),
    ("leaders_score", "Leaderboards", {}, "leaders"),
    ("leaders_ops", "Leaderboards", {"leaders_sort_stat_filter": "OPS"}, "leaders"),
]

results = {}
backup = WS_FILE.read_bytes() if WS_FILE.is_file() else None
dir_created = not WS_FILE.parent.exists()
WS_FILE.parent.mkdir(parents=True, exist_ok=True)
try:
    for name, page, selects, kind in CASES:
        WS_FILE.write_text(json.dumps({"version": 1, "app": "baseball", "saved_at": "2026-01-01T00:00:00+00:00", "state": {}}), encoding="utf-8")
        at = run_page(page, **selects)
        ss = at.session_state
        rng = list(ss["historical_year_range_filter" if kind == "historical" else "leaders_year_range_filter"])
        results[name] = {
            "page": page,
            "year_range": rng,
            "sort": ss["historical_sort_stat_filter" if kind == "historical" else "leaders_sort_stat_filter"],
            "card": answer_card(at),
            "table": records(at.dataframe[0].value),
        }
        print("dumped", name, flush=True)
finally:
    if backup is not None:
        WS_FILE.write_bytes(backup)
    elif WS_FILE.is_file():
        WS_FILE.unlink()
    if dir_created and WS_FILE.parent.exists():
        shutil.rmtree(WS_FILE.parent, ignore_errors=True)

OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print("wrote", OUT)
