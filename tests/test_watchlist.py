import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from yxstock.services.watchlist import INITIAL_WATCHLIST, fetch_watchlist_quotes, market_for_ticker, validate_watchlist_ticker
from yxstock.storage.cache import PriceCache


class WatchlistTests(unittest.TestCase):
    def test_initial_list_and_market_classification(self):
        self.assertEqual(len(INITIAL_WATCHLIST), 6)
        self.assertEqual(market_for_ticker("aapl"), "US")
        self.assertEqual(market_for_ticker("1155.kl"), "Bursa Malaysia")
        self.assertEqual(validate_watchlist_ticker("1155.kl")[0], "1155.KL")
        with self.assertRaises(ValueError):
            validate_watchlist_ticker("ABC.L")

    def test_sqlite_watchlist_persistence_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "yxstock.db"
            cache = PriceCache(path)
            self.assertTrue(cache.add_to_watchlist("AAPL", "US"))
            self.assertFalse(cache.add_to_watchlist("AAPL", "US"))
            self.assertEqual(PriceCache(path).get_watchlist()[0]["ticker"], "AAPL")
            self.assertTrue(cache.remove_from_watchlist("AAPL"))

    @patch("yxstock.services.watchlist.yf.download")
    @patch("yxstock.services.watchlist.yf.Ticker")
    def test_quote_enrichment_reuses_indicator_module(self, ticker, download):
        index = pd.date_range("2025-01-01", periods=260, freq="B")
        close = [100. + i for i in range(len(index))]
        frame = pd.DataFrame({"Open": close, "High": [x + 1 for x in close], "Low": [x - 1 for x in close], "Close": close, "Volume": [1000.] * len(index)}, index=index)
        download.return_value = pd.concat({"AAPL": frame}, axis=1)
        ticker.return_value.get_info.return_value = {"longName": "Apple Inc.", "currency": "USD", "exchangeName": "NasdaqGS"}
        result = fetch_watchlist_quotes(["AAPL"])["AAPL"]
        self.assertEqual(result["company_name"], "Apple Inc.")
        self.assertEqual(result["currency"], "USD")
        self.assertAlmostEqual(result["previous_close"], close[-2])
        self.assertGreater(result["ema_20"], 0)
        self.assertIn("historical close", result["source"])


if __name__ == "__main__":
    unittest.main()
