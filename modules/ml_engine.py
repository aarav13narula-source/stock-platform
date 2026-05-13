"""Self-learning engine.

Combines:
  • Supervised: tracks indicator weights and adjusts them per win/loss
    (online stochastic learning with sklearn SGDClassifier on tabular features).
  • Reinforcement: per-indicator weight nudges based on trade outcomes (REINFORCE-style).
  • Unsupervised: KMeans clusters past trades into 'setup archetypes' and logs which
    clusters perform best/worst so the engine learns to avoid bad archetypes.

After every closed paper trade the engine:
  1. logs a self-note (visible in the Self-Audit tab),
  2. adjusts indicator weights,
  3. refits the supervised model and the cluster map.
"""
import json
import logging
import math
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

from config import DATA_DIR
from modules import database as db

log = logging.getLogger(__name__)

MODEL_PATH = DATA_DIR / "ml_model.pkl"
CLUSTER_PATH = DATA_DIR / "cluster_model.pkl"


# ------------------------------------------------------------------ #
# Reinforcement weight updates
# ------------------------------------------------------------------ #
LEARNING_RATE = 0.05
WEIGHT_FLOOR = 0.3
WEIGHT_CAP = 2.5


def _signals_from_rec(rec):
    """Reconstruct which indicators contributed to a recommendation."""
    # Very lightweight reconstruction from rationale + pattern fields
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


def learn_from_trade(rec_id, outcome, pnl_pct):
    """Called after every paper-trade close. Updates weights & self-notes."""
    rec = _load_rec(rec_id)
    if not rec:
        return
    sigs = _signals_from_rec(rec)
    weights = db.get_ml_weights()
    # Reinforcement nudges
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

    # Generate a plain-English self-note
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

    # Retrain supervised + cluster models if enough data
    try:
        retrain_models()
    except Exception as e:
        log.warning("retrain err: %s", e)


# ------------------------------------------------------------------ #
# Supervised + Unsupervised retraining
# ------------------------------------------------------------------ #
def _gather_training_data():
    """Build a small feature matrix from the audit log + recommendations table."""
    from modules.database import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT r.score, r.rr_ratio, r.holding_days, r.style,
                      a.outcome, a.pnl_pct
               FROM recommendations r JOIN audit_log a ON r.id = a.rec_id
               WHERE a.outcome IS NOT NULL"""
        ).fetchall()
    X, y = [], []
    for r in rows:
        X.append([
            r["score"] or 5,
            r["rr_ratio"] or 1,
            r["holding_days"] or 5,
            1 if r["style"] == "swing" else 0,
        ])
        y.append(1 if r["outcome"] == "WIN" else 0)
    return np.array(X), np.array(y)


def retrain_models():
    """Refit supervised + cluster models if enough samples."""
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
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({"clf": clf, "scaler": scaler}, f)
        # Unsupervised cluster of all setups
        if len(X) >= 6:
            n_clusters = min(4, max(2, len(X) // 5))
            km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
            km.fit(Xs)
            with open(CLUSTER_PATH, "wb") as f:
                pickle.dump({"km": km, "scaler": scaler}, f)
        return True
    except Exception as e:
        log.warning("retrain models err: %s", e)
        return False


def predict_win_probability(score, rr_ratio, holding_days, style):
    """Use the trained classifier to predict P(win) for a fresh setup."""
    if not MODEL_PATH.exists():
        # Heuristic fallback
        base = 0.5 + (score - 5) * 0.05 + (rr_ratio - 1) * 0.03
        return float(max(0.05, min(0.95, base)))
    try:
        with open(MODEL_PATH, "rb") as f:
            obj = pickle.load(f)
        x = np.array([[score, rr_ratio, holding_days, 1 if style == "swing" else 0]])
        xs = obj["scaler"].transform(x)
        if hasattr(obj["clf"], "predict_proba"):
            return float(obj["clf"].predict_proba(xs)[0][1])
        return float(1 / (1 + math.exp(-obj["clf"].decision_function(xs)[0])))
    except Exception:
        return 0.5


def _load_rec(rec_id):
    from modules.database import get_conn
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM recommendations WHERE id=?", (rec_id,))
        r = cur.fetchone()
        return dict(r) if r else None
