"""Pure pandas implementations of the V1 technical indicators."""

import pandas as pd


def _ema(series: pd.Series, period: int) -> pd.Series:
    """EMA seeded from the first full-period SMA (standard technical-analysis convention)."""
    values = pd.to_numeric(series, errors="coerce")
    output = pd.Series(float("nan"), index=values.index, dtype="float64")
    valid = values.notna()
    # Missing observations break the sequence rather than being imputed.
    groups = (~valid).cumsum()
    for _, segment in values[valid].groupby(groups[valid]):
        if len(segment) < period:
            continue
        seed_index = segment.index[period - 1]
        output.loc[seed_index] = segment.iloc[:period].mean()
        alpha = 2 / (period + 1)
        previous = output.loc[seed_index]
        for index, value in segment.iloc[period:].items():
            previous = alpha * value + (1 - alpha) * previous
            output.loc[index] = previous
    return output


def _wilder_average(series: pd.Series, period: int) -> pd.Series:
    """Wilder average: initial period SMA followed by recursive alpha=1/period smoothing."""
    values = pd.to_numeric(series, errors="coerce")
    output = pd.Series(float("nan"), index=values.index, dtype="float64")
    valid = values.notna()
    groups = (~valid).cumsum()
    for _, segment in values[valid].groupby(groups[valid]):
        if len(segment) < period:
            continue
        seed_index = segment.index[period - 1]
        output.loc[seed_index] = segment.iloc[:period].mean()
        previous = output.loc[seed_index]
        for index, value in segment.iloc[period:].items():
            previous = (value + (period - 1) * previous) / period
            output.loc[index] = previous
    return output


def add_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of prices with EMA 20/50/200, Wilder RSI 14 and MACD 12/26/9.

    Missing close values remain missing and restart indicator warm-up. No prices are filled.
    EMA outputs begin after a full-period seed; RSI begins after 14 price changes.
    """
    if "Close" not in prices.columns:
        raise ValueError("Price data is missing required column: Close")

    result = prices.copy()
    close = pd.to_numeric(result["Close"], errors="coerce")
    for period in (20, 50, 200):
        result[f"EMA_{period}"] = _ema(close, period)

    delta = close.diff()
    # A gap must reset RSI's rolling initialization; do not treat it as a zero return.
    delta = delta.where(close.notna() & close.shift(1).notna())
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = _wilder_average(gains, 14)
    avg_loss = _wilder_average(losses, 14)
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50)
    result["RSI_14"] = rsi

    fast = _ema(close, 12)
    slow = _ema(close, 26)
    result["MACD"] = fast - slow
    result["MACD_signal"] = _ema(result["MACD"], 9)
    result["MACD_histogram"] = result["MACD"] - result["MACD_signal"]
    return result
