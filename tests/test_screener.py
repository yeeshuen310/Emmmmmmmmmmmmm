import unittest

import pandas as pd

from yxstock.services.screener import (classify_trend, evaluate_strategies,
                                       matches_trend_following, overextension_warnings, relative_volume)
from yxstock.services.watchlist import market_for_ticker


class ScreenerTests(unittest.TestCase):
    def test_relative_volume_excludes_current_session(self):
        volume = pd.Series([100.] * 20 + [200.])
        self.assertEqual(relative_volume(volume).iloc[-1], 2.)

    def test_missing_and_insufficient_data(self):
        self.assertFalse(evaluate_strategies(pd.DataFrame())["Trend Following"]["matched"])
        small = pd.DataFrame({"Open": [1.] * 20, "High": [2.] * 20, "Low": [.5] * 20,
                              "Close": [1.] * 20, "Volume": [100.] * 20})
        self.assertIn("Insufficient", evaluate_strategies(small)["Breakout"]["reason"])

    def test_us_and_bursa_symbols(self):
        self.assertEqual(market_for_ticker("MSFT"), "US")
        self.assertEqual(market_for_ticker("1023.KL"), "Bursa Malaysia")

    def test_trend_following_requires_ema20_above_ema50(self):
        self.assertTrue(matches_trend_following(110,108,105,100,60,1.3))
        self.assertFalse(matches_trend_following(110,104,105,100,60,1.3))
        self.assertFalse(matches_trend_following(110,108,105,100,71,1.3))
        self.assertFalse(matches_trend_following(110,108,105,100,60,1.2))
        self.assertEqual(classify_trend(110, 105, 106, 100), "Developing Trend")
        self.assertEqual(classify_trend(110, 108, 105, 100), "Strong Trend")
        self.assertEqual(classify_trend(90, 95, 100, 80), "Weak Trend")

    def test_distance_warning_thresholds(self):
        warnings = overextension_warnings(109, 100, 71, 8.1)
        self.assertEqual(len(warnings), 3)
        self.assertEqual(overextension_warnings(105, 100, 65, 2), [])


if __name__ == "__main__":
    unittest.main()
