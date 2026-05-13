"""Live market data fetching: yfinance for stocks/MCX, CoinGecko fallback for crypto."""
import time
import logging
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
import requests

log = logging.getLogger(__name__)

try:
    import yfinance as yf
    HAS_YF = True
except Exception as e:
    log.warning("yfinance not available: %s", e)
    HAS_YF = False


# Cache wrappers: yfinance is rate-limited, so cache aggressively.
_PRICE_CACHE = {}
_PRICE_TTL = 30      # seconds for current price
_OHLC_CACHE = {}
_OHLC_TTL = 300      # 5 minutes for OHLCV bars


def _cache_get(cache, key, ttl):
    item = cache.get(key)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    return None


def _cache_set(cache, key, value):
    cache[key] = (time.time(), value)


# ------------------------------------------------------------------ #
# Quote / current price
# ------------------------------------------------------------------ #
def get_quote(ticker):
    """Return latest price, change %, volume, prev close, high, low."""
    cached = _cache_get(_PRICE_CACHE, ticker, _PRICE_TTL)
    if cached:
        return cached
    if not HAS_YF:
        return {"ticker": ticker, "price": None, "error": "yfinance unavailable"}
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info if hasattr(t, "fast_info") else {}
        price = info.get("last_price") if info else None
        prev = info.get("previous_close") if info else None
        # Fallback to last bar
        if price is None or prev is None:
            hist = t.history(period="5d", interval="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        chg = (price - prev) / prev * 100 if (price and prev) else 0
        out = {
            "ticker": ticker,
            "price": round(price, 4) if price else None,
            "change_pct": round(chg, 2),
            "prev_close": round(prev, 4) if prev else None,
            "day_high": info.get("day_high") if info else None,
            "day_low": info.get("day_low") if info else None,
            "volume": info.get("last_volume") if info else None,
            "ts": datetime.utcnow().isoformat(),
        }
        _cache_set(_PRICE_CACHE, ticker, out)
        return out
    except Exception as e:
        log.warning("quote err %s: %s", ticker, e)
        return {"ticker": ticker, "price": None, "error": str(e)}


def get_quotes_bulk(tickers):
    return [get_quote(t) for t in tickers]


# ------------------------------------------------------------------ #
# OHLCV history
# ------------------------------------------------------------------ #
INTERVAL_MAP = {
    "1m":  ("1m",  "1d"),
    "5m":  ("5m",  "5d"),
    "15m": ("15m", "1mo"),
    "1h":  ("1h",  "3mo"),
    "1d":  ("1d",  "1y"),
    "1wk": ("1wk", "5y"),
    "1mo": ("1mo", "10y"),
}


def get_ohlcv(ticker, timeframe="1d", period=None):
    """Return DataFrame with OHLCV; uses cache."""
    key = f"{ticker}|{timeframe}|{period or ''}"
    cached = _cache_get(_OHLC_CACHE, key, _OHLC_TTL)
    if cached is not None:
        return cached.copy()
    if not HAS_YF:
        return pd.DataFrame()
    interval, default_period = INTERVAL_MAP.get(timeframe, ("1d", "1y"))
    try:
        df = yf.download(
            ticker, period=period or default_period, interval=interval,
            progress=False, auto_adjust=False, threads=False,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        # Flatten multi-index columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns=str.title)
        df = df.dropna()
        _cache_set(_OHLC_CACHE, key, df)
        return df.copy()
    except Exception as e:
        log.warning("ohlcv err %s: %s", ticker, e)
        return pd.DataFrame()


# ------------------------------------------------------------------ #
# Index snapshot
# ------------------------------------------------------------------ #
def get_indices_snapshot(index_map):
    out = []
    for name, tkr in index_map.items():
        q = get_quote(tkr)
        out.append({"name": name, **q})
    return out


# ------------------------------------------------------------------ #
# Crypto (CoinGecko fallback)
# ------------------------------------------------------------------ #
_CG_BASE = "https://api.coingecko.com/api/v3"
_CG_ID_MAP = {
    "BTC-USD": "bitcoin", "ETH-USD": "ethereum", "BNB-USD": "binancecoin",
    "SOL-USD": "solana", "XRP-USD": "ripple", "ADA-USD": "cardano",
    "DOGE-USD": "dogecoin", "TRX-USD": "tron", "MATIC-USD": "matic-network",
    "DOT-USD": "polkadot", "AVAX-USD": "avalanche-2", "LINK-USD": "chainlink",
    "LTC-USD": "litecoin",
}


def get_crypto_market(limit=25):
    try:
        r = requests.get(
            f"{_CG_BASE}/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": limit, "page": 1, "sparkline": "false"},
            timeout=10,
        )
        if r.ok:
            return r.json()
    except Exception as e:
        log.warning("CoinGecko err: %s", e)
    return []
