"""R7: the shared player search (draft_player_names.search_draft_pool_names, used by the API's
/players/search and the app's Draft Room) returns exactly what it returned before the speed-up, on
the real ~24,000 player labels, and a new query is fast once names are normalized."""

import difflib
import os
import re
import statistics
import time
import unittest

os.environ.setdefault("BASEBALL_API_PRELOAD", "0")

import draft_player_names as dpn  # noqa: E402
from baseball_api import services as svc  # noqa: E402


def _reference_search(query, names, *, limit=20):
    """search_draft_pool_names as of a9a80f7 (before the R7 speed-up), verbatim in behavior."""
    import unicodedata

    def norm(name):
        text = unicodedata.normalize("NFKD", str(name or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def word_prefix(word, q):
        if word.startswith(q):
            return True
        if len(q) >= 3 and len(word) >= len(q):
            return difflib.SequenceMatcher(None, q, word[: len(q)]).ratio() >= 0.75
        return False

    q = norm(query)
    if len(q) < 2:
        return []
    starts, contains = [], []
    for name in names:
        key = norm(name)
        if key.startswith(q) or any(word_prefix(w, q) for w in key.split()):
            starts.append(name)
        elif q in key:
            contains.append(name)
    return (starts + [n for n in contains if n not in starts])[:limit]


SEARCH_QUERIES = [
    "judge", "jugde", "ohtani", "ohtnai", "aaron", "aa", "ac", "mc", "mcg", "rodriguez", "rodriquez", "gonzalez", "peña",
    "pena", "jr", "o'neil", "de la", "ken griffey", "griffey jr", "babe", "ruth", "williams", "wiliams", "smith", "smtih",
    "josé", "mays", "cabrerra", "a judge", "alex rod", "xz", "qqqq", "acuña", "acuna", "vladimir", "guerero", "lindor",
    "Ichiro", "St. Louis", "zz top", "a", "  ", "jeter derek", "derek jeter", "ott", "mel ott", "ted willaims",
]


class SearchTests(unittest.TestCase):  # R7
    @classmethod
    def setUpClass(cls):
        cls.labels = list(svc.STORE.get().label_tuple)

    def test_results_equal_the_previous_matching(self):
        for q in SEARCH_QUERIES:
            for limit in (11, 500):
                with self.subTest(q=q, limit=limit):
                    self.assertEqual(dpn.search_draft_pool_names(q, self.labels, limit=limit),
                                     _reference_search(q, self.labels, limit=limit))

    def test_fuzzy_matches_still_found(self):
        self.assertIn("Aaron Judge", dpn.search_draft_pool_names("jugde", self.labels, limit=50))
        self.assertIn("Shohei Ohtani", dpn.search_draft_pool_names("ohtnai", self.labels, limit=50))

    def test_new_query_is_fast_when_warm(self):
        dpn.search_draft_pool_names("warmup", self.labels)
        times = []
        for q in ("rodriguez", "smith", "jugde", "wiliams", "cabrerra", "qqqq", "de la", "alex rod"):
            t0 = time.perf_counter()
            dpn.search_draft_pool_names(q, self.labels, limit=11)
            times.append(time.perf_counter() - t0)
        # target 300 ms; the bound is loose because the test machine is shared
        self.assertLess(statistics.median(times), 0.6, [round(t * 1000) for t in times])


if __name__ == "__main__":
    unittest.main()
