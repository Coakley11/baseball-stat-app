"""Compare JUnit results: which tests fail on the candidate but not on the baseline.

    python ci/compare_failures.py <suite> <candidate_dir> <baseline_dir> >> "$GITHUB_STEP_SUMMARY"

Exit 1 when the candidate has a failure the baseline does not have (a new failure).
"""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def outcomes(folder: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for xml in Path(folder).rglob("*.xml"):
        for case in ET.parse(xml).getroot().iter("testcase"):
            name = f"{case.get('classname')}::{case.get('name')}"
            if case.find("failure") is not None or case.find("error") is not None:
                result[name] = "failed"
            elif case.find("skipped") is not None:
                result[name] = "skipped"
            else:
                result[name] = "passed"
    return result


def count(d: dict[str, str], outcome: str) -> int:
    return sum(1 for v in d.values() if v == outcome)


suite, cand_dir, base_dir = sys.argv[1:4]
cand, base = outcomes(cand_dir), outcomes(base_dir)
failed = sorted(n for n, o in cand.items() if o == "failed")
new = [n for n in failed if base.get(n) != "failed"]
old = [n for n in failed if base.get(n) == "failed"]
fixed = sorted(n for n, o in base.items() if o == "failed" and cand.get(n) == "passed")
print(f"### {suite}\n")
print(f"Candidate: {count(cand, 'passed')} passed, {len(failed)} failed, {count(cand, 'skipped')} skipped. "
      f"Baseline {os.environ.get('BASELINE_SHA', '?')[:7]}: {count(base, 'passed')} passed, {count(base, 'failed')} failed.\n")
for title, names in (("New failures (fail on the candidate, not on the baseline)", new),
                     ("Pre-existing failures (also fail on the baseline)", old),
                     ("Fixed (fail on the baseline, pass on the candidate)", fixed)):
    print(f"**{title}: {len(names)}**\n")
    for n in names:
        print(f"- `{n}`")
    print()
sys.exit(1 if new else 0)
