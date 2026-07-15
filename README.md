# Options Dashboard

A Streamlit dashboard for a single ticker's options market, covering:

- **IV Rank / IV Percentile** — built from a self-updating history (see caveat below)
- **Skew** — 25-delta-proxy put IV vs call IV
- **Open Interest** by strike
- **Gamma Exposure (GEX)** by strike, plus net GEX
- **Dealer Positioning** — a long/short-gamma read derived from GEX
- **Earnings Calendar** — next reported/estimated earnings dates
- **Macro Events** — FOMC meeting dates (official schedule) + approximate CPI/NFP dates

All data comes from [yfinance](https://github.com/ranaroussi/yfinance) (free,
unofficial, delayed Yahoo Finance data). This is a learning/monitoring tool,
not a trading signal generator, and nothing it shows is financial advice.

## Important caveat on IV Rank / IV Percentile

Yahoo Finance (and yfinance) does not expose historical implied volatility.
IV Rank and IV Percentile are only meaningful relative to a history of past
IV readings, so this app builds its **own** history: every time it loads a
ticker, it snapshots that day's ATM implied vol into `data/<TICKER>_iv_history.csv`.
The rank/percentile shown will say "building history" until there are a
few weeks of snapshots. If you deploy this so it's opened regularly (or add
a scheduled job that pings it daily), the numbers become meaningful over
time. If you have access to a proper IV history source (e.g. a paid data
vendor), swap `load_iv_history` / `record_iv_snapshot` in
`utils/data_fetch.py` for calls to that API instead.

## Project structure

```
app.py                     Streamlit app / UI
utils/data_fetch.py         yfinance wrappers + local IV history cache
utils/black_scholes.py       Gamma/delta calc (yfinance chains don't include greeks)
utils/metrics.py            Skew, open interest, GEX, dealer-positioning heuristic
utils/calendar_data.py      FOMC dates + approximate CPI/NFP dates + earnings wrapper
requirements.txt
.streamlit/config.toml      Basic theme
```

## Run locally

```bash
git clone <this-repo-url>
cd options-dashboard
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).

## Deploy for free on Streamlit Community Cloud

1. Push this folder to a **public GitHub repo** (private repos work too if
   your Streamlit Cloud account supports them).
   ```bash
   git init
   git add .
   git commit -m "Initial options dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **"New app"**, pick your repo/branch, and set the main file path to `app.py`.
4. Click **Deploy**. Streamlit Cloud installs `requirements.txt` automatically.

Note: Streamlit Cloud's filesystem is not guaranteed to persist forever
across redeploys/restarts, so the IV-history CSV cache may occasionally
reset. For a durable history, point `utils/data_fetch.py` at a small
database (e.g. Supabase, a Google Sheet, or SQLite on a persistent volume)
instead of a local CSV.

## Extending it

- **Real GEX/dealer data**: providers like ORATS, ConvergEx, or SpotGamma
  sell proprietary dealer-positioning data far more accurate than the
  heuristic here — swap `utils/metrics.py` for calls to one of those APIs
  if you need production-grade numbers.
- **Real macro calendar**: `utils/calendar_data.py` uses the Fed's published
  FOMC schedule (accurate) but only approximates CPI/NFP timing. A service
  like Trading Economics or FRED's release calendar API can replace the
  approximation.
- **Multiple tickers / watchlist**: wrap the current single-ticker logic in
  a loop and add a `st.selectbox` or multi-select in the sidebar.
