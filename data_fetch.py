"""
All external data access lives here. Everything is built on yfinance, which
is free but unofficial -- treat every number as "close enough for a
dashboard", not as a broker-grade quote.
"""
import os
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

RISK_FREE_RATE = 0.045  # rough proxy for a short-dated T-bill rate; adjust as needed


def get_ticker(symbol: str) -> yf.Ticker:
    return yf.Ticker(symbol)


def get_spot_price(tkr: yf.Ticker) -> float:
    fast = tkr.fast_info
    price = fast.get("lastPrice") or fast.get("last_price")
    if price is None:
        hist = tkr.history(period="1d")
        price = float(hist["Close"].iloc[-1])
    return float(price)


def get_expirations(tkr: yf.Ticker) -> list[str]:
    try:
        return list(tkr.options)
    except Exception:
        return []


def get_option_chain(tkr: yf.Ticker, expiration: str):
    chain = tkr.option_chain(expiration)
    calls = chain.calls.copy()
    puts = chain.puts.copy()
    calls["type"] = "call"
    puts["type"] = "put"
    return calls, puts


def get_all_chains(tkr: yf.Ticker, expirations: list[str]) -> pd.DataFrame:
    """Pull and concatenate chains for several expirations, tagging each
    with days-to-expiry so downstream code can price greeks."""
    frames = []
    today = dt.date.today()
    for exp in expirations:
        try:
            calls, puts = get_option_chain(tkr, exp)
        except Exception:
            continue
        exp_date = dt.datetime.strptime(exp, "%Y-%m-%d").date()
        dte = max((exp_date - today).days, 0)
        for df in (calls, puts):
            df["expiration"] = exp
            df["dte"] = dte
        frames.append(pd.concat([calls, puts], ignore_index=True))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def get_earnings_dates(tkr: yf.Ticker, symbol: str) -> pd.DataFrame:
    try:
        df = tkr.get_earnings_dates(limit=8)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.reset_index().rename(columns={"Earnings Date": "date"})
        return df
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Local IV history cache -- yfinance has no endpoint for historical implied
# vol, so IV Rank / IV Percentile are only meaningful once this dashboard has
# been run repeatedly over time and built up its own snapshots. Each call
# appends "today's" ATM IV; percentile/rank are computed against that history.
# ---------------------------------------------------------------------------
def _history_path(symbol: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol.upper()}_iv_history.csv")


def record_iv_snapshot(symbol: str, atm_iv: float):
    path = _history_path(symbol)
    today = dt.date.today().isoformat()
    row = pd.DataFrame([{"date": today, "atm_iv": atm_iv}])
    if os.path.exists(path):
        existing = pd.read_csv(path)
        existing = existing[existing["date"] != today]  # keep one row/day
        combined = pd.concat([existing, row], ignore_index=True)
    else:
        combined = row
    combined.to_csv(path, index=False)


def load_iv_history(symbol: str) -> pd.DataFrame:
    path = _history_path(symbol)
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=["date", "atm_iv"])


def iv_rank_and_percentile(history: pd.DataFrame, current_iv: float):
    """IV Rank: where current IV sits between the min and max of the lookback
    window. IV Percentile: % of days in the window with IV below current."""
    if history.empty:
        return None, None
    values = history["atm_iv"].dropna().values
    if len(values) < 2:
        return None, None
    lo, hi = values.min(), values.max()
    iv_rank = 100 * (current_iv - lo) / (hi - lo) if hi > lo else 50.0
    iv_percentile = 100 * (values < current_iv).sum() / len(values)
    return float(iv_rank), float(iv_percentile)


def realized_vol_proxy(tkr: yf.Ticker, lookback_days: int = 252) -> pd.Series:
    """Rolling 20-day realized vol, used only as a fallback context series
    when we don't yet have enough recorded IV snapshots for a real rank."""
    hist = tkr.history(period=f"{lookback_days + 30}d")
    if hist.empty:
        return pd.Series(dtype=float)
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1))
    rv = log_ret.rolling(20).std() * np.sqrt(252)
    return rv.dropna()


def realized_vol_rank_and_percentile(tkr: yf.Ticker, current_iv: float, lookback_days: int = 252):
    """Fallback rank/percentile using a year of realized (historical) vol as
    the comparison window, since yfinance has years of price history but zero
    IV history. This is NOT the same thing as a true IV Rank/Percentile --
    realized vol and implied vol usually differ, sometimes by a lot -- but it
    gives an immediately-usable number instead of "building history" for
    weeks while real IV snapshots accumulate."""
    rv_series = realized_vol_proxy(tkr, lookback_days)
    if rv_series.empty or current_iv is None:
        return None, None
    values = rv_series.values
    lo, hi = values.min(), values.max()
    rank = 100 * (current_iv - lo) / (hi - lo) if hi > lo else 50.0
    percentile = 100 * (values < current_iv).sum() / len(values)
    # Clip: current IV can sit outside the realized-vol range entirely
    # (implied vol usually runs a bit above realized), so rank can go
    # slightly below 0 or above 100 -- clip for a sane display.
    rank = float(np.clip(rank, 0, 100))
    return rank, float(percentile)
