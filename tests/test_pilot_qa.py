import unittest

import numpy as np

from scripts.qualify_pilot import aggregate, metrics


class PilotMathTests(unittest.TestCase):
    def test_aggregate_linear_power_and_reject_insufficient_support(self):
        power = np.ones((3, 9))
        power[0, 0] = 9
        valid = np.ones_like(power, dtype=bool)
        valid[0, 3] = False
        valid[0, 6:8] = False
        actual = aggregate(power, valid, (1, 3), (0, 0))
        np.testing.assert_allclose(actual, [[10 * np.log10(17 / 9), 0, np.nan]])

    def test_threshold_edges_and_paired_support(self):
        delta = np.array([[3., -3., np.nan, 2.99, 8.]])
        selected = np.array([[True, True, True, True, False]])
        report = metrics(delta, selected)
        self.assertEqual(report["valid_cells"], 3)
        self.assertEqual(report["coverage"], 0.75)
        for direction in ("increase", "decrease"):
            result = report["thresholds"][3][direction]
            self.assertEqual(result["cells"], 1)
            self.assertAlmostEqual(result["km2"], 0.0009)
            self.assertAlmostEqual(result["percent"], 100 / 3)

    def test_no_valid_pair_has_no_threshold_metrics(self):
        report = metrics(np.array([[np.nan]]), np.array([[True]]))
        self.assertEqual(report["valid_cells"], 0)
        self.assertEqual(report["thresholds"], {})


if __name__ == "__main__":
    unittest.main()
