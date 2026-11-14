import unittest

import numpy as np

from scripts.build_release import rgba, stats


class ReleaseMathTests(unittest.TestCase):
    def test_pair_thresholds_use_paired_cells_and_fixed_cell_area(self):
        delta = np.array([[4.0, 3.0, -4.0, -3.0, 2.0, np.nan]])
        paired = np.array([[True, True, True, True, False, True]])
        eligible = np.ones_like(paired)

        report = stats(delta, paired, eligible, 3)

        self.assertEqual(report["valid_cells"], 4)
        self.assertEqual(report["valid_area_km2"], 0.0036)
        self.assertEqual(report["coverage"], 4 / 6)
        self.assertEqual(report["thresholds_db"]["3"]["increase"]["cells"], 2)
        self.assertEqual(report["thresholds_db"]["3"]["decrease"]["cells"], 2)
        self.assertEqual(report["thresholds_db"]["4"]["increase"]["cells"], 1)

    def test_zero_support_has_no_median_or_threshold_percentages(self):
        report = stats(np.array([[np.nan]]), np.array([[True]]), np.array([[True]]), 3)

        self.assertEqual(report["valid_cells"], 0)
        self.assertEqual(report["coverage"], 0.0)
        self.assertIsNone(report["median_db"])
        self.assertIsNone(report["thresholds_db"]["3"]["increase"]["percent"])

    def test_missing_values_render_transparent_and_difference_zero_is_neutral(self):
        image = rgba(np.array([[-6.0, 0.0, 6.0, np.nan]]), 6, 6, difference=True)

        np.testing.assert_array_equal(image[0, 0], [0, 0, 255, 255])
        np.testing.assert_array_equal(image[0, 1], [255, 255, 255, 255])
        np.testing.assert_array_equal(image[0, 2], [255, 0, 0, 255])
        self.assertEqual(image[0, 3, 3], 0)


if __name__ == "__main__":
    unittest.main()
