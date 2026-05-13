"""Self-learning ML engine — Vercel/Firebase edition.

Combines:
  • Supervised: SGDClassifier trained on closed trades (win/loss)
  • Reinforcement: per-indicator weight nudges based on trade outcomes
  • Unsupervised: KMeans setup archetypes

On Vercel, .pkl files cannot be persisted to disk. Models are stored
as base64 JSON blobs inside Firestore (ml_model_blob / cluster_model_blob docs).
"""
import base64
import json
import logging
import math
import pickle
from datetime import datetime

import numpy as np

from modules import firebase_db as db

log = logging.getLogger(__name__)

LEARNING_RATE = 0.05
WEIGHT_FLOOR = 0.3
WEIGHT_CAP = 2.5


# ------------------------------------------------------------------ #
# Firestore model persistence helpers
# ------------------------------------------------------------------ #
def _save_model_blob(key, obj):
    """Pickle obj and store as base64 string in Firestore."""
    try:
        blob = base64.b64encode(pickle.dumps(obj)).decode()
        _db_col().document(key).set({"blob": blob, "updated_at": datetime.utcnow().isoformat()})
    except Exception as e:
        log.warning("_save_model_blob error: %s", e)


def _load_model_blob(key):
    """Load pickled object from Firestore blob. Returns None if missing."""
    try:
        doc = _db_col().document(key).get()
        if doc.exists:
            blob = doc.to_dict().get("blob")
            if blob:
                return pickle.loads(base64.b64decode(blob))
    except Exception as e:
        log.warning("_load_model_blob error: %s", e)
    return None


def _db_col():
    from firebase_admin import firestore as _fs
    return _fs.client().collection("ml_models")


# ------------------------------------------------------------------ #
# Signal extraction
# ------------------------------------------------------------------ #
def _signals_from_rec(rec):
    rationale = (rec.get("rationale") or "").lower()
    sigs = []
    if "moving average" in rationale or "ema" in rationale: sigs.append("ema_cross")
    if "rsi" in rationale or "strength meter" in rationale: sigs.append("rsi")
    if "macd" in rationale or "momentum" in rationale: sigs.append("macd")
    if "volume" in rationale: sigs.append("volume_surge")
    if "trend strength" in rationale or "adx" in rationale: sigs.append("adx")
    if "bollinger" in rationale: sigs.append("bb")
    if "pattern" in rationale or rec.get("pattern"): sigs.append("pattern")
    if "multiple timeframes" in rationale: sigs.append("multi_tf")
    if not sigs:
        sigs = ["pattern"]
    return sigs


# ------------------------------------------------------------------ #
# Reinforcement + self-notes
# ------------------------------------------------------------------ #
def learn_from_trade(rec_id, outcome, pnl_pct):
    """Called after every paper-trade close. Updates weights & self-notes."""
    rec = _load_rec(rec_id)
    if not rec:
        return
    sigs = _signals_from_rec(rec)
    weights = db.get_ml_weights()
    for ind in sigs:
        if ind not in weights:
            continue
        cur = weights[ind]["weight"]
        if outcome == "WIN":
            new = cur + LEARNING_RATE * (1 - cur / WEIGHT_CAP) * max(0.5, pnl_pct / 5)
            db.update_ml_weight(ind, min(WEIGHT_CAP, new), 1, 0)
        elif outcome == "LOSS":
            new = cur - LEARNING_RATE * (cur - WEIGHT_FLOOR) * max(0.5, abs(pnl_pct) / 5)
            db.update_ml_weight(ind, max(WEIGHT_FLOOR, new), 0, 1)
        else:
            db.update_ml_weight(ind, cur, 0, 0)

    if outcome == "WIN":
        lesson = (
            f"On {rec['ticker']}, the combination of {', '.join(sigs)} produced a "
            f"+{pnl_pct:.2f}% gain. Boosting confidence in these signals."
        )
        cat = "win_pattern"
    elif outcome == "LOSS":
        lesson = (
            f"On {rec['ticker']}, signals {', '.join(sigs)} failed (loss "
            f"{pnl_pct:.2f}%). Reducing weight of these indicators. "
            f"Next time, look for confirmation from more timeframes before entering."
        )
        cat = "loss_lesson"
    else:
        lesson = f"Neutral exit on {rec['ticker']} — no clear lesson, no weight change."
        cat = "neutral"

    db.add_self_note(
        note=f"Trade {rec['ticker']} closed: outcome={outcome}, P&L={pnl_pct:.2f}%",
        lesson=lesson, category=cat,
    )

    try:
        retrain_models()
    except Exception as e:
        log.warning("retrain err: %s", e)


# ------------------------------------------------------------------ #
# Supervised + Unsupervised retraining (Firestore data source)
# ------------------------------------------------------------------ #
def _gather_training_data():
    """Build feature matrix from Firestore audit log + recommendations."""
    try:
        audit_rows = db.list_audit(limit=500)
        X, y = [], []
        for a in audit_rows:
            rec_id = a.get("rec_id")
            if not rec_id or a.get("outcome") is None:
                continue
            rec = _load_rec(rec_id)
            if not rec:
                continue
            X.append([
                rec.get("score") or 5,
                rec.get("rr_ratio") or 1,
                rec.get("holding_days") or 5,
                1 if rec.get("style") == "swing" else 0,
            ])
            y.append(1 if a["outcome"] == "WIN" else 0)
        return np.array(X), np.array(y)
    except Exception as e:
        log.warning("_gather_training_data error: %s", e)
        return np.array([]), np.array([])


def retrain_models():
    """Refit supervised + cluster models and persist to Firestore."""
    X, y = _gather_training_data()
    if len(X) < 10:
        return False
    try:
        from sklearn.linear_model import SGDClassifier
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X)
        clf = SGDClassifier(loss="log_loss", max_iter=200, learning_rate="optimal")
        clf.fit(Xs, y)
        _save_model_blob("clf_model", {"clf": clf, "scaler": scaler})
        if len(X) >= 6:
            n_clusters = min(4, max(2, len(X) // 5))
            km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
            km.fit(Xs)
            _save_model_blob("cluster_model", {"km": km, "scaler": scaler})
        return True
    except Exception as e:
        log.warning("retrain models err: %s", e)
        return False


def predict_win_probability(score, rr_ratio, holding_days, style):
    """Use the trained classifier to predict P(win) for a fresh setup."""
    obj = _load_model_blob("clf_model")
    if obj is None:
        # Heuristic fallback when no model trained yet
        base = 0.5 + (score - 5) * 0.05 + (rr_ratio - 1) * 0.03
        return float(max(0.05, min(0.95, base)))
    try:
        x = np.array([[score, rr_ratio, holding_days, 1 if style == "swing" else 0]])
        xs = obj["scaler"].transform(x)
        if hasattr(obj["clf"], "predict_proba"):
            return float(obj["clf"].predict_proba(xs)[0][1])
        return float(1 / (1 + math.exp(-obj["clf"].decision_function(xs)[0])))
    except Exception:
        return 0.5


def _load_rec(rec_id):
    try:
        recs = db.list_recommendations(limit=1000)
        for r in recs:
            if str(r.get("id")) == str(rec_id):
                return r
    except Exception:
        pass
    return None
