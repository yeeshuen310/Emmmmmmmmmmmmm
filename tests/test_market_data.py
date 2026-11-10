import unittest
from unittest.mock import patch

import pandas as pd

from yxstock.analysis.indicators import add_indicators
from yxstock.services.market_data import MarketDataError, PERIODS, _validate_ohlcv, fetch_history


def sample_history(index):
    return pd.DataFrame({"Open": [10.] * len(index), "High": [12.] * len(index), "Low": [9.] * len(index),
                         "Close": [11.] * len(index), "Volume": [1000.] * len(index)}, index=index)


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, **kwargs):
        self.history_args = kwargs
        index = pd.date_range("2025-01-01", periods=700, freq="B", tz="America/New_York")
        return sample_history(index)

    def get_info(self):
        if self.symbol.endswith(".KL"):
            return {"longName": "Example Bursa Company", "exchangeName": "Kuala Lumpur", "currency": "MYR"}
        return {"longName": "Apple Inc.", "exchangeName": "NasdaqGS", "currency": "USD"}


class MarketDataTests(unittest.TestCase):
    @patch("yxstock.services.market_data.yf.Ticker", FakeTicker)
    def test_aapl_metadata_and_warmup_request(self):
        data = fetch_history("AAPL", "1 year")
        self.assertEqual(data.ticker, "AAPL")
        self.assertEqual(data.exchange, "NasdaqGS")
        self.assertEqual(data.currency, "USD")
        self.assertEqual(data.source, "Yahoo Finance via yfinance")
        self.assertTrue(data.retrieved_at.tzinfo)
        self.assertGreater(data.warmup_observations, 0)
        self.assertEqual(len(data.prices), 700)  # Warm-up rows remain available to seed indicators.
        self.assertLess(data.prices.index[0], data.chart_start)
        chart = add_indicators(data.prices).loc[lambda frame: frame.index >= data.chart_start]
        self.assertFalse(pd.isna(chart["EMA_200"].iloc[0]))

    @patch("yxstock.services.market_data.yf.Ticker", FakeTicker)
    def test_bursa_symbol_metadata(self):
        data = fetch_history("1155.kl", "1 year")
        self.assertEqual(data.ticker, "1155.KL")
        self.assertEqual(data.exchange, "Kuala Lumpur")
        self.assertEqual(data.currency, "MYR")

    def test_period_options(self):
        self.assertIn("2 years", PERIODS)
        self.assertIn("5 years", PERIODS)

    def test_empty_and_invalid_rows_are_errors(self):
        with self.assertRaises(MarketDataError):
            _validate_ohlcv(pd.DataFrame(), "AAPL")
        bad = sample_history(pd.date_range("2025-01-01", periods=1))
        bad.loc[:, "Close"] = float("nan")
        with self.assertRaises(MarketDataError):
            _validate_ohlcv(bad, "AAPL")

    def test_invalid_ohlc_relation_is_error(self):
        bad = sample_history(pd.date_range("2025-01-01", periods=1))
        bad.loc[bad.index[0], "Low"] = 11.5
        with self.assertRaises(MarketDataError):
            _validate_ohlcv(bad, "AAPL")


if __name__ == "__main__":
    unittest.main()
