import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
A = "http://127.0.0.1:8601/api/v1/"


def g(path):
    try:
        with urllib.request.urlopen(A + path) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


print("== 1. CAREER DEFAULT (player_id, no start/end)")
d = g("seasons?metric=OPS&player_id=cabremi01&include_below_minimum=true&limit=30")
print("range:", d["start"], d["end"], "| rows", len(d["rows"]), "| ranked", d["ranked_rows"], "| first/last year", min(r["year"] for r in d["rows"]), max(r["year"] for r in d["rows"]))
d = g("seasons?start=2015&metric=OPS&player_id=cabremi01&include_below_minimum=true&limit=30")
print("only start=2015:", d["start"], d["end"], "| rows", len(d["rows"]))
d = g("seasons?end=2008&metric=OPS&player_id=cabremi01&include_below_minimum=true&limit=30")
print("only end=2008:", d["start"], d["end"], "| rows", len(d["rows"]))
d = g("seasons?start=2015&end=2020&metric=OPS&player_id=cabremi01&include_below_minimum=true&limit=30")
print("explicit 2015-2020:", d["start"], d["end"], "| rows", len(d["rows"]))
d = g("seasons?metric=OPS&limit=1")
print("all players default:", d["start"], d["end"])

print("\n== 2. MANUAL MINIMUMS")
base = "seasons?start=2010&end=2025&metric=HR&order=desc&limit=3"
for extra in ("", "&min_ab=500", "&min_ab=0", "&qualified=false", "&min_HR=50", "&min_ab=300&min_HR=40"):
    d = g(base + extra)
    q = d["qualification"]
    print(f"{extra or '(none)':26} total={d['total_rows']:>6} applies={q['applies']} mode={q['mode']} min_ab={q['min_ab']} summary={q['summary']!r}")
base = "seasons?start=2010&end=2025&metric=OPS&order=desc&limit=3"
for extra in ("", "&min_ab=300", "&min_ab=0", "&min_ab=300&min_HR=30"):
    d = g(base + extra)
    q = d["qualification"]
    print(f"OPS {extra or '(none)':23} total={d['total_rows']:>6} applies={q['applies']} mode={q['mode']} min_ab={q['min_ab']} summary={q['summary']!r}")
    if extra == "&min_ab=300":
        print("   explanation:", q["explanation"])
print("min_AB rejected:", g(base + "&min_AB=300").get("error", {}).get("code"))
print("min_FOO rejected:", g(base + "&min_FOO=3").get("error", {}).get("code"))
lb = "leaderboards?start=2020&end=2025&metric=OPS&limit=3"
for extra in ("", "&min_ab=1000", "&min_ab=0", "&min_ab=1000&min_HR=100"):
    d = g(lb + extra)
    q = d["qualification"]
    print(f"LB {extra or '(none)':26} total={d['total_rows']:>5} applies={q['applies']} mode={q['mode']} min_ab={q['min_ab']} summary={q['summary']!r}")
lb = "leaderboards?start=2020&end=2025&metric=HR&limit=3"
d = g(lb + "&min_ab=1000")
q = d["qualification"]
print(f"LB HR min_ab=1000 total={d['total_rows']} applies={q['applies']} mode={q['mode']} summary={q['summary']!r}")
print("catalog minimum_columns:", g("catalog")["historical"]["filters"]["minimum_columns"])

print("\n== 3. MULTI-FRANCHISE")
cat = g("catalog")["historical"]["filters"]["teams"]
print("team options:", len(cat), [t["value"] for t in cat][:6])
base = "seasons?start=2010&end=2025&metric=HR&order=desc&limit=1"
res = {}
for label, extra in (("none", ""), ("Boston Red Sox", "&teams=Boston+Red+Sox"), ("New York Yankees", "&teams=New+York+Yankees"), ("both", "&teams=Boston+Red+Sox,New+York+Yankees"), ("both (encoded)", "&teams=Boston+Red+Sox%2CNew+York+Yankees"), ("AL", "&teams=American+League"), ("AL + Cubs", "&teams=American+League,Chicago+Cubs"), ("NL", "&teams=National+League")):
    d = g(base + extra)
    res[label] = d["total_rows"]
    print(f"{label:18} total={d['total_rows']}")
print("both == sum of the two:", res["both"] == res["Boston Red Sox"] + res["New York Yankees"])
print("AL+Cubs > AL:", res["AL + Cubs"] > res["AL"])
