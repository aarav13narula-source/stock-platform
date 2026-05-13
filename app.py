"""Flask entry point for the Smartest Stock Analysis Platform — Vercel + Firebase edition."""
import io
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import (Flask, render_template, request, redirect, url_for, jsonify,
                   send_file, flash, abort)
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config

# Use firebase_db instead of database (SQLite)
from modules import firebase_db as db

from modules.data_fetcher import (get_quote, get_quotes_bulk, get_ohlcv,
                                  get_indices_snapshot, get_crypto_market)
from modules.analyzer import compute_indicators, detect_patterns, score_timeframe
from modules.recommender import generate_recommendations, analyze_ticker
from modules.paper_trade import evaluate_open_trades, manual_swap
from modules.ml_engine import predict_win_probability
from modules.news_engine import aggregate_news, aggregate_social, media_leaderboard
from modules.reports import to_csv, build_pdf

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
app.config.from_object(Config)

login_mgr = LoginManager(app)
login_mgr.login_view = "login"


class User(UserMixin):
    def __init__(self, row):
        # Firestore uses string doc IDs; keep as-is
        self.id = str(row["id"])
        self.username = row["username"]
        self.theme = row.get("theme", "light")


@login_mgr.user_loader
def load_user(uid):
    r = db.get_user_by_id(uid)
    return User(r) if r else None


# ------------------------------------------------------------------ #
# Auth
# ------------------------------------------------------------------ #
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user_row = db.verify_password(username, password)
        if user_row:
            user = User(user_row)
            login_user(user, remember=True)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ------------------------------------------------------------------ #
# Cron endpoints (called by Vercel Cron Jobs — replace APScheduler)
# ------------------------------------------------------------------ #
@app.route("/cron/mtm")
def cron_mtm():
    """Mark-to-market: evaluate all open paper trades every 15 min."""
    result = evaluate_open_trades()
    log.info("Cron MTM: %s", result)
    return jsonify(result)


@app.route("/cron/alerts")
def cron_alerts():
    """Evaluate price alerts every minute."""
    from modules.scheduler_tasks import evaluate_alerts, check_near_decision
    evaluate_alerts()
    check_near_decision()
    return jsonify({"ok": True})


@app.route("/cron/ml")
def cron_ml():
    """Retrain ML weights every hour."""
    from modules.ml_engine import retrain_models
    retrain_models()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Dashboard
# ------------------------------------------------------------------ #
@app.route("/")
@login_required
def dashboard():
    indices = get_indices_snapshot(Config.INDEX_TICKERS)
    notifs = db.list_notifications(current_user.id, unread_only=True, limit=10)
    rec_count = len(db.list_recommendations(status="OPEN"))
    alert_count = len(db.list_alerts(current_user.id))
    stats = db.accuracy_stats()
    paper = db.paper_summary()
    return render_template("dashboard.html",
                           indices=indices, notifs=notifs,
                           rec_count=rec_count, alert_count=alert_count,
                           stats=stats, paper=paper,
                           theme=current_user.theme)


@app.route("/theme/<t>")
@login_required
def set_theme(t):
    if t in ("light", "dark"):
        db.update_theme(current_user.id, t)
        current_user.theme = t
    return redirect(request.referrer or url_for("dashboard"))


# ------------------------------------------------------------------ #
# Notifications
# ------------------------------------------------------------------ #
@app.route("/api/notifications")
@login_required
def api_notifications():
    notifs = db.list_notifications(current_user.id, unread_only=True, limit=20)
    return jsonify(notifs)


@app.route("/api/notifications/<nid>/seen", methods=["POST"])
@login_required
def mark_seen(nid):
    db.mark_notification_seen(nid)
    return jsonify({"ok": True})


@app.route("/api/notifications/<nid>/snooze", methods=["POST"])
@login_required
def snooze(nid):
    from datetime import timedelta
    snooze_until = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
    db.snooze_notification(nid, snooze_until)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Recommendations
# ------------------------------------------------------------------ #
@app.route("/recommendations")
@login_required
def recommendations():
    style = request.args.get("style")
    status = request.args.get("status", "OPEN")
    recs = db.list_recommendations(style=style, status=status)
    return render_template("recommendations.html", recs=recs,
                           style=style, status=status,
                           theme=current_user.theme)


@app.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    data = request.get_json() or {}
    market = data.get("market", "NSE")
    style = data.get("style", "swing")
    watchlist = db.get_watchlist(current_user.id, market=market)
    tickers = [w["ticker"] for w in watchlist]
    if not tickers:
        return jsonify({"error": "Empty watchlist"}), 400
    recs = generate_recommendations(tickers, market=market, style=style)
    saved = []
    for r in recs:
        rid = db.save_recommendation(r)
        from modules.paper_trade import auto_open_paper_for_rec
        auto_open_paper_for_rec(rid, r)
        saved.append(rid)
    return jsonify({"generated": len(saved)})


@app.route("/api/rec/<rec_id>/close", methods=["POST"])
@login_required
def api_close_rec(rec_id):
    data = request.get_json() or {}
    status = data.get("status", "TIME_EXIT")
    pnl = data.get("pnl_pct", 0.0)
    db.close_recommendation(rec_id, status, pnl)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Market & stock detail
# ------------------------------------------------------------------ #
@app.route("/market")
@login_required
def market():
    market_type = request.args.get("m", "NSE")
    watchlist = db.get_watchlist(current_user.id, market=market_type)
    tickers = [w["ticker"] for w in watchlist]
    quotes = get_quotes_bulk(tickers)
    return render_template("market.html", quotes=quotes, market=market_type,
                           watchlist=watchlist, theme=current_user.theme)


@app.route("/stock/<ticker>")
@login_required
def stock_detail(ticker):
    tf = request.args.get("tf", "1d")
    market = request.args.get("market", "NSE")
    ohlcv = get_ohlcv(ticker, timeframe=tf)
    indicators = compute_indicators(ohlcv) if not ohlcv.empty else {}
    patterns = detect_patterns(ohlcv) if not ohlcv.empty else []
    scores = score_timeframe(ohlcv)
    analysis = analyze_ticker(ticker, market)
    news = aggregate_news()
    if analysis and not analysis.get("rejected"):
        win_prob = predict_win_probability(
            score=analysis.get("score", 5.0),
            rr_ratio=analysis.get("rr_ratio", 2.0),
            holding_days=analysis.get("holding_days", 7),
            style=analysis.get("style", "swing"),
        )
    else:
        win_prob = 0.5
    return render_template("stock_detail.html", ticker=ticker, tf=tf,
                           indicators=indicators, patterns=patterns,
                           scores=scores, analysis=analysis,
                           news=news, win_prob=win_prob,
                           theme=current_user.theme)


# ------------------------------------------------------------------ #
# Watchlist management
# ------------------------------------------------------------------ #
@app.route("/api/watchlist/add", methods=["POST"])
@login_required
def add_watchlist():
    data = request.get_json() or {}
    ticker = data.get("ticker", "").upper().strip()
    market = data.get("market", "NSE")
    if not ticker:
        return jsonify({"error": "No ticker"}), 400
    db.add_to_watchlist(current_user.id, ticker, market)
    return jsonify({"ok": True})


@app.route("/api/watchlist/<wid>/remove", methods=["POST"])
@login_required
def remove_watchlist(wid):
    db.remove_from_watchlist(current_user.id, wid)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Alerts
# ------------------------------------------------------------------ #
@app.route("/alerts")
@login_required
def alerts():
    user_alerts = db.list_alerts(current_user.id)
    return render_template("alerts.html", alerts=user_alerts,
                           theme=current_user.theme)


@app.route("/api/alerts/add", methods=["POST"])
@login_required
def add_alert():
    data = request.get_json() or {}
    db.add_alert(
        user_id=current_user.id,
        ticker=data.get("ticker", "").upper(),
        alert_type=data.get("type", "ABOVE"),
        threshold=float(data.get("threshold", 0)),
        note=data.get("note", ""),
    )
    return jsonify({"ok": True})


@app.route("/api/alerts/<aid>/delete", methods=["POST"])
@login_required
def delete_alert(aid):
    db.delete_alert(current_user.id, aid)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Paper trading
# ------------------------------------------------------------------ #
@app.route("/paper_trade")
@login_required
def paper_trade():
    style = request.args.get("style")
    trades = db.list_paper_trades(style=style, limit=200)
    summary = db.paper_summary(style=style)
    return render_template("paper_trade.html", trades=trades,
                           summary=summary, style=style,
                           theme=current_user.theme)


@app.route("/api/paper/evaluate", methods=["POST"])
@login_required
def api_evaluate_trades():
    result = evaluate_open_trades()
    return jsonify(result)


@app.route("/api/paper/swap", methods=["POST"])
@login_required
def api_swap():
    data = request.get_json() or {}
    tid = data.get("trade_id")
    new_ticker = data.get("new_ticker", "").upper()
    new_price = float(data.get("new_price", 0))
    result = manual_swap(tid, new_ticker, new_price)
    return jsonify({"ok": bool(result), "new_trade_id": result})


# ------------------------------------------------------------------ #
# Self audit / notes
# ------------------------------------------------------------------ #
@app.route("/self_audit")
@login_required
def self_audit():
    notes = db.list_self_notes()
    stats = db.accuracy_stats()
    audit = db.list_audit(limit=200)
    return render_template("self_audit.html", notes=notes, stats=stats,
                           audit=audit, theme=current_user.theme)


@app.route("/api/notes/add", methods=["POST"])
@login_required
def add_note():
    data = request.get_json() or {}
    db.add_self_note(
        note=data.get("note", ""),
        lesson=data.get("lesson", ""),
        category=data.get("category", "pattern_failure"),
    )
    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Media / news
# ------------------------------------------------------------------ #
@app.route("/media")
@login_required
def media():
    ticker = request.args.get("ticker", "RELIANCE.NS")
    news = aggregate_news()
    social = aggregate_social()
    leaders = media_leaderboard()
    return render_template("media.html", ticker=ticker,
                           news=news, social=social, leaders=leaders,
                           theme=current_user.theme)


# ------------------------------------------------------------------ #
# Best picks
# ------------------------------------------------------------------ #
@app.route("/best_picks")
@login_required
def best_picks():
    audit = db.list_audit(limit=1000)
    top = sorted([r for r in audit if r["outcome"] == "WIN"],
                 key=lambda r: r["pnl_pct"] or 0, reverse=True)[:20]
    return render_template("best_picks.html", picks=top,
                           theme=current_user.theme)


# ------------------------------------------------------------------ #
# Reports
# ------------------------------------------------------------------ #
@app.route("/reports")
@login_required
def reports():
    return render_template("reports.html", theme=current_user.theme)


@app.route("/api/reports/csv")
@login_required
def report_csv():
    kind = request.args.get("kind", "recs")
    if kind == "recs":
        rows = db.list_recommendations(limit=500)
        headers = ["id", "ticker", "market", "style", "side", "entry",
                   "target1", "target2", "stop_loss", "score", "tier",
                   "status", "final_pnl_pct", "created_at"]
    elif kind == "audit":
        rows = db.list_audit(limit=500)
        headers = ["id", "ticker", "style", "invested", "final_value",
                   "pnl_pct", "outcome", "reason", "closed_at"]
    else:
        rows = db.list_paper_trades(limit=500)
        headers = ["id", "ticker", "style", "side", "invested",
                   "pnl", "pnl_pct", "status", "opened_at"]
    csv_data = to_csv(rows, headers)
    return send_file(
        io.BytesIO(csv_data.encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{kind}_report.csv",
    )


@app.route("/api/reports/pdf")
@login_required
def report_pdf():
    recs = db.list_recommendations(limit=200)
    audit = db.list_audit(limit=200)
    pdf_bytes = build_pdf("Stock Platform Report", [
        ("Open Recommendations", recs,
         ["ticker", "market", "style", "side", "entry", "target1",
          "stop_loss", "score", "tier", "status"]),
        ("Audit Log", audit,
         ["ticker", "style", "pnl_pct", "outcome", "reason", "closed_at"]),
    ])
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="platform_report.pdf",
    )


# ------------------------------------------------------------------ #
# JSON API — price data for charts
# ------------------------------------------------------------------ #
@app.route("/api/ohlcv/<ticker>")
@login_required
def api_ohlcv(ticker):
    tf = request.args.get("tf", "1d")
    df = get_ohlcv(ticker, timeframe=tf)
    if df is None or df.empty:
        return jsonify([])
    out = []
    for ts, row in df.iterrows():
        out.append({
            "t": ts.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(ts, "strftime") else str(ts),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row.get("Volume", 0)),
        })
    return jsonify(out)


# ------------------------------------------------------------------ #
# App factory
# ------------------------------------------------------------------ #
def create_app():
    db.init_db()
    # No APScheduler on Vercel — cron jobs handle scheduling via /cron/* routes
    return app


if __name__ == "__main__":
    create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
