import tempfile
import unittest
from pathlib import Path

import numpy as np

from nasa_explorer.processing.gcov import prepare_cog


class GcovCogTests(unittest.TestCase):
    def test_cog_preserves_finite_values_mask_grid_and_lineage(self):
        values = np.arange(512 * 512, dtype="<f4").reshape((512, 512)) / 100
        values[0, 0] = np.nan
        tags = {"stac_item_id": "case:gcov:hh:2026-06-17", "crid": "P05023"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.f32"
            output = root / "output.tif"
            values.tofile(source)
            kwargs = {"width": 512, "height": 512, "crs": "EPSG:32610",
                      "transform": [30, 0, 500000, 0, -30, 3800000], "tags": tags}
            info = prepare_cog(source, output, **kwargs)
            replay = prepare_cog(source, output, **kwargs)
            self.assertEqual(info["valid_pixels"], values.size - 1)
            self.assertEqual(info["unit"], "dB")
            self.assertTrue(info["sha256"])
            self.assertEqual(info["sha256"], replay["sha256"])

    def test_invalid_source_size_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bad.f32"
            source.write_bytes(b"bad")
            with self.assertRaises(ValueError):
                prepare_cog(source, root / "output.tif", width=2, height=2, crs="EPSG:32610",
                            transform=[30, 0, 0, 0, -30, 0], tags={})


if __name__ == "__main__":
    unittest.main()
