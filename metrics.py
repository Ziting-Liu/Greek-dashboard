"""
Metrics derived from a raw option chain: skew, open interest by strike,
gamma exposure (GEX), and a dealer-positioning read built on top of GEX.

Everything here is a widely-used *approximation*, not the proprietary
methodology behind paid products (e.g. SpotGamma, SqueezeMetrics). The two
big assumptions, spelled out because they drive the sign of every result:

  1. Dealers are net long calls and net short puts that customers hold
     (the standard "customers are net long options, dealers are the other
     side" assumption).
  2. All open interest is delta-hedged by dealers, so gamma exposure per
     contract = gamma * OI * 100 shares * spot^2 * 1%.
"""
import numpy as np
import pandas as pd

from .black_scholes import gamma as bs_gamma

CONTRACT_MULTIPLIER = 100


def atm_iv(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> float | None:
    """Average implied vol of the call and put closest to the money."""
    ivs = []
    for df in (calls, puts):
        if df.empty:
            continue
        idx = (df["strike"] - spot).abs().idxmin()
        iv = df.loc[idx, "impliedVolatility"]
        if iv and iv > 0:
            ivs.append(iv)
    return float(np.mean(ivs)) if ivs else None


def skew_25delta(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> dict:
    """25-delta skew: IV of the ~25-delta put minus IV of the ~25-delta call.
    Positive skew (the normal equity pattern) means downside puts are bid up
    relative to upside calls -- the market paying up for crash protection."""
    result = {"put_iv": None, "call_iv": None, "skew": None}
    if calls.empty or puts.empty:
        return result

    # Approximate 25-delta strikes without recomputing full BS deltas: use
    # ~10% OTM as a simple, transparent stand-in for the 25-delta point.
    put_target = spot * 0.90
    call_target = spot * 1.10

    put_row = puts.iloc[(puts["strike"] - put_target).abs().argsort()[:1]]
    call_row = calls.iloc[(calls["strike"] - call_target).abs().argsort()[:1]]

    if not put_row.empty and not call_row.empty:
        put_iv = float(put_row["impliedVolatility"].iloc[0])
        call_iv = float(call_row["impliedVolatility"].iloc[0])
        result["put_iv"] = put_iv
        result["call_iv"] = call_iv
        result["skew"] = put_iv - call_iv
    return result


def open_interest_by_strike(chain: pd.DataFrame) -> pd.DataFrame:
    if chain.empty:
        return chain
    grouped = (
        chain.groupby(["strike", "type"])["openInterest"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ("call", "put"):
        if col not in grouped.columns:
            grouped[col] = 0
    grouped["total"] = grouped["call"] + grouped["put"]
    return grouped.sort_values("strike")


def compute_gex(chain: pd.DataFrame, spot: float, rate: float) -> pd.DataFrame:
    """Per-contract-row GEX, signed by the dealer-positioning assumption
    above (long-gamma from calls, short-gamma from puts)."""
    if chain.empty:
        return chain

    rows = []
    for _, r in chain.iterrows():
        iv = r.get("impliedVolatility", np.nan)
        oi = r.get("openInterest", 0) or 0
        t_years = max(r.get("dte", 0), 0) / 365.0
        if not iv or iv <= 0 or oi <= 0 or t_years <= 0:
            continue
        g = bs_gamma(spot, r["strike"], t_years, rate, iv)
        notional_gamma = g * oi * CONTRACT_MULTIPLIER * (spot ** 2) * 0.01
        sign = 1 if r["type"] == "call" else -1
        rows.append(
            {
                "strike": r["strike"],
                "expiration": r["expiration"],
                "type": r["type"],
                "gamma": g,
                "openInterest": oi,
                "gex": sign * notional_gamma,
            }
        )
    return pd.DataFrame(rows)


def gex_by_strike(gex_df: pd.DataFrame) -> pd.DataFrame:
    if gex_df.empty:
        return gex_df
    return gex_df.groupby("strike", as_index=False)["gex"].sum().sort_values("strike")


def dealer_positioning_summary(gex_df: pd.DataFrame) -> dict:
    if gex_df.empty:
        return {"net_gex": 0.0, "regime": "unknown", "flip_strike": None}

    net_gex = gex_df["gex"].sum()
    by_strike = gex_by_strike(gex_df)

    # Zero-gamma / "flip" strike: where cumulative GEX crosses zero as you
    # sweep strikes from low to high. Common heuristic for the level where
    # dealer hedging behavior is expected to flip character.
    by_strike = by_strike.sort_values("strike").reset_index(drop=True)
    by_strike["cum_gex"] = by_strike["gex"].cumsum()
    flip_strike = None
    signs = np.sign(by_strike["cum_gex"])
    for i in range(1, len(signs)):
        if signs[i] != signs[i - 1] and signs[i - 1] != 0:
            flip_strike = float(by_strike["strike"].iloc[i])
            break

    if net_gex > 0:
        regime = "long_gamma"   # dealers likely buy dips / sell rips -> dampens realized moves
    elif net_gex < 0:
        regime = "short_gamma"  # dealers likely sell dips / buy rips -> amplifies realized moves
    else:
        regime = "flat"

    return {"net_gex": float(net_gex), "regime": regime, "flip_strike": flip_strike}
