"""Yahoo Finance market-data access and OHLCV validation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

PERIODS = {"1 month": "1mo", "3 months": "3mo", "6 months": "6mo", "1 year": "1y", "2 years": "2y", "5 years": "5y"}
PERIOD_DAYS = {"1mo": 31, "3mo": 93, "6mo": 186, "1y": 366, "2y": 731, "5y": 1827}
WARMUP_CALENDAR_DAYS = 370  # Covers 250 trading observations plus holidays/weekends.
OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


@dataclass
class MarketData:
    ticker: str
    company_name: str
    exchange: str
    currency: str
    prices: pd.DataFrame
    chart_start: pd.Timestamp
    source: str
    retrieved_at: datetime
    delayed_notice: str = "Yahoo Finance quotes can be delayed; delay depends on exchange and provider."
    warmup_observations: int = 0


class MarketDataError(RuntimeError):
    """Raised when a ticker has no usable historical prices."""


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not ticker or len(ticker) > 24 or any(char.isspace() for char in ticker):
        raise ValueError("Enter a ticker such as AAPL or 1155.KL.")
    return ticker


def _validate_ohlcv(history: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if history is None or history.empty:
        raise MarketDataError(f"No historical price data is available for {ticker}. Verify the ticker and exchange suffix.")
    missing = [column for column in OHLCV_COLUMNS if column not in history.columns]
    if missing:
        raise MarketDataError(f"Yahoo Finance returned incomplete OHLCV data for {ticker}; missing columns: {', '.join(missing)}.")
    prices = history.loc[:, OHLCV_COLUMNS].copy()
    for column in OHLCV_COLUMNS:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    # Reject malformed bars; do not fill missing components or silently remove rows.
    valid = prices[OHLCV_COLUMNS].notna().all(axis=1)
    valid &= prices["Low"] <= prices[["Open", "Close", "High"]].min(axis=1)
    valid &= prices["High"] >= prices[["Open", "Close", "Low"]].max(axis=1)
    valid &= prices["Volume"] >= 0
    bad_count = int((~valid).sum())
    if bad_count:
        raise MarketDataError(f"Yahoo Finance returned {bad_count} row(s) with missing or invalid OHLCV values for {ticker}; data was not repaired.")
    index = pd.DatetimeIndex(pd.to_datetime(prices.index))
    # Preserve actual exchange dates in their local timezone for consistent chart alignment.
    prices.index = index
    prices.index.name = "Date"
    if prices.index.has_duplicates:
        raise MarketDataError(f"Yahoo Finance returned duplicate dates for {ticker}; data was not deduplicated.")
    return prices.sort_index()


def fetch_history(value: str, period: str) -> MarketData:
    ticker = normalize_ticker(value)
    if period not in PERIODS:
        raise ValueError(f"Unsupported history period: {period}")

    end = datetime.now(timezone.utc)
    requested_start = end - timedelta(days=PERIOD_DAYS[PERIODS[period]])
    download_start = requested_start - timedelta(days=WARMUP_CALENDAR_DAYS)
    instrument = yf.Ticker(ticker)
    try:
        # Explicit start/end fetches a 370-day indicator warm-up before the selected chart period.
        raw = instrument.history(start=download_start.date().isoformat(), end=(end + timedelta(days=1)).date().isoformat(),
                                 auto_adjust=False, actions=False, raise_errors=True)
    except Exception as exc:
        raise MarketDataError(f"Yahoo Finance could not retrieve {ticker}: {exc}") from exc
    if raw is None or raw.empty:
        raise MarketDataError(f"No historical price data is available for {ticker}. The symbol may be unsupported or unavailable from Yahoo Finance.")
    # Missing/invalid rows are a data-quality error and stay visible as an explicit failure.
    all_prices = _validate_ohlcv(raw, ticker)
    try:
        info = instrument.get_info()
    except Exception:
        # Price history remains useful when Yahoo's metadata endpoint is unavailable.
        info = {}
    cutoff = pd.Timestamp(requested_start.date())
    if all_prices.index.tz is not None:
        cutoff = cutoff.tz_localize(all_prices.index.tz)
    chart_prices = all_prices.loc[all_prices.index >= cutoff].copy()
    if chart_prices.empty:
        raise MarketDataError(f"Yahoo returned data for {ticker}, but none falls within the selected {period} period.")

    exchange = str(info.get("exchangeName") or info.get("fullExchangeName") or info.get("exchange") or "Unavailable")
    currency = str(info.get("currency") or "Unavailable")
    if ticker.endswith(".KL") and currency not in {"MYR", "Unavailable"}:
        # Provider metadata is authoritative; show it as returned and avoid assuming MYR.
        pass
    company = info.get("longName") or info.get("shortName") or ticker
    warmup = int((all_prices.index < cutoff).sum())
    return MarketData(ticker=ticker, company_name=company, exchange=exchange, currency=currency,
                      prices=all_prices, chart_start=cutoff, source="Yahoo Finance via yfinance", retrieved_at=datetime.now(timezone.utc),
                      warmup_observations=warmup)
