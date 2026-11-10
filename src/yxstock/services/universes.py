"""Cached US index constituents. Sources are public constituent tables, not licensed feeds."""

from datetime import datetime, timezone
from io import StringIO

import pandas as pd
import requests

from yxstock.services.market_data import normalize_ticker

SOURCES = {
    "S&P 500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "NASDAQ 100": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
}


def normalize_yahoo_symbol(symbol: str) -> str:
    return normalize_ticker(symbol).replace(".", "-")


def retrieve_constituents(universe: str) -> tuple[list[dict[str, str]], str, datetime]:
    if universe not in SOURCES:
        raise ValueError(f"Unsupported universe: {universe}")
    url = SOURCES[universe]
    response = requests.get(url, timeout=25, headers={"User-Agent": "YxStock research screener/1.4"})
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    table = next((t for t in tables if any(str(c).lower() in {"symbol", "ticker"} for c in t.columns)), None)
    if table is None:
        raise RuntimeError(f"No constituent table found at {url}")
    lower = {str(c).lower(): c for c in table.columns}
    symbol_col = lower.get("symbol", lower.get("ticker"))
    name_col = next((lower[k] for k in ("security", "company", "name") if k in lower), None)
    sector_col = next((lower[k] for k in ("gics sector", "sector") if k in lower), None)
    industry_col = next((lower[k] for k in ("gics sub-industry", "industry") if k in lower), None)
    output, seen = [], set()
    for _, row in table.iterrows():
        raw = str(row[symbol_col]).strip()
        ticker = normalize_yahoo_symbol(raw)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        output.append({"ticker": ticker, "company_name": str(row[name_col]) if name_col else ticker,
                       "sector": str(row[sector_col]) if sector_col and pd.notna(row[sector_col]) else "Unavailable",
                       "industry": str(row[industry_col]) if industry_col and pd.notna(row[industry_col]) else "Unavailable"})
    if len(output) < 80:
        raise RuntimeError(f"Constituent table unexpectedly small ({len(output)}); refusing to replace cached universe.")
    return output, url, datetime.now(timezone.utc)


class USUniverseManager:
    def __init__(self, cache):
        self.cache = cache

    def refresh(self, universe: str):
        constituents, source, timestamp = retrieve_constituents(universe)
        self.cache.save_universe(universe, constituents, source, timestamp)
        return constituents

    def get(self, universe: str, refresh: bool = False):
        if refresh:
            constituents = self.refresh(universe)
        else:
            constituents = self.cache.load_universe(universe)
            if not constituents:
                constituents = self.refresh(universe)
        return constituents, self.cache.universe_metadata(universe)

    def combined_us_large_cap(self, refresh: bool = False):
        sp, _ = self.get("S&P 500", refresh)
        ndx, _ = self.get("NASDAQ 100", refresh)
        merged = {row["ticker"]: row for row in sp}
        merged.update({row["ticker"]: row for row in ndx})
        return list(merged.values())
