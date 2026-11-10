import tempfile
import unittest
from pathlib import Path

from yxstock.services.universes import normalize_yahoo_symbol, USUniverseManager
from yxstock.storage.cache import PriceCache


class UniverseTests(unittest.TestCase):
    def test_yahoo_symbol_normalization(self):
        self.assertEqual(normalize_yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(normalize_yahoo_symbol("aapl"), "AAPL")

    def test_duplicate_removal_and_separate_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=PriceCache(Path(tmp)/"u.db")
            manager=USUniverseManager(cache)
            manager.cache.save_universe("S&P 500",[
                {"ticker":"AAPL","company_name":"Apple","sector":"Technology","industry":"Hardware"},
                {"ticker":"MSFT","company_name":"Microsoft","sector":"Technology","industry":"Software"}],
                "https://source.test/sp", __import__('datetime').datetime.now(__import__('datetime').timezone.utc))
            manager.cache.save_universe("NASDAQ 100",[
                {"ticker":"AAPL","company_name":"Apple","sector":"Technology","industry":"Hardware"}],
                "https://source.test/ndx", __import__('datetime').datetime.now(__import__('datetime').timezone.utc))
            combined=manager.combined_us_large_cap()
            self.assertEqual(len(combined),2)
            self.assertEqual(len(cache.load_universe("NASDAQ 100")),1)


if __name__ == '__main__': unittest.main()
