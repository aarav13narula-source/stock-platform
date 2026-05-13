"""News + social-media sentiment engine.

Sources (all free, no API keys required):
  • Google News RSS  (Moneycontrol, ET Markets, Bloomberg, Reuters — country/topic feeds)
  • Reddit JSON public endpoints  (r/IndianStockMarket, r/wallstreetbets, r/CryptoCurrency)
  • Nitter (X/Twitter alternative) RSS  — optional best-effort

Outputs:
  • Headlines list with simple polarity (positive / neutral / negative)
  • A Top-5 BUY and Top-5 SELL leaderboard (the 'Media' tab)
"""
import re
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import requests
from textblob import TextBlob

log = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 stock-platform/1.0"}

_FEEDS = {
    "Global Markets": "https://news.google.com/rss/search?q=stock+market&hl=en&gl=US",
    "Indian Markets": "https://news.google.com/rss/search?q=NSE+India+stock&hl=en&gl=IN",
    "US Markets":     "https://news.google.com/rss/search?q=NASDAQ+OR+S%26P500&hl=en&gl=US",
    "Commodities":    "https://news.google.com/rss/search?q=gold+silver+crude+commodity&hl=en",
    "Crypto":         "https://news.google.com/rss/search?q=cryptocurrency+bitcoin+ethereum&hl=en",
}

_SUBREDDITS = {
    "Indian Markets": "IndianStockMarket",
    "US Markets":     "stocks",
    "Crypto":         "CryptoCurrency",
}


def _polarity(text):
    try:
        p = TextBlob(text).sentiment.polarity
    except Exception:
        p = 0.0
    if p > 0.15: return "positive", p
    if p < -0.15: return "negative", p
    return "neutral", p


def fetch_rss(url, limit=20):
    """Lightweight RSS parse without feedparser dep (use feedparser if available)."""
    try:
        import feedparser
        f = feedparser.parse(url)
        items = []
        for e in f.entries[:limit]:
            title = e.get("title", "")
            link = e.get("link", "")
            pub = e.get("published", "")
            label, score = _polarity(title)
            items.append({"title": title, "link": link, "pub": pub,
                          "sentiment": label, "score": score})
        return items
    except Exception as e:
        log.warning("rss err %s: %s", url, e)
        return []


def fetch_reddit(sub, limit=25):
    try:
        r = requests.get(
            f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}",
            headers=UA, timeout=8,
        )
        if not r.ok:
            return []
        out = []
        for c in r.json()["data"]["children"]:
            d = c["data"]
            title = d.get("title", "")
            label, score = _polarity(title)
            out.append({
                "title": title,
                "link": f"https://reddit.com{d.get('permalink', '')}",
                "score": score,
                "ups": d.get("ups", 0),
                "sentiment": label,
                "subreddit": sub,
            })
        return out
    except Exception as e:
        log.warning("reddit err: %s", e)
        return []


def aggregate_news():
    out = {}
    for label, url in _FEEDS.items():
        out[label] = fetch_rss(url, limit=15)
    return out


def aggregate_social():
    out = {}
    for label, sub in _SUBREDDITS.items():
        out[label] = fetch_reddit(sub, limit=20)
    return out


# ------------------------------------------------------------------ #
# Build BUY / SELL leaderboard from social + news
# ------------------------------------------------------------------ #
_TICKER_PAT = re.compile(r"\b([A-Z]{2,6})\b")   # rough US ticker
_INR_PAT = re.compile(r"\b(RELIANCE|TCS|INFY|HDFC|ICICI|SBI|AXIS|KOTAK|ITC|LT|ADANI|"
                      r"TATA|JSW|ONGC|NTPC|COAL|SUN|DR\.?REDDY|CIPLA|WIPRO|HCL|MARUTI|"
                      r"BHARTI|TITAN|BAJAJ|ASIAN|ULTRACEMCO|POWERGRID|NIFTY|BANKNIFTY)\b",
                      re.IGNORECASE)


def media_leaderboard():
    """Aggregate mentions + sentiment into Top-5 BUY and Top-5 SELL leaderboards."""
    scoreboard = defaultdict(lambda: {"pos": 0, "neg": 0, "mentions": 0, "sources": []})
    # news
    for label, items in aggregate_news().items():
        for it in items:
            for m in set(_INR_PAT.findall(it["title"]) + _TICKER_PAT.findall(it["title"])):
                k = m.upper()
                scoreboard[k]["mentions"] += 1
                if it["sentiment"] == "positive": scoreboard[k]["pos"] += 1
                if it["sentiment"] == "negative": scoreboard[k]["neg"] += 1
                scoreboard[k]["sources"].append({"title": it["title"], "link": it["link"]})
    # social
    for label, items in aggregate_social().items():
        for it in items:
            for m in set(_INR_PAT.findall(it["title"]) + _TICKER_PAT.findall(it["title"])):
                k = m.upper()
                scoreboard[k]["mentions"] += 1
                if it["sentiment"] == "positive": scoreboard[k]["pos"] += 1
                if it["sentiment"] == "negative": scoreboard[k]["neg"] += 1
                scoreboard[k]["sources"].append({"title": it["title"], "link": it["link"]})

    rows = []
    for tkr, s in scoreboard.items():
        if s["mentions"] < 2:
            continue
        net = s["pos"] - s["neg"]
        rows.append({"ticker": tkr, "mentions": s["mentions"],
                     "pos": s["pos"], "neg": s["neg"],
                     "net": net, "sources": s["sources"][:3]})
    buys = sorted([r for r in rows if r["net"] > 0],
                  key=lambda x: (x["net"], x["mentions"]), reverse=True)[:5]
    sells = sorted([r for r in rows if r["net"] < 0],
                   key=lambda x: (x["net"], -x["mentions"]))[:5]
    return {"buys": buys, "sells": sells, "generated_at": datetime.utcnow().isoformat()}
