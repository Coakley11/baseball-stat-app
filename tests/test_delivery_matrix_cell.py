"""Matrix cell query-param mapping."""

from __future__ import annotations

import unittest

from live_draft_solo_delivery_diag import delivery_matrix_cell


class DeliveryMatrixCellTests(unittest.TestCase):
    def test_matrix_param(self) -> None:
        class St:
            query_params = {"solo_delivery_matrix": "3", "solo_delivery_diag": "1"}

        self.assertEqual(delivery_matrix_cell(St()), 3)

    def test_case_a_maps_to_one(self) -> None:
        class St:
            query_params = {"solo_delivery_case": "A", "solo_delivery_diag": "1"}

        self.assertEqual(delivery_matrix_cell(St()), 1)


if __name__ == "__main__":
    unittest.main()
