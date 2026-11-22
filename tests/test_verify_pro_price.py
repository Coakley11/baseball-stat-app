"""The read-only price check compares the app's label with Stripe's amount and period."""

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "verify_pro_price", Path(__file__).resolve().parents[1] / "scripts" / "qa" / "verify_pro_price.py")
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)


class LabelMatchTests(unittest.TestCase):
    def info(self, amount, interval="month", currency="usd", count=1):
        return vp.describe({"id": "price_x", "livemode": False, "active": True, "currency": currency,
                            "unit_amount": amount, "recurring": {"interval": interval, "interval_count": count},
                            "product": {"name": "Baseball Pro"}})

    def test_matching_label(self):
        self.assertTrue(vp.label_matches(self.info(1499), "$14.99/month"))
        self.assertTrue(vp.label_matches(self.info(1499), "$14.99 per month"))

    def test_wrong_amount_or_period_is_a_mismatch(self):
        self.assertFalse(vp.label_matches(self.info(999), "$14.99/month"))
        self.assertFalse(vp.label_matches(self.info(1499, "year"), "$14.99/month"))
        self.assertFalse(vp.label_matches(self.info(1499, count=3), "$14.99/month"))

    def test_the_script_only_reads(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "qa" / "verify_pro_price.py").read_text(encoding="utf-8")
        self.assertIn('method="GET"', src)
        self.assertNotIn("POST", src)
        self.assertNotIn("print(key", src)


if __name__ == "__main__":
    unittest.main()
