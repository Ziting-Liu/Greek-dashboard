import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import calendar_data, data_fetch, metrics

st.set_page_config(page_title="Options Dashboard", layout="wide")

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.title("Settings")
symbol = st.sidebar.text_input("Ticker", value="AAPL").strip().upper()
num_expirations = st.sidebar.slider("Expirations to include", 1, 8, 4)
risk_free_rate = st.sidebar.number_input(
    "Risk-free rate (for gamma calc)", value=data_fetch.RISK_FREE_RATE, step=0.005, format="%.3f"
)
st.sidebar.caption(
    "Data source: Yahoo Finance via yfinance (free, unofficial, ~15 min delayed). "
    "Not investment advice."
)

if not symbol:
    st.stop()

# ---------------------------------------------------------------------------
# Pull data
# ---------------------------------------------------------------------------
with st.spinner(f"Loading data for {symbol}..."):
    try:
        tkr = data_fetch.get_ticker(symbol)
        spot = data_fetch.get_spot_price(tkr)
        expirations = data_fetch.get_expirations(tkr)
    except Exception as e:
        st.error(f"Couldn't load data for {symbol}: {e}")
        st.stop()

if not expirations:
    st.error(f"No options chain found for {symbol}.")
    st.stop()

chosen_expirations = expirations[:num_expirations]
full_chain = data_fetch.get_all_chains(tkr, chosen_expirations)
nearest_calls, nearest_puts = data_fetch.get_option_chain(tkr, expirations[0])

st.title(f"{symbol} Options Dashboard")
st.caption(f"Spot price: ${spot:,.2f}  |  As of {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")

tab_vol, tab_positioning, tab_calendar = st.tabs(
    ["Volatility (IV Rank / Percentile / Skew)", "Positioning (OI / GEX / Dealers)", "Calendar (Earnings / Macro)"]
)

# ---------------------------------------------------------------------------
# Tab 1: Volatility
# ---------------------------------------------------------------------------
with tab_vol:
    current_atm_iv = metrics.atm_iv(nearest_calls, nearest_puts, spot)

    if current_atm_iv is not None:
        data_fetch.record_iv_snapshot(symbol, current_atm_iv)
        history = data_fetch.load_iv_history(symbol)
        iv_rank, iv_percentile = data_fetch.iv_rank_and_percentile(history, current_atm_iv)
    else:
        history, iv_rank, iv_percentile = pd.DataFrame(), None, None

    col1, col2, col3 = st.columns(3)
    col1.metric("ATM Implied Vol (nearest expiry)", f"{current_atm_iv:.1%}" if current_atm_iv else "n/a")

    if iv_rank is not None:
        col2.metric("IV Rank", f"{iv_rank:.0f}")
        col3.metric("IV Percentile", f"{iv_percentile:.0f}")
    else:
        col2.metric("IV Rank", "building history...")
        col3.metric("IV Percentile", "building history...")

    if len(history) < 20:
        st.info(
            f"IV Rank/Percentile need a history of daily IV readings, which Yahoo Finance doesn't "
            f"provide historically. This app builds its own by snapshotting the ATM IV each time it "
            f"runs -- it has {len(history)} day(s) recorded for {symbol} so far. Run it daily (or "
            f"schedule it) for a couple of months to get a meaningful rank/percentile. Until then, "
            f"the numbers above are placeholders."
        )

    if not history.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=history["date"], y=history["atm_iv"], mode="lines+markers", name="ATM IV"))
        fig.update_layout(title="Recorded ATM IV history (this app's own cache)", yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Skew (25-delta proxy)")
    skew = metrics.skew_25delta(nearest_calls, nearest_puts, spot)
    if skew["skew"] is not None:
        c1, c2, c3 = st.columns(3)
        c1.metric("~25∆ Put IV", f"{skew['put_iv']:.1%}")
        c2.metric("~25∆ Call IV", f"{skew['call_iv']:.1%}")
        c3.metric("Put − Call Skew", f"{skew['skew']*100:+.1f} pts")
        st.caption(
            "Positive skew = downside puts priced richer than upside calls (normal equity pattern, "
            "market paying for crash protection). Strikes are chosen at ~10% OTM as a simple stand-in "
            "for true 25-delta strikes."
        )
    else:
        st.write("Not enough chain data to compute skew.")

# ---------------------------------------------------------------------------
# Tab 2: Positioning
# ---------------------------------------------------------------------------
with tab_positioning:
    st.subheader("Open Interest by Strike (nearest expiry)")
    oi_table = metrics.open_interest_by_strike(pd.concat([nearest_calls, nearest_puts], ignore_index=True))
    if not oi_table.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=oi_table["strike"], y=oi_table["call"], name="Call OI"))
        fig.add_trace(go.Bar(x=oi_table["strike"], y=-oi_table["put"], name="Put OI"))
        fig.add_vline(x=spot, line_dash="dash", annotation_text="Spot")
        fig.update_layout(barmode="relative", title="Open Interest (puts shown negative)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.write("No open interest data available.")

    st.subheader(f"Gamma Exposure (GEX) across {len(chosen_expirations)} expirations")
    gex_df = metrics.compute_gex(full_chain, spot, risk_free_rate)
    if not gex_df.empty:
        by_strike = metrics.gex_by_strike(gex_df)
        summary = metrics.dealer_positioning_summary(gex_df)

        c1, c2, c3 = st.columns(3)
        c1.metric("Net GEX ($ per 1% move)", f"{summary['net_gex']:,.0f}")
        c2.metric("Dealer regime (heuristic)", summary["regime"].replace("_", " ").title())
        c3.metric("Estimated flip strike", f"${summary['flip_strike']:.0f}" if summary["flip_strike"] else "n/a")

        fig = go.Figure()
        colors = ["green" if v >= 0 else "red" for v in by_strike["gex"]]
        fig.add_trace(go.Bar(x=by_strike["strike"], y=by_strike["gex"], marker_color=colors, name="GEX"))
        fig.add_vline(x=spot, line_dash="dash", annotation_text="Spot")
        if summary["flip_strike"]:
            fig.add_vline(x=summary["flip_strike"], line_dash="dot", line_color="orange", annotation_text="Flip")
        fig.update_layout(title="Gamma Exposure by Strike")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(
            """
**How to read this (approximation, not the proprietary SpotGamma/SqueezeMetrics methodology):**
- **Long gamma / positive net GEX** → dealers are assumed to hedge by buying dips and selling rallies,
  which tends to dampen realized volatility.
- **Short gamma / negative net GEX** → dealers are assumed to hedge by selling dips and buying rallies,
  which tends to amplify realized volatility.
- **Flip strike** is where cumulative GEX crosses zero moving up the strike ladder — a rough estimate
  of the level where dealer hedging behavior may change character.
- Assumes dealers are net long calls / net short puts against customer flow, and that all open
  interest is delta-hedged. Real dealer books are not fully known publicly — treat this as directional
  context, not a precise measurement.
"""
        )
    else:
        st.write("Not enough data (missing IV or open interest) to compute GEX.")

# ---------------------------------------------------------------------------
# Tab 3: Calendar
# ---------------------------------------------------------------------------
with tab_calendar:
    st.subheader("Earnings Calendar")
    earnings = data_fetch.get_earnings_dates(tkr, symbol)
    if not earnings.empty:
        st.dataframe(earnings, use_container_width=True, hide_index=True)
    else:
        st.write("No earnings date data available from Yahoo Finance for this ticker.")

    st.subheader("Macro Events")
    macro = calendar_data.macro_calendar(n=4)
    st.dataframe(macro, use_container_width=True, hide_index=True)
    st.caption(
        "FOMC dates come from the Fed's published schedule. CPI and payrolls dates are rough "
        "placeholders based on typical release timing -- always confirm exact dates on bls.gov "
        "before trading around them."
    )

st.divider()
st.caption(
    "Educational tool built on free, delayed data. Nothing here is financial advice or a "
    "recommendation to buy or sell any security."
)
