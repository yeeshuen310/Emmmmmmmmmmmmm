"""Completed-session strategy screening using Yahoo Finance daily history."""

from dataclasses import dataclass
from datetime import datetime, timezone
import time

import pandas as pd
import yfinance as yf

from yxstock.analysis.indicators import add_indicators
from yxstock.services.watchlist import market_for_ticker, validate_watchlist_ticker


@dataclass
class ScreenConfig:
    universe: list[str]
    strategy: str = "All strategies"
    min_rsi: float = 0.0
    max_rsi: float = 100.0
    relative_volume_threshold: float = 0.0
    min_market_cap: float = 0.0
    ema_fast: int = 50
    ema_slow: int = 200
    exchange: str = "Any"
    currency: str = "Any"
    batch_size: int = 50
    retries: int = 2


STRATEGIES = ["Oversold Recovery", "Trend Following", "Breakout"]


def classify_trend(close, ema20, ema50, ema200) -> str:
    values = [close, ema20, ema50, ema200]
    if any(pd.isna(v) for v in values):
        return "Unavailable"
    if close > ema20 > ema50 > ema200:
        return "Strong Trend"
    if close <= ema50:
        return "Weak Trend"
    if close > ema200 and ema50 > ema200 and ema20 <= ema50:
        return "Developing Trend"
    return "Mixed Structure"


def matches_trend_following(close, ema20, ema50, ema200, rsi, relative_vol) -> bool:
    values = [close, ema20, ema50, ema200, rsi, relative_vol]
    if any(pd.isna(v) for v in values):
        return False
    return close > ema200 and ema20 > ema50 and ema50 > ema200 and 50 <= rsi <= 70 and relative_vol > 1.2


def overextension_warnings(close, ema20, rsi, daily_change_pct) -> list[str]:
    warnings = []
    if pd.notna(ema20) and ema20 > 0 and (close / ema20 - 1) * 100 > 8:
        warnings.append("Close >8% above EMA20")
    if pd.notna(rsi) and rsi > 70:
        warnings.append("RSI above 70")
    if pd.notna(daily_change_pct) and daily_change_pct > 8:
        warnings.append("Daily change above 8%")
    return warnings


def relative_volume(volume: pd.Series, window: int = 20) -> pd.Series:
    """Compare each completed daily volume with the prior window's average, excluding itself."""
    values = pd.to_numeric(volume, errors="coerce")
    average = values.shift(1).rolling(window, min_periods=window).mean()
    return values / average.where(average > 0)


def evaluate_strategies(history: pd.DataFrame, market_cap: float | None = None,
                        minimum_market_cap: float = 0.0, ema_fast: int = 50,
                        ema_slow: int = 200) -> dict[str, dict[str, object]]:
    """Evaluate only the last completed daily bar; return matched rules and explicit reasons."""
    required = {"Open", "High", "Low", "Close", "Volume"}
    if history is None or not required.issubset(history.columns):
        return {name: {"matched": False, "reason": "Required OHLCV data unavailable."} for name in STRATEGIES}
    frame = history[list(required)].copy()
    frame = frame.sort_index()
    if len(frame) < max(ema_slow, 21) + 1:
        return {name: {"matched": False, "reason": "Insufficient completed daily history."} for name in STRATEGIES}
    if frame.iloc[-2:][["Open", "High", "Low", "Close", "Volume"]].isna().any().any():
        return {name: {"matched": False, "reason": "Latest completed session contains missing OHLCV data."} for name in STRATEGIES}
    indicators = add_indicators(frame)
    rv = relative_volume(frame["Volume"])
    current, previous = indicators.iloc[-1], indicators.iloc[-2]
    close = float(current["Close"])
    rsi = current["RSI_14"]
    ema20 = current.get("EMA_20")
    ema50 = current.get(f"EMA_{ema_fast}")
    ema200 = current.get(f"EMA_{ema_slow}")
    relvol = rv.iloc[-1]
    prev_high20 = frame["High"].shift(1).rolling(20, min_periods=20).max().iloc[-1]
    cap_ok = market_cap is not None and pd.notna(market_cap) and market_cap >= minimum_market_cap
    common_available = all(pd.notna(v) for v in [rsi, ema50, ema200, relvol])

    def result(passed: bool, reason: str) -> dict[str, object]:
        return {"matched": passed, "reason": reason}

    if not common_available:
        unavailable = "Required indicator unavailable because history has gaps or too few observations."
        return {name: result(False, unavailable) for name in STRATEGIES}
    oversold = close > ema200 and previous["RSI_14"] <= 30 < rsi and relvol > 1.5 and cap_ok
    trend = matches_trend_following(close, ema20, ema50, ema200, rsi, relvol)
    breakout = pd.notna(prev_high20) and close > prev_high20 and ema50 > ema200 and 55 <= rsi <= 75 and relvol > 2.0
    cap_reason = "Market cap unavailable or below configured minimum." if not cap_ok else ""
    return {
        "Oversold Recovery": result(bool(oversold), "Passed: close > EMA200; RSI crossed above 30; relative volume > 1.5; market cap meets threshold." if oversold else cap_reason or "One or more completed-session recovery conditions did not pass."),
        "Trend Following": result(bool(trend), "Passed: close > EMA200; EMA20 > EMA50 > EMA200; RSI 50–70; relative volume > 1.2." if trend else "One or more completed-session trend conditions did not pass."),
        "Breakout": result(bool(breakout), "Passed: close > prior 20-session high; EMA50 > EMA200; RSI 55–75; relative volume > 2.0." if breakout else "One or more completed-session breakout conditions did not pass."),
    }


def screen_universe(config: ScreenConfig) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Batch scan and report every symbol outcome; only matched symbols are returned as rows."""
    tickers = list(dict.fromkeys(validate_watchlist_ticker(t)[0] for t in config.universe))
    updated = datetime.now(timezone.utc)
    report = {"total": len(tickers), "eligible": 0, "success": 0, "failed": [], "insufficient": [],
              "matching": 0, "started_at": updated, "completed_at": None, "status": "full"}
    if not tickers:
        report.update(status="failed", completed_at=datetime.now(timezone.utc))
        return [], report
    rows = []
    report['eligible'] = len(tickers)
    for offset in range(0, len(tickers), max(1, min(100, config.batch_size))):
        batch = tickers[offset:offset + max(1, min(100, config.batch_size))]
        data = None
        for attempt in range(config.retries + 1):
            try:
                data = yf.download(tickers=batch, period="2y", interval="1d", group_by="ticker", auto_adjust=False,
                                   actions=False, progress=False, threads=False, timeout=35)
                break
            except Exception as exc:
                if attempt >= config.retries:
                    report['failed'].extend({"ticker": t, "reason": str(exc)} for t in batch)
                else:
                    time.sleep(min(2 ** attempt, 8))
        if data is None:
            continue
        for ticker in batch:
          try:
            bars = data[ticker].dropna(how="all").copy() if isinstance(data.columns, pd.MultiIndex) and ticker in data.columns.get_level_values(0) else pd.DataFrame()
            if bars.empty or not {"Open","High","Low","Close","Volume"}.issubset(bars.columns):
                report['insufficient'].append({"ticker": ticker, "reason": "No supported historical OHLCV data"})
                continue
            if len(bars) < max(config.ema_slow, 200) + 21:
                report['insufficient'].append({"ticker": ticker, "reason": f"Only {len(bars)} daily rows available"})
                continue
            info = yf.Ticker(ticker).get_info()
            cap_raw = info.get("marketCap")
            cap = float(cap_raw) if cap_raw is not None and pd.notna(cap_raw) else None
            exchange = str(info.get("exchangeName") or info.get("fullExchangeName") or "Unavailable")
            currency = str(info.get("currency") or "Unavailable")
            market = market_for_ticker(ticker)
            if config.exchange != "Any" and config.exchange.casefold() not in exchange.casefold():
                continue
            if config.currency != "Any" and currency != config.currency:
                continue
            analyzed = add_indicators(bars)
            strategies = evaluate_strategies(bars, cap, config.min_market_cap, config.ema_fast, config.ema_slow)
            report['success'] += 1
            matched = [name for name, item in strategies.items() if item["matched"]]
            if config.strategy != "All strategies":
                matched = [name for name in matched if name == config.strategy]
            last = analyzed.iloc[-1]
            rv = relative_volume(bars["Volume"]).iloc[-1]
            rsi = last["RSI_14"]
            if pd.isna(rsi) or not config.min_rsi <= rsi <= config.max_rsi:
                continue
            if pd.isna(rv) or rv < config.relative_volume_threshold:
                continue
            if config.strategy != "All strategies" and not matched:
                continue
            if config.strategy == "All strategies" and not matched:
                continue
            prev = bars["Close"].iloc[-2]
            last_close = bars["Close"].iloc[-1]
            daily_change = float((last_close / prev - 1) * 100) if prev else None
            ema20_value = float(last["EMA_20"]) if pd.notna(last["EMA_20"]) else None
            ema50_value = float(last["EMA_50"]) if pd.notna(last["EMA_50"]) else None
            ema200_value = float(last["EMA_200"]) if pd.notna(last["EMA_200"]) else None
            distance = lambda ema: (float(last_close) / ema - 1) * 100 if ema is not None and ema != 0 else None
            structure = classify_trend(float(last_close), ema20_value, ema50_value, ema200_value)
            warnings = overextension_warnings(float(last_close), ema20_value, float(rsi), daily_change)
            rows.append({"Ticker": ticker, "Company": info.get("longName") or info.get("shortName") or ticker,
                         "Market": market, "Exchange": exchange, "Currency": currency,
                         "Latest close": float(last_close), "Daily change %": daily_change,
                         "Market cap": cap, "RSI": float(rsi),
                         "EMA 20": float(last["EMA_20"]) if pd.notna(last["EMA_20"]) else None,
                         "EMA 50": float(last["EMA_50"]) if pd.notna(last["EMA_50"]) else None,
                         "EMA 200": float(last["EMA_200"]) if pd.notna(last["EMA_200"]) else None,
                         "Distance from EMA20 %": distance(ema20_value),
                         "Distance from EMA50 %": distance(ema50_value),
                         "Distance from EMA200 %": distance(ema200_value),
                         "Trend Structure": structure,
                         "Overextension Risk": "; ".join(warnings) if warnings else "No threshold warning",
                         "Relative volume": float(rv), "Matching strategy": ", ".join(matched),
                         "Why passed": " ".join(strategies[s]["reason"] for s in matched),
                         "Source": "Yahoo Finance daily history (may be delayed)", "Last updated": updated})
          except Exception as exc:
            report['failed'].append({"ticker": ticker, "reason": str(exc)})
    report['matching'] = len(rows)
    report['completed_at'] = datetime.now(timezone.utc)
    report['status'] = "full" if report['success'] + len(report['failed']) + len(report['insufficient']) == report['total'] and not report['failed'] else "partial"
    report['duration_seconds'] = (report['completed_at'] - report['started_at']).total_seconds()
    return rows, report
