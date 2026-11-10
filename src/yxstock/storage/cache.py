"""Small SQLite cache for historical daily OHLCV data."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd


class PriceCache:
    def __init__(self, database_path: str | Path = "yxstock.db") -> None:
        self.database_path = str(database_path)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS daily_prices (
                ticker TEXT NOT NULL, date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (ticker, date))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY, market TEXT NOT NULL, added_at TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS universe_constituents (
                universe TEXT NOT NULL, ticker TEXT NOT NULL, company_name TEXT,
                sector TEXT, industry TEXT, source_url TEXT NOT NULL, refreshed_at TEXT NOT NULL,
                PRIMARY KEY (universe, ticker))""")

    def save_universe(self, universe, constituents, source_url, refreshed_at) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM universe_constituents WHERE universe = ?", (universe,))
            connection.executemany(
                "INSERT INTO universe_constituents VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(universe, x['ticker'], x.get('company_name'), x.get('sector'), x.get('industry'),
                  source_url, refreshed_at.isoformat()) for x in constituents],
            )

    def load_universe(self, universe):
        with self._connect() as connection:
            rows = connection.execute("SELECT ticker, company_name, sector, industry FROM universe_constituents WHERE universe = ? ORDER BY ticker", (universe,)).fetchall()
        return [dict(zip(('ticker','company_name','sector','industry'), row)) for row in rows]

    def universe_metadata(self, universe):
        with self._connect() as connection:
            row = connection.execute("SELECT source_url, refreshed_at FROM universe_constituents WHERE universe = ? LIMIT 1", (universe,)).fetchone()
        return {'source_url': row[0], 'refreshed_at': row[1]} if row else None

    def get_watchlist(self) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker, market, added_at FROM watchlist ORDER BY ticker"
            ).fetchall()
        return [{"ticker": row[0], "market": row[1], "added_at": row[2]} for row in rows]

    def add_to_watchlist(self, ticker: str, market: str) -> bool:
        from datetime import datetime, timezone

        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO watchlist (ticker, market, added_at) VALUES (?, ?, ?)",
                (ticker.upper(), market, datetime.now(timezone.utc).isoformat()),
            )
        return cursor.rowcount == 1

    def remove_from_watchlist(self, ticker: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
        return cursor.rowcount == 1

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, ticker: str, prices: pd.DataFrame) -> None:
        if prices.empty:
            return
        rows = []
        for date, row in prices.iterrows():
            def value(name: str):
                item = row.get(name)
                return None if pd.isna(item) else float(item)
            rows.append((ticker.upper(), pd.Timestamp(date).isoformat(), value("Open"),
                         value("High"), value("Low"), value("Close"), value("Volume")))
        with self._connect() as connection:
            connection.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

    def load(self, ticker: str, start: pd.Timestamp | None = None) -> pd.DataFrame:
        query = "SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker = ?"
        params: list[object] = [ticker.upper()]
        if start is not None:
            query += " AND date >= ?"
            params.append(pd.Timestamp(start).isoformat())
        query += " ORDER BY date"
        with self._connect() as connection:
            frame = pd.read_sql_query(query, connection, params=params, parse_dates=["date"])
        if frame.empty:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        return frame.set_index("date").rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
