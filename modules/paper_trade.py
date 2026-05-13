"""Paper trading game: auto-open ₹1L per recommendation, close when T1/T2/SL hit."""
from datetime import datetime, timedelta
import logging

from config import Config
from modules import firebase_db as db
from modules.data_fetcher import get_quote

log = logging.getLogger(__name__)


def auto_open_paper_for_rec(rec_id, rec):
    """When a recommendation is generated, place a dummy ₹1L paper trade."""
    if not rec.get("entry"):
        return None
    return db.open_paper_trade(
        rec_id=rec_id, ticker=rec["ticker"], style=rec["style"],
        side=rec.get("side", "BUY"),
        entry_price=rec["entry"], invested=Config.PAPER_CAPITAL_PER_REC,
    )


def evaluate_open_trades():
    """Mark to market every open trade; close when T1/T2/SL hit or time-exit."""
    open_trades = db.list_paper_trades(status="OPEN", limit=10000)
    closed_count = 0
    audit_entries = []

    for t in open_trades:
        rec = _get_rec(t["rec_id"])
        if not rec:
            continue
        q = get_quote(t["ticker"])
        cur = q.get("price")
        if cur is None:
            continue

        outcome = None
        reason = None
        final_price = None
        side = t.get("side", "BUY")

        if side == "BUY":
            if cur >= rec.get("target2", 0):
                outcome, reason, final_price = "WIN", "Target 2 hit", rec["target2"]
            elif cur >= rec.get("target1", 0):
                outcome, reason, final_price = "WIN", "Target 1 hit", rec["target1"]
            elif cur <= rec.get("stop_loss", 0):
                outcome, reason, final_price = "LOSS", "Stop loss hit", rec["stop_loss"]
        else:
            if cur <= rec.get("target2", float("inf")):
                outcome, reason, final_price = "WIN", "Short target 2 hit", rec["target2"]
            elif cur <= rec.get("target1", float("inf")):
                outcome, reason, final_price = "WIN", "Short target 1 hit", rec["target1"]
            elif cur >= rec.get("stop_loss", float("inf")):
                outcome, reason, final_price = "LOSS", "Short stop loss hit", rec["stop_loss"]

        # Time-exit
        opened = datetime.fromisoformat(t["opened_at"])
        days = (datetime.utcnow() - opened).days
        max_days = 1 if t.get("style") == "intraday" else 10
        if not outcome and days >= max_days:
            outcome = (
                "NEUTRAL" if abs(cur - t["entry_price"]) / t["entry_price"] < 0.005
                else ("WIN" if cur > t["entry_price"] else "LOSS")
            )
            reason = f"Time-based exit after {days} day(s)"
            final_price = cur

        if outcome:
            res = db.close_paper_trade(t["id"], final_price)
            if res:
                db.close_recommendation(
                    t["rec_id"],
                    "T2_HIT" if "Target 2" in reason else
                    "T1_HIT" if "Target 1" in reason else
                    "SL_HIT" if "stop" in reason.lower() else "TIME_EXIT",
                    res["pnl_pct"],
                )
                db.log_audit(
                    rec_id=t["rec_id"], ticker=t["ticker"], style=t.get("style", ""),
                    invested=t["invested"], final_value=res["exit_value"],
                    pnl_pct=res["pnl_pct"], outcome=outcome, reason=reason,
                )
                closed_count += 1
                audit_entries.append({
                    "ticker": t["ticker"], "outcome": outcome,
                    "pnl_pct": res["pnl_pct"], "reason": reason,
                })
                from modules.ml_engine import learn_from_trade
                learn_from_trade(t["rec_id"], outcome, res["pnl_pct"])

    return {"closed": closed_count, "details": audit_entries}


def _get_rec(rec_id):
    if rec_id is None:
        return None
    doc = db._db.collection("recommendations").document(str(rec_id)).get()
    if doc.exists:
        d = doc.to_dict()
        d["id"] = doc.id
        return d
    return None


def manual_swap(trade_id, new_ticker, new_entry_price):
    """User-driven 'swap dummy money to a different stock' game move."""
    doc = db._db.collection("paper_trades").document(str(trade_id)).get()
    if not doc.exists:
        return None
    t = doc.to_dict()
    t["id"] = doc.id
    if t.get("status") != "OPEN":
        return None

    q = get_quote(t["ticker"])
    if q.get("price"):
        db.close_paper_trade(trade_id, q["price"])
        db.log_audit(
            rec_id=t["rec_id"], ticker=t["ticker"], style=t.get("style", ""),
            invested=t["invested"],
            final_value=t["qty"] * q["price"],
            pnl_pct=((t["qty"] * q["price"] - t["invested"]) / t["invested"] * 100),
            outcome="NEUTRAL", reason="User swapped to another stock",
        )

    return db.open_paper_trade(
        rec_id=t["rec_id"], ticker=new_ticker,
        style=t.get("style", "swing"), side="BUY",
        entry_price=new_entry_price,
        invested=Config.PAPER_CAPITAL_PER_REC,
    )
