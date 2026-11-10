import tempfile
import unittest
from pathlib import Path

import pandas as pd

from yxstock.storage.cache import PriceCache


class CacheTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = PriceCache(Path(folder) / "prices.db")
            source = pd.DataFrame({"Open": [10.0], "High": [12.0], "Low": [9.0], "Close": [11.0], "Volume": [100]},
                                  index=pd.to_datetime(["2025-01-02"]))
            cache.save("abc", source)
            result = cache.load("ABC")
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]["Close"], 11.0)


if __name__ == "__main__":
    unittest.main()
