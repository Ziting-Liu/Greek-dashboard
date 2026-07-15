"""
Earnings calendar comes straight from yfinance. Macro events (FOMC, CPI,
jobs report) don't have a good free real-time API, so FOMC meeting dates
are hardcoded from the Federal Reserve's published schedule (these are
announced a year or more in advance) and CPI/NFP are approximated by their
usual release rhythm. Update FOMC_DATES when the Fed publishes a new year.
Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
"""
import datetime as dt

import pandas as pd

FOMC_DATES = [
    # 2026 schedule (decision/press-conference day, second day of the meeting)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    # 2027 tentative schedule
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
]


def upcoming_fomc_dates(n: int = 4) -> pd.DataFrame:
    today = dt.date.today()
    dates = [dt.datetime.strptime(d, "%Y-%m-%d").date() for d in FOMC_DATES]
    upcoming = sorted(d for d in dates if d >= today)[:n]
    return pd.DataFrame({"date": upcoming, "event": "FOMC rate decision"})


def approx_cpi_release(n: int = 3) -> pd.DataFrame:
    """CPI is released roughly monthly, typically the second week of the
    month. This gives a rough placeholder date, not an official one --
    always confirm against bls.gov before trading around it."""
    today = dt.date.today()
    out = []
    cursor = today.replace(day=1)
    while len(out) < n:
        candidate = cursor + dt.timedelta(days=12)  # rough "second week" placeholder
        if candidate >= today:
            out.append(candidate)
        # advance to next month
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return pd.DataFrame({"date": out, "event": "CPI release (approx., confirm on bls.gov)"})


def approx_nfp_release(n: int = 3) -> pd.DataFrame:
    """Nonfarm payrolls: first Friday of the month, approximately."""
    today = dt.date.today()
    out = []
    year, month = today.year, today.month
    while len(out) < n:
        d = dt.date(year, month, 1)
        while d.weekday() != 4:  # Friday
            d += dt.timedelta(days=1)
        if d >= today:
            out.append(d)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return pd.DataFrame({"date": out, "event": "Nonfarm payrolls (approx.)"})


def macro_calendar(n: int = 4) -> pd.DataFrame:
    df = pd.concat(
        [upcoming_fomc_dates(n), approx_cpi_release(n), approx_nfp_release(n)],
        ignore_index=True,
    )
    return df.sort_values("date").reset_index(drop=True)
