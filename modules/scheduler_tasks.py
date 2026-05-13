"""Scheduler tasks — previously run by APScheduler, now called by Vercel Cron endpoints."""
import logging
from modules import firebase_db as db
from modules.data_fetcher import get_quote

log = logging.getLogger(__name__)


def evaluate_alerts():
    """Walk all active alerts; fire + push notification if price condition met."""
    alerts = []
    # Get all active alerts across all users
    try:
        from modules.firebase_db import _db
        from firebase_admin import firestore
        docs = _db.collection("alerts").where("active", "==", True).get()
        alerts = [doc.to_dict() | {"id": doc.id} for doc in docs]
    except Exception as e:
        log.error("evaluate_alerts error: %s", e)
        return

    for a in alerts:
        q = get_quote(a["ticker"])
        price = q.get("price")
        if price is None:
            continue
        fired = False
        msg = ""
        if a["alert_type"] == "ABOVE" and price >= a["threshold"]:
            fired = True
            msg = f"{a['ticker']} is above ₹{a['threshold']} (now ₹{price})"
        elif a["alert_type"] == "BELOW" and price <= a["threshold"]:
            fired = True
            msg = f"{a['ticker']} is below ₹{a['threshold']} (now ₹{price})"
        if fired:
            db.trigger_alert(a["id"])
            db.push_notification(
                user_id=a["user_id"],
                title=f"Alert: {a['ticker']}",
                body=msg + (f" — Note: {a['note']}" if a.get("note") else ""),
                severity="warn",
            )


def check_near_decision():
    """For each open recommendation, push notification when price is within 1% of T1/T2/SL."""
    recs = db.list_recommendations(status="OPEN", limit=500)
    for r in recs:
        q = get_quote(r["ticker"])
        price = q.get("price")
        if price is None:
            continue
        levels = [
            ("Target 1", r.get("target1")),
            ("Target 2", r.get("target2")),
            ("Stop Loss", r.get("stop_loss")),
        ]
        for name, lv in levels:
            if not lv:
                continue
            if abs(price - lv) / lv <= 0.01:
                db.push_notification(
                    user_id="1",
                    title=f"{r['ticker']} near {name}",
                    body=(f"{r['ticker']} is at ₹{price:.2f} — within 1% of "
                          f"{name} (₹{lv:.2f}). Consider action."),
                    severity="critical",
                )
