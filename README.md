# YxStock — Personal Stock Analysis Platform

YxStock is a local Streamlit learning dashboard for US and Bursa Malaysia equities. It retrieves historical prices through `yfinance`, calculates common technical indicators with pandas, and stores successful downloads in a small SQLite cache. It does not place trades.

## Architecture

```text
Streamlit UI (app.py)
    ├── services/market_data.py  — symbol lookup and Yahoo Finance downloads
    ├── analysis/indicators.py   — EMA, RSI and MACD calculations
    └── storage/cache.py         — SQLite cache for downloaded OHLCV data
```

Keeping these responsibilities separate makes it possible to change the data provider or UI without rewriting the calculations. `tests/` contains focused unit tests for indicators and cache behavior.

## Folder structure

```text
app.py
src/yxstock/
  analysis/indicators.py
  services/market_data.py
  storage/cache.py
tests/
  test_indicators.py
  test_market_data.py
  test_cache.py
requirements.txt
```

## Install and run (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:PYTHONPATH = "src"
streamlit run app.py
```

On macOS/Linux, activate with `source .venv/bin/activate`, then run `PYTHONPATH=src streamlit run app.py`.

Search by ticker (for example `AAPL`, `MSFT`, `1155.KL` for Maybank, or `CIMB.KL`). Yahoo Finance commonly uses `.KL` for Bursa Malaysia symbols. Search is ticker-based; company-name search is not provided by the Yahoo Finance interface used here. A failed or unrecognized symbol is reported as unavailable rather than filled with synthetic prices.

The sidebar offers 1 month, 3 months, 6 months, 1 year, 2 years and 5 years. The default is 1 year. YxStock fetches an additional 370 calendar days before the selected range so indicators have enough historical observations to initialize. The chart shows only the selected range, while EMA/MACD/RSI calculations use the hidden warm-up rows too.

Data comes from Yahoo Finance and may be delayed; YxStock displays the provider, exchange, currency and local retrieval time. `.KL` is a Yahoo Finance convention for Bursa Malaysia, but symbol coverage and metadata depend on Yahoo. YxStock reports missing/invalid OHLCV rows and does not repair or fill them. A successful symbol lookup does not guarantee complete data or a particular delay level.

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Tests use deterministic local samples and mocked Yahoo responses for automated checks. A live provider check can be run by loading AAPL and `1155.KL` in the dashboard; provider availability may change. The application never uses test samples as market data.
