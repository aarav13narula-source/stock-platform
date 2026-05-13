"""Application configuration — Vercel + Firebase edition."""
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-2026")

    # SQLite is GONE — Firebase is configured via FIREBASE_SERVICE_ACCOUNT env var
    # (No SQLITE_PATH needed)

    SESSION_COOKIE_SECURE = True       # Vercel always uses HTTPS
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 1 week

    # Default user (seeded into Firestore on first run)
    DEFAULT_USER = os.environ.get("DEFAULT_USER", "admin")
    DEFAULT_PASS = os.environ.get("DEFAULT_PASS", "admin123")  # CHANGE after first login

    # Auto-refresh interval (ms) for live market mode
    REFRESH_INTERVAL_MS = 15 * 60 * 1000   # 15 min
    QUICK_REFRESH_MS = 15 * 1000            # 15 sec for price ticks

    # Paper trading
    PAPER_CAPITAL_PER_REC = 100000          # ₹1 lakh per recommendation
    PAPER_STARTING_WALLET = 10000000        # ₹1 crore starting "wallet"

    # Watchlists (default seeds — user can extend in UI)
    NSE_DEFAULT = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
        "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS", "ITC.NS", "LT.NS",
        "HINDUNILVR.NS", "BHARTIARTL.NS", "ASIANPAINT.NS", "MARUTI.NS",
        "TITAN.NS", "BAJFINANCE.NS", "WIPRO.NS", "HCLTECH.NS",
        "ADANIENT.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "JSWSTEEL.NS",
        "ONGC.NS", "POWERGRID.NS", "NTPC.NS", "COALINDIA.NS",
        "SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "ULTRACEMCO.NS",
    ]
    US_DEFAULT = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
        "AMD", "NFLX", "AVGO", "INTC", "ORCL", "CRM", "ADBE",
        "PYPL", "DIS", "BA", "JPM", "BAC", "WMT", "KO", "PEP",
        "JNJ", "PFE", "XOM", "CVX",
    ]
    MCX_DEFAULT = [
        "GC=F", "SI=F", "HG=F", "CL=F", "NG=F", "PL=F", "ZC=F",
    ]
    CRYPTO_DEFAULT = [
        "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
        "ADA-USD", "DOGE-USD", "TRX-USD", "MATIC-USD", "DOT-USD",
        "AVAX-USD", "LINK-USD", "LTC-USD",
    ]

    INDEX_TICKERS = {
        "Nifty 50": "^NSEI",
        "Bank Nifty": "^NSEBANK",
        "Sensex": "^BSESN",
        "India VIX": "^INDIAVIX",
        "S&P 500": "^GSPC",
        "Nasdaq": "^IXIC",
        "Dow Jones": "^DJI",
        "Gold": "GC=F",
        "Crude Oil": "CL=F",
        "USD/INR": "INR=X",
    }
