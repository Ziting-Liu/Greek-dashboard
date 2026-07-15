"""
Minimal Black-Scholes greeks.

yfinance option chains give price, implied volatility and open interest but
NOT greeks, so we derive delta/gamma ourselves from the quoted implied vol.
This is the standard approach used by most free "GEX" dashboards.
"""
import numpy as np
from scipy.stats import norm


def _d1_d2(spot, strike, t_years, rate, iv):
    if t_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return None, None
    d1 = (np.log(spot / strike) + (rate + 0.5 * iv ** 2) * t_years) / (iv * np.sqrt(t_years))
    d2 = d1 - iv * np.sqrt(t_years)
    return d1, d2


def gamma(spot, strike, t_years, rate, iv):
    """Gamma is the same formula for calls and puts."""
    d1, _ = _d1_d2(spot, strike, t_years, rate, iv)
    if d1 is None:
        return 0.0
    return norm.pdf(d1) / (spot * iv * np.sqrt(t_years))


def delta(spot, strike, t_years, rate, iv, option_type="call"):
    d1, _ = _d1_d2(spot, strike, t_years, rate, iv)
    if d1 is None:
        return 0.0
    if option_type == "call":
        return norm.cdf(d1)
    return norm.cdf(d1) - 1
