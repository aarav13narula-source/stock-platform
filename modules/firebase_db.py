"""Firebase Firestore database layer — drop-in replacement for database.py (SQLite)."""
import json
import os
import logging
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Firebase initialisation
# Reads FIREBASE_SERVICE_ACCOUNT env var (JSON string) on Vercel.
# Falls back to firebase-service-account.json locally.
# ------------------------------------------------------------------ #
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    sa_env = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if sa_env:
        sa_dict = json.loads(sa_env)
        cred = credentials.Certificate(sa_dict)
    else:
        cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)

_db = firestore.client()


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def _now():
    return datetime.utcnow().isoformat()


def _doc_to_dict(doc):
    d = doc.to_dict()
    d["id"] = doc.id
    return d


# ------------------------------------------------------------------ #
# Init / seed (call once on startup)
# ------------------------------------------------------------------ #
def init_db():
    from config import Config
    """Seed default user, ML weights, and watchlist if they don't exist."""

    # --- Default user ---
    users_ref = _db.collection("users")
    existing = users_ref.where("username", "==", Config.DEFAULT_USER).limit(1).get()
    if not list(existing):
        users_ref.add({
            "username": Config.DEFAULT_USER,
            "password_hash": generate_password_hash(Config.DEFAULT_PASS),
            "created_at": _now(),
            "theme": "light",
        })
        log.info("Seeded default user: %s", Config.DEFAULT_USER)

    # --- ML weights ---
    default_weights = {
        "rsi": 1.0, "macd": 1.2, "ema_cross": 1.1, "bb": 0.9,
        "atr": 0.7, "obv": 1.0, "adx": 1.0, "volume_surge": 1.3,
        "pattern": 1.5, "multi_tf": 1.4, "news_sentiment": 0.8,
    }
    for indicator, weight in default_weights.items():
        ref = _db.collection("ml_weights").document(indicator)
        if not ref.get().exists:
            ref.set({
                "indicator": indicator, "weight": weight,
                "wins": 0, "losses": 0, "last_updated": _now(),
            })

    # --- Watchlist seed ---
    user_doc = list(users_ref.where("username", "==", Config.DEFAULT_USER).limit(1).get())[0]
    uid = user_doc.id
    wl_ref = _db.collection("watchlist")
    existing_wl = list(wl_ref.where("user_id", "==", uid).limit(1).get())
    if not existing_wl:
        seeds = (
            [(t, "NSE") for t in Config.NSE_DEFAULT[:10]] +
            [(t, "US") for t in Config.US_DEFAULT[:8]] +
            [(t, "MCX") for t in Config.MCX_DEFAULT[:5]] +
            [(t, "CRYPTO") for t in Config.CRYPTO_DEFAULT[:5]]
        )
        for tkr, mkt in seeds:
            wl_ref.add({"user_id": uid, "ticker": tkr, "market": mkt, "added_at": _now()})
        log.info("Seeded watchlist for user %s", uid)


# ------------------------------------------------------------------ #
# User helpers
# ------------------------------------------------------------------ #
def get_user_by_username(username):
    docs = list(_db.collection("users").where("username", "==", username).limit(1).get())
    if not docs:
        return None
    return _doc_to_dict(docs[0])


def get_user_by_id(uid):
    doc = _db.collection("users").document(str(uid)).get()
    if not doc.exists:
        return None
    return _doc_to_dict(doc)


def verify_password(username, password):
    user = get_user_by_username(username)
    if not user:
        return None
    if check_password_hash(user["password_hash"], password):
        return user
    return None


def update_theme(uid, theme):
    _db.collection("users").document(str(uid)).update({"theme": theme})


# ------------------------------------------------------------------ #
# Recommendations
# ------------------------------------------------------------------ #
def save_recommendation(rec):
    _, ref = _db.collection("recommendations").add({
        "ticker": rec["ticker"],
        "market": rec["market"],
        "style": rec["style"],
        "side": rec.get("side", "BUY"),
        "entry": rec["entry"],
        "target1": rec["target1"],
        "target2": rec["target2"],
        "stop_loss": rec["stop_loss"],
        "rr_ratio": rec["rr_ratio"],
        "score": rec["score"],
        "tier": rec["tier"],
        "pattern": rec.get("pattern", ""),
        "rationale": rec.get("rationale", ""),
        "risks": rec.get("risks", ""),
        "holding_days": rec.get("holding_days", 5),
        "created_at": _now(),
        "status": "OPEN",
        "final_pnl_pct": None,
        "closed_at": None,
    })
    return ref.id


def list_recommendations(style=None, status=None, limit=200):
    ref = _db.collection("recommendations")
    if style:
        ref = ref.where("style", "==", style)
    if status:
        ref = ref.where("status", "==", status)
    docs = ref.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit).get()
    return [_doc_to_dict(d) for d in docs]


def close_recommendation(rec_id, status, final_pnl_pct):
    _db.collection("recommendations").document(str(rec_id)).update({
        "status": status,
        "final_pnl_pct": final_pnl_pct,
        "closed_at": _now(),
    })


# ------------------------------------------------------------------ #
# Audit / notes
# ------------------------------------------------------------------ #
def log_audit(rec_id, ticker, style, invested, final_value, pnl_pct, outcome, reason):
    _db.collection("audit_log").add({
        "rec_id": str(rec_id),
        "ticker": ticker,
        "style": style,
        "invested": invested,
        "final_value": final_value,
        "pnl_pct": pnl_pct,
        "outcome": outcome,
        "reason": reason,
        "closed_at": _now(),
    })


def add_self_note(note, lesson, category):
    _db.collection("self_notes").add({
        "note": note, "lesson": lesson,
        "category": category, "created_at": _now(),
    })


def list_self_notes(limit=100):
    docs = (_db.collection("self_notes")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit).get())
    return [_doc_to_dict(d) for d in docs]


def list_audit(style=None, limit=500):
    ref = _db.collection("audit_log")
    if style:
        ref = ref.where("style", "==", style)
    docs = ref.order_by("closed_at", direction=firestore.Query.DESCENDING).limit(limit).get()
    return [_doc_to_dict(d) for d in docs]


def accuracy_stats(style=None):
    rows = list_audit(style=style, limit=10000)
    if not rows:
        return {"total": 0, "wins": 0, "losses": 0, "accuracy": 0.0,
                "avg_pnl": 0.0, "best": None, "worst": None}
    wins = sum(1 for r in rows if r["outcome"] == "WIN")
    losses = sum(1 for r in rows if r["outcome"] == "LOSS")
    total = len(rows)
    acc = (wins / total * 100) if total else 0
    avg = sum((r["pnl_pct"] or 0) for r in rows) / total
    best = max(rows, key=lambda r: r["pnl_pct"] or 0)
    worst = min(rows, key=lambda r: r["pnl_pct"] or 0)
    return {"total": total, "wins": wins, "losses": losses,
            "accuracy": round(acc, 2), "avg_pnl": round(avg, 2),
            "best": best, "worst": worst}


# ------------------------------------------------------------------ #
# Paper trading
# ------------------------------------------------------------------ #
def open_paper_trade(rec_id, ticker, style, side, entry_price, invested):
    qty = invested / entry_price if entry_price > 0 else 0
    _, ref = _db.collection("paper_trades").add({
        "rec_id": str(rec_id),
        "ticker": ticker, "style": style, "side": side,
        "qty": qty, "entry_price": entry_price,
        "invested": invested, "status": "OPEN",
        "opened_at": _now(), "closed_at": None,
        "exit_price": None, "exit_value": None,
        "pnl": None, "pnl_pct": None,
    })
    return ref.id


def close_paper_trade(trade_id, exit_price):
    doc_ref = _db.collection("paper_trades").document(str(trade_id))
    t = doc_ref.get()
    if not t.exists:
        return None
    td = t.to_dict()
    exit_value = td["qty"] * exit_price
    pnl = exit_value - td["invested"]
    pnl_pct = (pnl / td["invested"] * 100) if td["invested"] else 0
    doc_ref.update({
        "exit_price": exit_price, "exit_value": exit_value,
        "pnl": pnl, "pnl_pct": pnl_pct,
        "status": "CLOSED", "closed_at": _now(),
    })
    return {"pnl": pnl, "pnl_pct": pnl_pct, "exit_value": exit_value}


def list_paper_trades(status=None, style=None, limit=500):
    ref = _db.collection("paper_trades")
    if status:
        ref = ref.where("status", "==", status)
    if style:
        ref = ref.where("style", "==", style)
    docs = ref.order_by("opened_at", direction=firestore.Query.DESCENDING).limit(limit).get()
    return [_doc_to_dict(d) for d in docs]


def paper_summary(style=None):
    trades = list_paper_trades(style=style, limit=10000)
    closed = [t for t in trades if t["status"] == "CLOSED"]
    open_t = [t for t in trades if t["status"] == "OPEN"]
    total_pnl = sum(t["pnl"] or 0 for t in closed)
    total_invested = sum(t["invested"] or 0 for t in closed)
    pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0
    wins = sum(1 for t in closed if (t["pnl"] or 0) > 0)
    losses = sum(1 for t in closed if (t["pnl"] or 0) < 0)
    return {
        "open_count": len(open_t),
        "closed_count": len(closed),
        "total_invested": round(total_invested, 2),
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "wins": wins, "losses": losses,
        "win_rate": round((wins / len(closed) * 100), 2) if closed else 0,
    }


# ------------------------------------------------------------------ #
# Alerts
# ------------------------------------------------------------------ #
def add_alert(user_id, ticker, alert_type, threshold, note=""):
    _db.collection("alerts").add({
        "user_id": str(user_id), "ticker": ticker,
        "alert_type": alert_type, "threshold": threshold,
        "note": note, "active": True,
        "created_at": _now(), "triggered_at": None,
    })


def list_alerts(user_id, active_only=True):
    ref = _db.collection("alerts").where("user_id", "==", str(user_id))
    if active_only:
        ref = ref.where("active", "==", True)
    docs = ref.order_by("created_at", direction=firestore.Query.DESCENDING).get()
    return [_doc_to_dict(d) for d in docs]


def trigger_alert(alert_id):
    _db.collection("alerts").document(str(alert_id)).update({
        "active": False, "triggered_at": _now(),
    })


def delete_alert(user_id, alert_id):
    doc = _db.collection("alerts").document(str(alert_id)).get()
    if doc.exists and doc.to_dict().get("user_id") == str(user_id):
        _db.collection("alerts").document(str(alert_id)).delete()


# ------------------------------------------------------------------ #
# Notifications
# ------------------------------------------------------------------ #
def push_notification(user_id, title, body, severity="info"):
    _db.collection("notifications").add({
        "user_id": str(user_id), "title": title,
        "body": body, "severity": severity,
        "seen": False, "snoozed_until": None,
        "created_at": _now(),
    })


def list_notifications(user_id, unread_only=False, limit=100):
    ref = _db.collection("notifications").where("user_id", "==", str(user_id))
    if unread_only:
        ref = ref.where("seen", "==", False)
    docs = ref.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit).get()
    return [_doc_to_dict(d) for d in docs]


def mark_notification_seen(nid):
    _db.collection("notifications").document(str(nid)).update({"seen": True})


def snooze_notification(nid, snooze_iso):
    _db.collection("notifications").document(str(nid)).update({"snoozed_until": snooze_iso})


# ------------------------------------------------------------------ #
# ML weights
# ------------------------------------------------------------------ #
def get_ml_weights():
    docs = _db.collection("ml_weights").get()
    return {d.id: _doc_to_dict(d) for d in docs}


def update_ml_weight(indicator, weight, win, loss):
    ref = _db.collection("ml_weights").document(indicator)
    doc = ref.get()
    if doc.exists:
        cur = doc.to_dict()
        ref.update({
            "weight": weight,
            "wins": cur.get("wins", 0) + win,
            "losses": cur.get("losses", 0) + loss,
            "last_updated": _now(),
        })


# ------------------------------------------------------------------ #
# Watchlist
# ------------------------------------------------------------------ #
def get_watchlist(user_id, market=None):
    ref = _db.collection("watchlist").where("user_id", "==", str(user_id))
    if market:
        ref = ref.where("market", "==", market)
    docs = ref.order_by("ticker").get()
    return [_doc_to_dict(d) for d in docs]


def add_to_watchlist(user_id, ticker, market):
    _db.collection("watchlist").add({
        "user_id": str(user_id), "ticker": ticker,
        "market": market, "added_at": _now(),
    })


def remove_from_watchlist(user_id, wid):
    doc = _db.collection("watchlist").document(str(wid)).get()
    if doc.exists and doc.to_dict().get("user_id") == str(user_id):
        _db.collection("watchlist").document(str(wid)).delete()
