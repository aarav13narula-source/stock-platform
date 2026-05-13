"""Technical analysis engine: indicators, patterns, multi-timeframe scoring."""
import numpy as np
import pandas as pd


# ------------------------------------------------------------------ #
# Indicator formulas (pure pandas, no external TA dependency required)
# ------------------------------------------------------------------ #
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def sma(series, length):
    return series.rolling(length).mean()


def rsi(series, length=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    ef = ema(series, fast)
    es = ema(series, slow)
    line = ef - es
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def bollinger(series, length=20, std=2):
    m = sma(series, length)
    s = series.rolling(length).std()
    return m + std * s, m, m - std * s


def atr(df, length=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def obv(df):
    sign = np.sign(df["Close"].diff().fillna(0))
    return (sign * df["Volume"].fillna(0)).cumsum()


def adx(df, length=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    atr_ = tr.rolling(length).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(length).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(length).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(length).mean()


# ------------------------------------------------------------------ #
# Indicator suite
# ------------------------------------------------------------------ #
def compute_indicators(df):
    """Add a full suite of indicators to an OHLCV dataframe."""
    if df is None or df.empty or len(df) < 30:
        return df
    df = df.copy()
    df["EMA9"] = ema(df["Close"], 9)
    df["EMA20"] = ema(df["Close"], 20)
    df["EMA50"] = ema(df["Close"], 50)
    df["EMA200"] = ema(df["Close"], 200) if len(df) >= 200 else ema(df["Close"], 50)
    df["RSI"] = rsi(df["Close"], 14)
    line, sig, hist = macd(df["Close"])
    df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = line, sig, hist
    bb_u, bb_m, bb_l = bollinger(df["Close"], 20, 2)
    df["BB_U"], df["BB_M"], df["BB_L"] = bb_u, bb_m, bb_l
    df["ATR"] = atr(df, 14)
    df["OBV"] = obv(df)
    df["ADX"] = adx(df, 14)
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_AVG20"]
    return df


# ------------------------------------------------------------------ #
# Pattern detectors
# ------------------------------------------------------------------ #
def _last(df, col):
    if df.empty or col not in df:
        return None
    return df[col].iloc[-1] if not pd.isna(df[col].iloc[-1]) else None


def detect_patterns(df):
    """Return list of detected pattern dicts."""
    out = []
    if df is None or df.empty or len(df) < 30:
        return out
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    o = df["Open"]

    # Hammer (bullish reversal)
    body = (c - o).abs().iloc[-1]
    rng = (h - l).iloc[-1]
    lower_wick = (min(c.iloc[-1], o.iloc[-1]) - l.iloc[-1])
    upper_wick = h.iloc[-1] - max(c.iloc[-1], o.iloc[-1])
    if rng > 0 and lower_wick >= 2 * body and upper_wick <= 0.1 * rng and body <= 0.35 * rng:
        out.append({"name": "Hammer", "type": "Bullish Reversal", "score": 7.5})

    # Bullish Engulfing
    if len(df) >= 2:
        po, pc = o.iloc[-2], c.iloc[-2]
        co, cc = o.iloc[-1], c.iloc[-1]
        if pc < po and cc > co and cc > po and co < pc:
            out.append({"name": "Bullish Engulfing", "type": "Bullish Reversal", "score": 7.0})
        if pc > po and cc < co and cc < po and co > pc:
            out.append({"name": "Bearish Engulfing", "type": "Bearish Reversal", "score": -7.0})

    # Double Bottom (rough heuristic): two recent lows within 2% of each other
    last_lows = l.tail(40)
    if not last_lows.empty:
        m1 = last_lows.idxmin()
        without = last_lows.drop(m1)
        if not without.empty:
            m2 = without.idxmin()
            if abs(last_lows[m1] - without[m2]) / last_lows[m1] < 0.02 and m2 != m1:
                out.append({"name": "Double Bottom", "type": "Bullish Reversal", "score": 7.8})

    # Bull Flag: strong rally then tight consolidation
    if len(df) >= 30:
        recent = c.tail(15)
        prior = c.iloc[-30:-15]
        if not prior.empty and recent.std() < prior.std() * 0.6 \
                and prior.iloc[-1] > prior.iloc[0] * 1.05:
            out.append({"name": "Bull Flag", "type": "Bullish Continuation", "score": 7.2})

    # 52-week high breakout
    if len(df) >= 60:
        window = c.tail(min(252, len(df)))
        if c.iloc[-1] >= window.max() * 0.999:
            out.append({"name": "52-Week High Breakout", "type": "Breakout", "score": 8.0})

    # Death Cross / Golden Cross
    if "EMA50" in df.columns and "EMA200" in df.columns and len(df) >= 200:
        e50, e200 = df["EMA50"], df["EMA200"]
        if e50.iloc[-2] < e200.iloc[-2] and e50.iloc[-1] > e200.iloc[-1]:
            out.append({"name": "Golden Cross", "type": "Bullish Continuation", "score": 8.5})
        if e50.iloc[-2] > e200.iloc[-2] and e50.iloc[-1] < e200.iloc[-1]:
            out.append({"name": "Death Cross", "type": "Bearish", "score": -8.5})

    # Head & Shoulders (very rough): three peaks with middle highest
    if len(df) >= 50:
        peaks = h.tail(50)
        sorted_idx = peaks.nlargest(3).index.tolist()
        if len(sorted_idx) == 3:
            sorted_idx.sort()
            a, b, cc = peaks[sorted_idx[0]], peaks[sorted_idx[1]], peaks[sorted_idx[2]]
            if b > a > cc * 0.97 and b > cc:
                out.append({"name": "Head & Shoulders", "type": "Bearish", "score": -7.5})

    return out


# ------------------------------------------------------------------ #
# Multi-timeframe scoring
# ------------------------------------------------------------------ #
def score_timeframe(df):
    """Score a single timeframe 0..10 plus signals breakdown."""
    if df is None or df.empty or len(df) < 30:
        return {"score": 0, "signals": {}, "verdict": "INSUFFICIENT_DATA"}
    di = compute_indicators(df)
    signals = {}
    score = 5.0

    rsi_v = _last(di, "RSI")
    if rsi_v is not None:
        if 30 <= rsi_v <= 60: signals["RSI"] = "neutral_bullish"; score += 0.6
        elif 60 < rsi_v <= 70: signals["RSI"] = "strong_bullish"; score += 1.0
        elif rsi_v > 70: signals["RSI"] = "overbought"; score -= 0.8
        elif rsi_v < 30: signals["RSI"] = "oversold_bounce"; score += 0.4
        else: signals["RSI"] = "weak"; score -= 0.4

    macd_h = _last(di, "MACD_HIST")
    if macd_h is not None:
        if macd_h > 0: signals["MACD"] = "bullish"; score += 0.8
        else: signals["MACD"] = "bearish"; score -= 0.8

    close = _last(di, "Close")
    e20 = _last(di, "EMA20"); e50 = _last(di, "EMA50"); e200 = _last(di, "EMA200")
    if close and e20 and e50:
        if close > e20 > e50: signals["EMA_STACK"] = "bullish"; score += 1.0
        elif close < e20 < e50: signals["EMA_STACK"] = "bearish"; score -= 1.0
        else: signals["EMA_STACK"] = "mixed"
    if close and e200:
        if close > e200: signals["LongTrend"] = "uptrend"; score += 0.5
        else: signals["LongTrend"] = "downtrend"; score -= 0.5

    bb_u = _last(di, "BB_U"); bb_l = _last(di, "BB_L")
    if close and bb_u and bb_l:
        if close > bb_u: signals["BB"] = "breakout_up"; score += 0.7
        elif close < bb_l: signals["BB"] = "oversold"; score -= 0.5

    adx_v = _last(di, "ADX")
    if adx_v is not None:
        if adx_v > 25: signals["ADX"] = "strong_trend"; score += 0.6
        else: signals["ADX"] = "weak_trend"

    vol_r = _last(di, "VOL_RATIO")
    if vol_r is not None:
        if vol_r > 1.8: signals["Volume"] = "surge"; score += 1.2
        elif vol_r > 1.2: signals["Volume"] = "above_avg"; score += 0.5
        else: signals["Volume"] = "low"

    score = max(0.0, min(10.0, score))
    verdict = "BUY" if score >= 7 else "WATCH" if score >= 5 else "AVOID"
    return {"score": round(score, 2), "signals": signals, "verdict": verdict,
            "rsi": rsi_v, "macd_hist": macd_h, "adx": adx_v,
            "ema20": e20, "ema50": e50, "ema200": e200,
            "close": close, "atr": _last(di, "ATR"),
            "vol_ratio": vol_r}


def multi_timeframe_score(ticker, fetcher):
    """Score Monthly→Weekly→Daily→Hourly with alignment bonus."""
    frames = {"Monthly": "1mo", "Weekly": "1wk", "Daily": "1d", "Hourly": "1h"}
    out = {}
    bullish_count = 0
    total_score = 0
    for label, tf in frames.items():
        df = fetcher(ticker, tf)
        s = score_timeframe(df)
        out[label] = s
        if s["score"] >= 6.5:
            bullish_count += 1
        total_score += s["score"]
    align_bonus = bullish_count * 0.4
    composite = (total_score / 4) + align_bonus
    composite = max(0, min(10, composite))
    out["composite"] = round(composite, 2)
    out["aligned_count"] = bullish_count
    return out
