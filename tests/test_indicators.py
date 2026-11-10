import unittest

import pandas as pd

from yxstock.analysis.indicators import add_indicators


class IndicatorTests(unittest.TestCase):
    def test_insufficient_history_is_nan(self):
        prices = pd.DataFrame({"Close": [1., 2., 3., 4., 5.]})
        result = add_indicators(prices)
        # EMA20 is not available until a full 20-observation SMA seed exists.
        self.assertTrue(result["EMA_20"].isna().all())

    def test_ema_seed_and_recursive_values(self):
        values = pd.Series([float(i) for i in range(1, 21)])
        prices = pd.DataFrame({"Close": values})
        result = add_indicators(prices)
        self.assertAlmostEqual(result["EMA_20"].iloc[19], 10.5)

    def test_all_ema_periods_use_sma_seed_then_recursive_smoothing(self):
        close = pd.Series([float(i) for i in range(1, 221)])
        result = add_indicators(pd.DataFrame({"Close": close}))
        for period in (20, 50, 200):
            self.assertAlmostEqual(result[f"EMA_{period}"].iloc[period - 1], close.iloc[:period].mean())
            expected_next = close.iloc[:period].mean() + (2 / (period + 1)) * (close.iloc[period] - close.iloc[:period].mean())
            self.assertAlmostEqual(result[f"EMA_{period}"].iloc[period], expected_next)

    def test_wilder_rsi_known_dataset(self):
        # Classic 14-period RSI example; first value uses SMA of first 14 price changes.
        changes = [ -0.10, 0.10, 0.20, -0.10, 0.15, -0.05, 0.10, -0.10, 0.15, -0.05, 0.10, -0.10, 0.15, -0.05 ]
        close = [100.0]
        for change in changes:
            close.append(close[-1] + change)
        prices = pd.DataFrame({"Close": close})
        result = add_indicators(prices)
        gain = sum(max(change, 0) for change in changes) / 14
        loss = sum(max(-change, 0) for change in changes) / 14
        expected = 100 - 100 / (1 + gain / loss)
        self.assertAlmostEqual(result["RSI_14"].iloc[14], expected, places=10)

    def test_flat_rsi_and_nan_gap(self):
        flat = add_indicators(pd.DataFrame({"Close": [5.] * 20}))
        self.assertEqual(flat["RSI_14"].iloc[-1], 50.)
        close = [float(i) for i in range(1, 31)]
        close[15] = float("nan")
        result = add_indicators(pd.DataFrame({"Close": close}))
        self.assertTrue(pd.isna(result["EMA_20"].iloc[19]))
        self.assertTrue(pd.isna(result["EMA_20"].iloc[29]))

    def test_macd_formula(self):
        close = pd.Series([100 + i * 0.7 + (i % 5) for i in range(80)])
        result = add_indicators(pd.DataFrame({"Close": close}))
        # Indicator implementation seeds each EMA with its full-period SMA.
        self.assertTrue(pd.isna(result["MACD"].iloc[24]))
        self.assertTrue(result["MACD"].notna().iloc[25])
        self.assertTrue(pd.isna(result["MACD_signal"].iloc[32]))
        self.assertTrue(result["MACD_signal"].notna().iloc[33])
        self.assertAlmostEqual(result["MACD_histogram"].iloc[-1], result["MACD"].iloc[-1] - result["MACD_signal"].iloc[-1])

    def test_requires_close(self):
        with self.assertRaises(ValueError):
            add_indicators(pd.DataFrame({"Open": [1]}))


if __name__ == "__main__":
    unittest.main()
