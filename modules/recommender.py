"""Trade recommender: 8-step workflow producing entry/T1/T2/SL/RR with plain-English logic."""
from datetime import datetime

from modules.analyzer import compute_indicators, detect_patterns, score_timeframe, multi_timeframe_score
from modules.data_fetcher import get_ohlcv, get_quote
from modules import firebase_db as db


# Hard eliminators
def _eliminators(di, mkt):
    """Return list of reasons the stock should be rejected. Empty == passes."""
    rejects = []
    if di is None or di.empty:
        return ["Insufficient data"]
    close = di["Close"].iloc[-1]
    if "EMA50" in di and "EMA200" in di and len(di) >= 200:
        if di["EMA50"].iloc[-1] < di["EMA200"].iloc[-1] and \
                di["EMA50"].iloc[-2] >= di["EMA200"].iloc[-2]:
            rejects.append("Death Cross just triggered")
    rsi_v = di["RSI"].iloc[-1] if "RSI" in di else None
    if rsi_v is not None:
        if rsi_v > 82: rejects.append(f"RSI {rsi_v:.1f} extremely overbought (>82)")
        if rsi_v < 22: rejects.append(f"RSI {rsi_v:.1f} extremely oversold (<22)")
    if "EMA200" in di and close < di["EMA200"].iloc[-1] * 0.85:
        rejects.append("Price >15% below 200-EMA — broken trend")
    if mkt == "NSE" and di["Volume"].tail(20).mean() < 50000:
        rejects.append("Illiquid (avg vol < 50k)")
    return rejects


def _atr_targets(close, atr, style, side="BUY"):
    """Compute entry zone, T1, T2, SL from ATR with style-aware multipliers."""
    if style == "intraday":
        sl_mult, t1_mult, t2_mult = 1.0, 1.5, 2.5
    else:  # swing
        sl_mult, t1_mult, t2_mult = 1.5, 2.5, 4.5
    if side == "BUY":
        entry_lo = close * 0.995
        entry_hi = close * 1.005
        sl = close - sl_mult * atr
        t1 = close + t1_mult * atr
        t2 = close + t2_mult * atr
    else:  # SELL / short
        entry_lo = close * 0.995
        entry_hi = close * 1.005
        sl = close + sl_mult * atr
        t1 = close - t1_mult * atr
        t2 = close - t2_mult * atr
    risk = abs(close - sl)
    reward = abs(t1 - close)
    rr = reward / risk if risk else 0
    return {
        "entry": round(close, 2),
        "entry_zone_lo": round(entry_lo, 2),
        "entry_zone_hi": round(entry_hi, 2),
        "target1": round(t1, 2),
        "target2": round(t2, 2),
        "stop_loss": round(sl, 2),
        "rr_ratio": round(rr, 2),
    }


def _tier(score):
    if score >= 8.0: return "Tier 1 ⭐⭐⭐"
    if score >= 6.5: return "Tier 2 ⭐⭐"
    if score >= 5.0: return "Tier 3 ⭐"
    return "REJECT"


def _plain_rationale(mtf, patterns, side="BUY"):
    """Convert technicals into common-man language."""
    sigs = []
    daily = mtf.get("Daily", {})
    s = daily.get("signals", {})
    if s.get("EMA_STACK") == "bullish":
        sigs.append("Price is trading above its short-term and medium-term moving averages — the trend is clearly UP.")
    if s.get("EMA_STACK") == "bearish":
        sigs.append("Price is below its moving averages — trend is DOWN, avoid buying.")
    if s.get("RSI") in ("neutral_bullish", "strong_bullish"):
        sigs.append("The strength meter (RSI) is in healthy bullish territory.")
    if s.get("RSI") == "overbought":
        sigs.append("The strength meter (RSI) shows the stock is overbought — wait for a pullback.")
    if s.get("MACD") == "bullish":
        sigs.append("Momentum (MACD) just turned positive — buyers are getting active.")
    if s.get("Volume") in ("surge", "above_avg"):
        sigs.append("Trading volume is higher than usual — big players are participating.")
    if s.get("ADX") == "strong_trend":
        sigs.append("Trend strength (ADX) is strong, the move is likely to continue.")
    if s.get("BB") == "breakout_up":
        sigs.append("Price has broken above its upper Bollinger Band — a breakout is in play.")
    if patterns:
        names = ", ".join(p["name"] for p in patterns if p["score"] > 0)
        if names:
            sigs.append(f"Bullish chart patterns detected: {names}.")
    if mtf.get("aligned_count", 0) >= 3:
        sigs.append("Multiple timeframes (monthly + weekly + daily) all agree — high-conviction setup.")
    if not sigs:
        sigs.append("Mixed signals — no strong edge right now.")
    return " ".join(sigs)


def analyze_ticker(ticker, market, style="swing"):
    """Run full 8-step analysis. Returns recommendation dict or None."""
    df = get_ohlcv(ticker, "1d")
    if df.empty or len(df) < 30:
        return None
    di = compute_indicators(df)
    rejects = _eliminators(di, market)
    if rejects:
        return {"ticker": ticker, "market": market, "style": style,
                "rejected": True, "reasons": rejects}

    patterns = detect_patterns(di)
    mtf = multi_timeframe_score(ticker, get_ohlcv)
    pattern_bonus = sum(max(0, p["score"]) for p in patterns) / 5.0
    final_score = min(10.0, mtf["composite"] + pattern_bonus * 0.3)

    daily = score_timeframe(df)
    close = daily["close"]
    atr_v = daily["atr"] or close * 0.01
    side = "BUY" if final_score >= 5 else "SELL"
    tp = _atr_targets(close, atr_v, style, side)

    rationale = _plain_rationale(mtf, patterns, side)
    pat_names = ", ".join(p["name"] for p in patterns) or "No major pattern"
    risks = "Watch out for: sudden negative news, broader market correction, RSI hitting overbought >75, breaking the stop loss level."

    holding = 1 if style == "intraday" else 7
    return {
        "ticker": ticker, "market": market, "style": style,
        "side": side, "score": round(final_score, 2),
        "tier": _tier(final_score), "pattern": pat_names,
        "rationale": rationale, "risks": risks,
        "holding_days": holding, "patterns_detected": patterns,
        "mtf": mtf, "indicators": daily,
        **tp,
    }


def generate_recommendations(tickers, market, style="swing", top_n=10, save=True):
    """Run analysis on a list of tickers, return top-N ranked."""
    results = []
    for t in tickers:
        try:
            r = analyze_ticker(t, market, style)
            if r and not r.get("rejected"):
                results.append(r)
        except Exception as e:
            continue
    # Rank descending
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]
    if save:
        for r in top:
            if r["rr_ratio"] >= 1.5 and r["score"] >= 5.5:
                rec_id = db.save_recommendation(r)
                r["id"] = rec_id
                # Auto-open paper trade with ₹1L
                from modules.paper_trade import auto_open_paper_for_rec
                auto_open_paper_for_rec(rec_id, r)
    return top
