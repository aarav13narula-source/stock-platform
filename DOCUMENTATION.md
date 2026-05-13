# 📘 Stock Analyst Pro — Complete Feature Documentation

This document lists every feature in the platform, mapped to your original requirements + the extra "smart" features I added to help you make profits.

---

## 1 · Markets Supported

| Market | Symbols | Data source |
|---|---|---|
| **USA NASDAQ / NYSE** | AAPL, MSFT, GOOGL, NVDA, TSLA, … (extendable) | yfinance |
| **India NSE** | RELIANCE, TCS, INFY, HDFCBANK, NIFTY 50, BANKNIFTY, … | yfinance (`.NS` suffix) |
| **MCX Commodities** | Gold, Silver, Copper, Crude Oil, Natural Gas, Platinum | yfinance futures (`=F`) |
| **Crypto** | BTC, ETH, BNB, SOL, XRP, … | yfinance + CoinGecko fallback |
| **Indices** | Nifty 50, Bank Nifty, Sensex, India VIX, S&P 500, Nasdaq, Dow, Gold, Crude, USD/INR | yfinance |

You can extend the watchlists in `config.py` or via the (planned) UI watchlist editor.

---

## 2 · Technical-Analysis Engine

Implemented in `modules/analyzer.py`:

* **Indicators (full formulas, no closed-source lib):** EMA(9/20/50/200), RSI(14), MACD(12,26,9), Bollinger(20,2), ATR(14), OBV, ADX(14), Volume ratio vs 20-day avg.
* **Patterns detected:** Hammer, Bullish/Bearish Engulfing, Double Bottom, Bull Flag, 52-Week High Breakout, Golden Cross, Death Cross, Head & Shoulders.
* **Multi-timeframe scoring:** Monthly → Weekly → Daily → Hourly each scored 0-10; **alignment bonus** if 3+ timeframes agree.
* **Hard eliminators:** Death Cross, RSI > 82, RSI < 22, illiquidity, > 15% below 200-EMA — stocks failing any eliminator are rejected.

---

## 3 · Recommendation Workflow (8 steps)

`modules/recommender.py → analyze_ticker()` follows your spec:

1. Pull OHLCV (daily) → compute indicator set
2. Apply hard eliminators (reject if any fire)
3. Detect chart patterns
4. Multi-timeframe alignment scoring
5. Final composite score (0-10) + pattern bonus
6. ATR-based entry / T1 / T2 / SL + R:R ratio
7. Plain-English rationale generator (no jargon)
8. Tier classification (⭐⭐⭐ Tier 1 ≥ 8 · ⭐⭐ Tier 2 ≥ 6.5 · ⭐ Tier 3 ≥ 5)

Each recommendation is stored in the DB and **automatically gets a ₹1,00,000 paper trade** (Section 6).

### Intraday vs Swing
* Intraday → 1-day max hold, tighter SL/T1/T2 ATR multipliers.
* Swing → up to 10-day hold, wider targets.
* Both have their own tabs and accuracy KPIs.

---

## 4 · Multi-Resolution Charts

* **TradingView Advanced widget** is embedded on every stock page (`templates/stock_detail.html`).
* Default studies: **RSI, MACD, Bollinger Bands, Volume**.
* User can switch resolutions in-chart: **1m · 5m · 15m · 1h · 1d · 1w · 1mo**.
* The platform also exposes a JSON candles endpoint `GET /api/candles/<ticker>?tf=1d` that can be re-plotted in custom charts (Chart.js / Lightweight-Charts ready).

---

## 5 · Self-Learning AI (Reinforcement + Supervised + Unsupervised)

`modules/ml_engine.py` runs **three learning loops**:

1. **Reinforcement (online)** — each closed paper trade nudges per-indicator weights up/down. Weights live in `ml_weights` table and are surfaced on Self-Audit page.
2. **Supervised (SGDClassifier)** — refit hourly on the historical audit log; predicts `P(win)` for any new setup. Surfaced as "AI Win Prob %" on every open recommendation.
3. **Unsupervised (KMeans)** — clusters historical setups into "archetypes"; remembers which clusters under-perform.

After every trade close the engine also writes a **plain-English Self-Note** like:
> *"On RELIANCE, signals ema_cross, macd, volume_surge failed (loss −1.83%). Reducing weight of these indicators. Next time look for confirmation from more timeframes before entering."*

These notes appear under **Self-Audit → Self Notes**.

---

## 6 · Paper-Trade Game (₹1,00,000 each)

`modules/paper_trade.py`:

* Every recommendation auto-opens a dummy ₹1,00,000 trade.
* Mark-to-market every 15 minutes (and on demand).
* Auto-closes when **T1 / T2 / SL** is hit (recorded as WIN / LOSS).
* Time-exit after 1 day (intraday) / 10 days (swing).
* **Swap action** — convert any open trade into a different stock to test your own ideas.
* Separate dashboards for Intraday vs Swing — each shows win-rate, total ₹ P&L, live P&L, history.
* Every close feeds the **Self-Audit log** + the **ML weights** (Section 5).

---

## 7 · Self-Audit (Honest Track Record)

`templates/self_audit.html` shows:

* Accuracy % for Intraday and Swing separately.
* Wins / Losses count, avg P&L %.
* Full trade log — *"If you had invested ₹1,00,000 in RELIANCE, it would now be worth ₹1,04,200 — a +4.20% return."*
* **Self Notes** — what the AI learned, categorized as `win_pattern`, `loss_lesson`, or `neutral`.
* **Live indicator-weights table** showing how reinforcement learning has tuned each signal.
* CSV + PDF downloads for the audit log and notes.

---

## 8 · Alerts & Notifications

* **Manual alerts:** price ABOVE / BELOW any threshold per ticker.
* **Automatic alerts:** when an open recommendation's live price comes within **1 %** of T1 / T2 / SL, a **popup modal** appears with **OK / Snooze 30 min** buttons (exactly as you requested).
* Bell icon in nav shows unread count + a dropdown with last 20 notifications.
* Severity tags: `info` / `warn` / `critical` (critical = popup-eligible).

---

## 9 · Media Tab (X / Reddit / News Leaderboard)

`modules/news_engine.py`:

* Aggregates Google News RSS (Moneycontrol, ET Markets, Bloomberg, Reuters).
* Fetches Reddit hot posts (r/IndianStockMarket, r/stocks, r/CryptoCurrency).
* TextBlob NLP scores polarity on every headline.
* Builds **Top-5 BUY** and **Top-5 SELL** mention-leaderboard (your request).
* Each row links back to the source headline.

> X/Twitter is paywalled now — the platform uses Reddit + verified RSS for the equivalent buzz. Nitter / community X mirrors can be added in `_FEEDS` if you want.

---

## 10 · Reports & Downloads

* **CSV + PDF** for: recommendations, audit log, paper trades, self-notes.
* PDFs are styled in landscape with branded headers.
* Triggered from the **Reports** page or any context-specific page (recommendations, paper trade, audit).

---

## 11 · UI / UX

* **Light by default, dark on toggle** — preference is saved per user.
* Top nav with all your requested menu items: USA · NSE · MCX · Crypto · Best Picks · Intraday · Swing · Paper Trade · Self Audit · Media · Alerts · Reports.
* Auto-refresh every **15 minutes** on live pages (dashboard, markets, recommendations, paper trade, best picks).
* Fully responsive — works on phone, tablet, desktop.
* TradingView-grade charts on every stock page + Nifty 50 widget on the dashboard.

---

## 12 · Architecture

* **Backend:** Flask 3 · Flask-Login · SQLite (no DB-server required).
* **Background jobs:** APScheduler — mark-to-market (15 min), alert poll (1 min), near-decision popups (5 min), ML retrain (1 hr).
* **ML stack:** scikit-learn (SGDClassifier, KMeans, StandardScaler), pure-pandas indicators.
* **Frontend:** vanilla JS + Jinja2 + TradingView widget + Lightweight-Charts (optional).
* **Data:** yfinance (free, no API key) + CoinGecko (free) + Google News RSS + Reddit JSON.

All free, all standard — nothing requires a paid API key out of the box.

---

## 13 · Extending

* Add tickers → edit `config.py` (`NSE_DEFAULT`, `US_DEFAULT`, `MCX_DEFAULT`, `CRYPTO_DEFAULT`) **or** insert rows into the `watchlist` table.
* Add more patterns → drop into `modules/analyzer.py → detect_patterns()` and return a dict.
* Plug in a paid API (e.g., Finnhub, Polygon, Alpha Vantage, NSE official) → swap functions in `modules/data_fetcher.py`.
* Add WhatsApp / email reports — APScheduler hook in `modules/scheduler.py` is the place.

---

## 14 · Disclaimer

This software is for personal research & education. Past performance ≠ future results. Always do your own due diligence and consult a SEBI-registered advisor before risking real capital.
