"""Watchlist symbol classification and batched quote enrichment."""

from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from yxstock.analysis.indicators import add_indicators
from yxstock.services.market_data import MarketDataError, normalize_ticker

INITIAL_WATCHLIST = ["AAPL", "TSLA", "NVDA", "MSFT", "1155.KL", "1023.KL"]


def market_for_ticker(value: str) -> str:
    ticker = normalize_ticker(value)
    if ticker.endswith(".KL"):
        return "Bursa Malaysia"
    if "." in ticker:
        raise ValueError("Only US symbols and Bursa symbols ending in .KL are supported.")
    return "US"


def validate_watchlist_ticker(value: str) -> tuple[str, str]:
    ticker = normalize_ticker(value)
    market = market_for_ticker(ticker)
    if not ticker.replace(".", "").replace("-", "").isalnum():
        raise ValueError("Ticker contains unsupported characters.")
    if market == "Bursa Malaysia" and len(ticker.split(".")[0]) != 4:
        raise ValueError("Bursa ticker should use four digits and the .KL suffix, for example 1155.KL.")
    return ticker, market


def fetch_watchlist_quotes(tickers: list[str]) -> dict[str, dict[str, object]]:
    """Fetch prices once for all symbols; return per-symbol errors without fabricating data."""
    if not tickers:
        return {}
    normalized = [validate_watchlist_ticker(t)[0] for t in tickers]
    try:
        downloaded = yf.download(
            tickers=normalized, period="1y", interval="1d", group_by="ticker",
            auto_adjust=False, actions=False, progress=False, threads=False,
        )
    except Exception as exc:
        return {ticker: {"error": f"Yahoo Finance request failed: {exc}"} for ticker in normalized}

    result: dict[str, dict[str, object]] = {}
    updated = datetime.now(timezone.utc)
    for ticker in normalized:
        try:
            if len(normalized) == 1 and not isinstance(downloaded.columns, pd.MultiIndex):
                frame = downloaded
            else:
                frame = downloaded[ticker].copy()
            frame = frame.dropna(how="all")
            required = {"Open", "High", "Low", "Close", "Volume"}
            if frame.empty or not required.issubset(frame.columns):
                raise MarketDataError("No usable historical OHLCV data is available.")
            # Validate every bar; null/malformed prices must not be silently dropped or filled.
            frame = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
            valid = frame.notna().all(axis=1)
            valid &= frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1)
            valid &= frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1)
            valid &= frame["Volume"] >= 0
            if not valid.all():
                raise MarketDataError("Historical OHLCV data contains missing or invalid rows.")
            if len(frame) < 2:
                raise MarketDataError("Insufficient history: need two valid trading sessions for daily change.")
            analyzed = add_indicators(frame)
            latest, previous = frame["Close"].iloc[-1], frame["Close"].iloc[-2]
            info = yf.Ticker(ticker).get_info()
            currency = str(info.get("currency") or "Unavailable")
            exchange = str(info.get("exchangeName") or info.get("fullExchangeName") or "Unavailable")
            result[ticker] = {
                "company_name": info.get("longName") or info.get("shortName") or ticker,
                "ticker": ticker,
                "market": market_for_ticker(ticker),
                "currency": currency,
                "exchange": exchange,
                "latest_close": float(latest),
                "previous_close": float(previous),
                "daily_change_pct": float((latest / previous - 1) * 100) if previous else None,
                "volume": float(frame["Volume"].iloc[-1]),
                "rsi_14": float(analyzed["RSI_14"].iloc[-1]) if pd.notna(analyzed["RSI_14"].iloc[-1]) else None,
                "ema_20": float(analyzed["EMA_20"].iloc[-1]) if pd.notna(analyzed["EMA_20"].iloc[-1]) else None,
                "ema_50": float(analyzed["EMA_50"].iloc[-1]) if pd.notna(analyzed["EMA_50"].iloc[-1]) else None,
                "source": "Yahoo Finance via yfinance (daily historical close; may be delayed)",
                "updated_at": updated,
                "last_session": pd.Timestamp(frame.index[-1]),
            }
        except Exception as exc:
            result[ticker] = {"ticker": ticker, "market": market_for_ticker(ticker), "error": str(exc)}
    return result
