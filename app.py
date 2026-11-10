"""YxStock Streamlit dashboard."""

import plotly.graph_objects as go
import pandas as pd
import streamlit as st
from plotly.subplots import make_subplots

from yxstock.analysis.indicators import add_indicators
from yxstock.services.market_data import MarketDataError, PERIODS, fetch_history, normalize_ticker
from yxstock.services.watchlist import INITIAL_WATCHLIST, fetch_watchlist_quotes, validate_watchlist_ticker
from yxstock.services.screener import ScreenConfig, STRATEGIES, screen_universe
from yxstock.services.universes import USUniverseManager
from yxstock.storage.cache import PriceCache

st.set_page_config(page_title="YxStock | Stock Analysis", page_icon="📈", layout="wide")
st.markdown("""
<style>
.stApp { background: #070d18; color: #e6edf7; }
[data-testid="stHeader"] { background: rgba(7,13,24,.96); }
[data-testid="stSidebar"] { background: #0a1322; border-right: 1px solid #20334b; }
[data-testid="stMetric"] { background: #111e30; border: 1px solid #233a54; padding: 14px; border-radius: 12px; }
.terminal-card { background: #111e30; border: 1px solid #233a54; border-radius: 14px; padding: 18px; margin: 4px 0 12px; }
.terminal-muted { color: #8fa6bf; font-size: .88rem; }
div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stMetric"]) { gap: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("📈 YxStock")
st.caption("Personal stock analysis · Historical data and technical indicators · No trade execution")

cache = PriceCache()
PAGES = ["Dashboard", "Watchlist", "Stock Analysis", "Stock Screener", "Portfolio", "Trading Journal", "Settings"]
if "page" not in st.session_state: st.session_state.page = "Dashboard"
with st.sidebar:
    st.markdown("## ◈ YxStock")
    st.caption("TRADING TERMINAL")
    st.session_state.page = st.radio("Navigation", PAGES, index=PAGES.index(st.session_state.page), key="page_selector")
    st.divider()
    st.caption("Yahoo Finance · Daily historical data · May be delayed")

if st.session_state.page == "Stock Screener":
    st.header("Stock Screener")
    st.caption("Completed daily sessions · Yahoo Finance history · Signals are research filters, not recommendations")
    universe_manager = USUniverseManager(cache)
    universe_choice = st.selectbox("Stock universe", ["S&P 500", "NASDAQ 100", "Combined US Large Cap", "My Watchlist", "Custom Universe"])
    if universe_choice in ("S&P 500", "NASDAQ 100", "Combined US Large Cap"):
        refresh_universe = st.button("Refresh constituent list")
        try:
            if universe_choice == "Combined US Large Cap":
                constituents = universe_manager.combined_us_large_cap(refresh_universe)
                metadata = {"source_url": "S&P 500 + NASDAQ 100 cached constituent pages", "refreshed_at": "see each cached source"}
            else:
                constituents, metadata = universe_manager.get(universe_choice, refresh_universe)
            st.caption(f"{len(constituents)} cached constituents · Source: {metadata.get('source_url','unavailable')} · Refreshed: {metadata.get('refreshed_at','unknown')}")
            universe_default = [x['ticker'] for x in constituents]
        except Exception as exc:
            st.error(f"Constituent retrieval failed; cached list was retained when available: {exc}")
            universe_default = []
    elif universe_choice == "My Watchlist":
        universe_default = [x["ticker"] for x in cache.get_watchlist()]
    else:
        universe_default = []
    with st.form("terminal_screener"):
        symbols = st.text_area("Selected universe symbols (editable, comma separated)", ",".join(universe_default), height=100)
        strategy = st.selectbox("Strategy", ["All strategies"] + STRATEGIES)
        a, b, c = st.columns(3)
        min_rsi = a.number_input("Minimum RSI", 0., 100., 0.)
        max_rsi = b.number_input("Maximum RSI", 0., 100., 100.)
        relvol = c.number_input("Relative volume minimum", 0., 20., 0., step=.1)
        a, b, c = st.columns(3)
        min_cap = a.number_input("Minimum market cap (provider currency)", 0., 1e13, 0., step=1e8)
        fast = b.selectbox("Fast EMA", [20, 50], index=1)
        slow = c.selectbox("Slow EMA", [100, 200], index=1)
        batch_size = st.select_slider("Batch size", options=[10, 25, 50, 75, 100], value=50)
        exchange = st.text_input("Exchange contains (optional)", "")
        currency = st.selectbox("Currency", ["Any", "USD", "MYR"])
        run_screen = st.form_submit_button("Run Screener", type="primary")
    if run_screen:
        try:
            universe = list(dict.fromkeys(x.strip().upper() for x in symbols.split(",") if x.strip()))
            if len(universe) > 1000: st.error("Limit the request to 1,000 symbols.")
            elif min_rsi > max_rsi: st.error("Minimum RSI cannot exceed maximum RSI.")
            else:
                config = ScreenConfig(universe, strategy, min_rsi, max_rsi, relvol, min_cap, fast, slow, exchange or "Any", currency, batch_size)
                with st.spinner("Screening completed sessions…"):
                    rows, report = screen_universe(config)
                st.session_state.screen_rows, st.session_state.screen_report = rows, report
        except Exception as exc: st.error(f"Screener failed: {exc}")
    if "screen_rows" in st.session_state:
        rows = st.session_state.screen_rows
        report=st.session_state.screen_report
        st.caption(f"{report['status'].upper()} scan · Constituents {report['total']} · Eligible {report['eligible']} · Scanned {report['success']} · Failed {len(report['failed'])} · Insufficient {len(report['insufficient'])} · Matches {report['matching']} · {report.get('duration_seconds',0):.1f}s · Retrieved {report['completed_at'].astimezone().strftime('%Y-%m-%d %H:%M %Z')} · historical, may be delayed")
        if report['failed']:
            with st.expander(f"Failed tickers ({len(report['failed'])})"):
                st.dataframe(pd.DataFrame(report['failed']), hide_index=True, width='stretch')
        if report['insufficient']:
            with st.expander(f"Insufficient data ({len(report['insufficient'])})"):
                st.dataframe(pd.DataFrame(report['insufficient']), hide_index=True, width='stretch')
        if rows:
            result_frame = pd.DataFrame(rows)
            sort_key = st.selectbox("Sort results", ["Ticker", "Daily change %", "RSI", "Relative volume", "Market cap"])
            st.dataframe(result_frame.sort_values(sort_key, ascending=sort_key == "Ticker", na_position="last"), hide_index=True, width="stretch", height=450)
            selected_result = st.selectbox("Open analysis for result", result_frame.Ticker.tolist())
            if st.button("Open selected analysis"):
                st.session_state.analysis_symbol=selected_result; st.session_state.page="Stock Analysis"; st.rerun()
        else: st.info("No symbols matched. Unsupported or unavailable symbols are omitted, not fabricated.")
    st.markdown("**Oversold Recovery** · close > EMA200, RSI crosses above 30, relative volume > 1.5, market cap threshold")
    st.markdown("**Trend Following** · close > EMA200, EMA20 > EMA50 > EMA200, RSI 50–70, relative volume > 1.2")
    st.markdown("**Breakout** · close > prior 20-session high, EMA50 > EMA200, RSI 55–75, relative volume > 2.0")
    st.caption("Results distinguish Strategy Match, Trend Structure, and Overextension Risk. Warnings are informational, not sell signals; matches are research filters, not buy recommendations.")
    st.stop()

if st.session_state.page in ("Portfolio", "Trading Journal", "Settings"):
    st.header(st.session_state.page)
    st.info("Coming Soon · Not implemented yet.")
    st.stop()

if not st.session_state.get("watchlist_initialized"):
    for initial_symbol in INITIAL_WATCHLIST:
        try:
            symbol, market = validate_watchlist_ticker(initial_symbol)
            cache.add_to_watchlist(symbol, market)
        except ValueError:
            pass
    st.session_state.watchlist_initialized = True

if st.session_state.page in ("Dashboard", "Watchlist"):
    st.header("Your Watchlist" if st.session_state.page == "Dashboard" else "Manage Watchlist")
    st.caption("Daily historical closes from Yahoo Finance. Quotes may be delayed; these are not real-time prices.")
    with st.form("add_watchlist", clear_on_submit=True):
        new_symbol = st.text_input("Add ticker", placeholder="AAPL or 1155.KL")
        submitted = st.form_submit_button("Add to watchlist", type="primary")
    if submitted:
        try:
            symbol, market = validate_watchlist_ticker(new_symbol)
            if cache.add_to_watchlist(symbol, market):
                st.success(f"Added {symbol}.")
            else:
                st.info(f"{symbol} is already in the watchlist.")
        except ValueError as exc:
            st.error(str(exc))

    saved = cache.get_watchlist()
    if saved:
        with st.spinner("Loading batched daily market data…"):
            quote_data = fetch_watchlist_quotes([item["ticker"] for item in saved])
        rows = []
        for item in saved:
            quote = quote_data.get(item["ticker"], {"error": "No result returned."})
            if "error" in quote:
                rows.append({"Ticker": item["ticker"], "Company": "Unavailable", "Market": quote.get("market", item["market"]), "Currency": "Unavailable", "Latest close": None, "Previous close": None, "Daily change %": None, "Volume": None, "RSI (14)": None, "EMA 20": None, "EMA 50": None, "Data status": f"Unavailable: {quote['error']}", "Source": "Yahoo Finance", "Last updated": "Unavailable"})
                continue
            rows.append({"Ticker": quote["ticker"], "Company": quote["company_name"], "Market": quote["market"], "Currency": quote["currency"], "Latest close": quote["latest_close"], "Previous close": quote["previous_close"], "Daily change %": quote["daily_change_pct"], "Volume": quote["volume"], "RSI (14)": quote["rsi_14"], "EMA 20": quote["ema_20"], "EMA 50": quote["ema_50"], "Data status": f"Last session: {quote['last_session'].date()}", "Source": quote["source"], "Last updated": quote["updated_at"].astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")})
        frame = pd.DataFrame(rows)
        sort_by = st.selectbox("Sort by", ["Ticker", "Daily change %", "RSI (14)"])
        frame = frame.sort_values(sort_by, ascending=(sort_by == "Ticker"), na_position="last")
        def color_change(value):
            if not isinstance(value, (float, int)):
                return ""
            return "color: #22c55e" if value > 0 else "color: #ef4444" if value < 0 else ""
        if st.session_state.page == "Dashboard":
            valid = [q for q in quote_data.values() if "error" not in q]
            summary = st.columns(4)
            summary[0].metric("Advancing", sum(q["daily_change_pct"] > 0 for q in valid))
            summary[1].metric("Declining", sum(q["daily_change_pct"] < 0 for q in valid))
            summary[2].metric("High volume", sum(q["volume"] > 0 for q in valid))
            summary[3].metric("Tracked", len(saved))
            cards = st.columns(3)
            for idx, q in enumerate(quote_data.values()):
                with cards[idx % 3]:
                    if "error" in q:
                        st.markdown(f'<div class="terminal-card"><b>{q.get("ticker", "Unknown")}</b><p class="terminal-muted">Unavailable · {q["error"]}</p></div>', unsafe_allow_html=True)
                    else:
                        cls = "#29c995" if q["daily_change_pct"] >= 0 else "#ff5577"
                        st.markdown(f'<div class="terminal-card"><div class="terminal-muted">{q["ticker"]} · {q["currency"]}</div><h3>{q["company_name"]}</h3><h2>{q["latest_close"]:,.2f}</h2><b style="color:{cls}">{q["daily_change_pct"]:+.2f}%</b><p class="terminal-muted">Volume {q["volume"]:,.0f} · RSI {q["rsi_14"] if q["rsi_14"] is not None else "N/A"}</p><p class="terminal-muted">Daily historical close · may be delayed</p></div>', unsafe_allow_html=True)
                        if st.button("Open analysis", key=f"dash_{q['ticker']}"):
                            st.session_state.analysis_symbol=q["ticker"]; st.session_state.page="Stock Analysis"; st.rerun()
        else:
            st.dataframe(frame.style.map(color_change, subset=["Daily change %"]), hide_index=True, width="stretch", height=420)
        st.markdown("**Open stock analysis**")
        analysis_choice = st.selectbox("Ticker", [item["ticker"] for item in saved], key="analysis_ticker")
        if st.button("Open Stock Analysis"):
            st.session_state.analysis_symbol = analysis_choice
            st.session_state.page = "Stock Analysis"
            st.rerun()
        with st.expander("Remove a stock"):
            remove_choice = st.selectbox("Ticker to remove", [item["ticker"] for item in saved], key="remove_ticker")
            if st.button("Remove from watchlist"):
                cache.remove_from_watchlist(remove_choice)
                st.rerun()
    else:
        st.info("Your watchlist is empty. Add a US or Bursa ticker above.")
    st.stop()

with st.sidebar:
    st.header("Market data")
    symbol_input = st.text_input("Ticker symbol", value=st.session_state.get("analysis_symbol", "AAPL"), help="US: AAPL · Bursa Malaysia: 1155.KL, CIMB.KL (availability varies by symbol)")
    period_label = st.selectbox("History period", list(PERIODS.keys()), index=3)
    refresh = st.button("Load / refresh data", type="primary", width="stretch")
    st.caption("Search by ticker symbol. Yahoo Finance commonly uses .KL for Bursa Malaysia; coverage varies by listing.")

if "market_data" not in st.session_state or refresh:
    try:
        requested = normalize_ticker(symbol_input)
        with st.spinner(f"Loading {requested} historical data…"):
            data = fetch_history(requested, period_label)
            # Store successfully retrieved observations locally; the live provider remains authoritative.
            try:
                PriceCache().save(data.ticker, data.prices)
            except Exception as cache_error:
                st.warning(f"Market data loaded, but the local cache could not be updated: {cache_error}")
        st.session_state.market_data = data
        st.session_state.request_key = (requested, period_label)
    except (ValueError, MarketDataError) as exc:
        st.session_state.pop("market_data", None)
        st.error(str(exc))
    except Exception as exc:
        st.session_state.pop("market_data", None)
        st.error(f"Unexpected problem while loading market data: {exc}")

data = st.session_state.get("market_data")
current_key = None
try:
    current_key = (normalize_ticker(symbol_input), period_label)
except ValueError:
    pass
if data is not None and st.session_state.get("request_key") != current_key:
    st.info("The sidebar ticker or period changed. Select **Load / refresh data** to update the dashboard.")
elif data is not None:
    # Calculate indicators using the pre-period warm-up, then clip to the requested chart window.
    all_indicators = add_indicators(data.prices)
    prices = all_indicators.loc[all_indicators.index >= data.chart_start].copy()
    st.subheader(f"{data.company_name}  ·  {data.ticker}")
    retrieved_local = data.retrieved_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
    st.caption(f"Exchange: {data.exchange}  ·  Currency: {data.currency}  ·  Source: {data.source}  ·  Retrieved: {retrieved_local}  ·  {data.delayed_notice}")
    st.info("Market quotes may be delayed. Missing provider data is shown as unavailable; YxStock does not estimate or fabricate prices.")

    valid_close = prices["Close"].dropna()
    latest = valid_close.iloc[-1]
    prior = valid_close.iloc[-2] if len(valid_close) > 1 else None
    change = ((latest / prior) - 1) * 100 if prior else None
    metrics = st.columns(4)
    metrics[0].metric("Latest close", f"{latest:,.2f}", f"{change:+.2f}%" if change is not None else None)
    rsi = prices["RSI_14"].dropna()
    metrics[1].metric("RSI (14)", f"{rsi.iloc[-1]:.1f}" if not rsi.empty else "Not enough data")
    vol = prices["Volume"].dropna()
    metrics[2].metric("Latest volume", f"{vol.iloc[-1]:,.0f}" if not vol.empty else "Unavailable")
    metrics[3].metric("Observations", f"{len(prices):,}")
    if data.warmup_observations < 200:
        st.warning(f"Only {data.warmup_observations} pre-period observations were available. EMA 200 may be unavailable until enough observations accumulate.")
    if prices["EMA_200"].notna().sum() == 0:
        st.warning("EMA 200 is unavailable: there are not enough valid historical observations in the selected range plus warm-up data.")
    if prices["RSI_14"].notna().sum() == 0:
        st.warning("RSI 14 is unavailable: there are not enough consecutive valid price changes.")

    st.markdown("**Chart indicators**")
    indicator_cols = st.columns(5)
    show_ema20 = indicator_cols[0].checkbox("EMA 20", value=True)
    show_ema50 = indicator_cols[1].checkbox("EMA 50", value=True)
    show_ema200 = indicator_cols[2].checkbox("EMA 200", value=True)
    show_rsi = indicator_cols[3].checkbox("RSI 14", value=True)
    show_macd = indicator_cols[4].checkbox("MACD", value=True)

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.035,
                        row_heights=[0.54, 0.16, 0.15, 0.15],
                        subplot_titles=("Price and moving averages", "Volume", "RSI (14)", "MACD (12, 26, 9)"))
    fig.add_trace(go.Candlestick(x=prices.index, open=prices.Open, high=prices.High, low=prices.Low, close=prices.Close,
                                 name="OHLC", increasing_line_color="#22c55e", decreasing_line_color="#ef4444"), row=1, col=1)
    for period, color, visible in ((20, "#f59e0b", show_ema20), (50, "#38bdf8", show_ema50), (200, "#c084fc", show_ema200)):
        fig.add_trace(go.Scatter(x=prices.index, y=prices[f"EMA_{period}"], mode="lines", name=f"EMA {period}",
                                 line={"color": color, "width": 1.4}, visible=visible), row=1, col=1)
    fig.add_trace(go.Bar(x=prices.index, y=prices.Volume, name="Volume", marker_color="#64748b"), row=2, col=1)
    fig.add_trace(go.Scatter(x=prices.index, y=prices.RSI_14, name="RSI 14", line={"color": "#e879f9", "width": 1.5}, visible=show_rsi), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ef4444", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#22c55e", row=3, col=1)
    fig.add_trace(go.Bar(x=prices.index, y=prices.MACD_histogram, name="MACD histogram", marker_color="#64748b", visible=show_macd), row=4, col=1)
    fig.add_trace(go.Scatter(x=prices.index, y=prices.MACD, name="MACD", line={"color": "#38bdf8", "width": 1.4}, visible=show_macd), row=4, col=1)
    fig.add_trace(go.Scatter(x=prices.index, y=prices.MACD_signal, name="Signal", line={"color": "#f59e0b", "width": 1.4}, visible=show_macd), row=4, col=1)
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0b1120", plot_bgcolor="#0b1120", height=900,
                      autosize=True, margin={"l": 15, "r": 15, "t": 95, "b": 15},
                      legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0,
                              "tracegroupgap": 8, "entrywidth": 100, "entrywidthmode": "pixels"},
                      xaxis_rangeslider_visible=False, hovermode="x unified")
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Shares", row=2, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)
    st.plotly_chart(fig, width="stretch", config={"responsive": True, "displaylogo": False},
                    alt=f"Candlestick and technical indicator charts for {data.ticker}")
    with st.expander("View latest data rows"):
        st.dataframe(prices.tail(15).sort_index(ascending=False), width="stretch")
    st.caption("EMA means exponential moving average. RSI summarizes recent momentum on a 0–100 scale. MACD compares two moving averages; these indicators describe past prices and do not predict future returns.")
elif "market_data" not in st.session_state:
    st.write("Enter a ticker and load historical market data to begin.")
