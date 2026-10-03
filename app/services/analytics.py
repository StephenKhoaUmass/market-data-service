"""Stats computed from daily closes.

Volatility and anomaly z-scores use a prior window that excludes the current
return, so a bar is not part of its own baseline. The direction model is fit
on earlier rows and scored only on later rows.
"""

import math

import numpy as np
from sklearn.linear_model import LogisticRegression

VOL_WINDOW = 20
ANOMALY_WINDOW = 20
ANOMALY_Z = 2.0
TRADING_DAYS = 252
FEATURE_FAST = 5
FEATURE_SLOW = 20
MIN_MODEL_ROWS = 80
# Fixed before any test-set score. The middle slice chooses one of these.
# The last 30% is scored only for the chosen rule.
CANDIDATES = (
    {"name": "next_day", "horizon": 1, "min_confidence": 0.50},
    {"name": "five_day", "horizon": 5, "min_confidence": 0.50},
    {"name": "ten_day", "horizon": 10, "min_confidence": 0.50},
    {"name": "next_day_conf_0.55", "horizon": 1, "min_confidence": 0.55},
    {"name": "next_day_conf_0.60", "horizon": 1, "min_confidence": 0.60},
    {"name": "five_day_conf_0.55", "horizon": 5, "min_confidence": 0.55},
)
MIN_COVERAGE = 0.30
MIN_ACTED = 30


def simple_returns(prices: list[float]) -> np.ndarray:
    arr = np.asarray(prices, dtype=float)
    if arr.size < 2:
        return np.array([], dtype=float)
    return arr[1:] / arr[:-1] - 1.0


def latest_moving_average(prices: list[float], window: int = VOL_WINDOW):
    if len(prices) < window:
        return None
    return round(float(np.mean(prices[-window:])), 4)


def latest_volatility(prices: list[float], window: int = VOL_WINDOW):
    returns = simple_returns(prices)
    if returns.size < window:
        return None
    daily = float(np.std(returns[-window:], ddof=1))
    return {
        "window": window,
        "daily_std": round(daily, 6),
        "annualized": round(daily * math.sqrt(TRADING_DAYS), 6),
        "annualization": "daily_std * sqrt(252)",
    }


def _as_date(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def anomaly_flags(
    dates: list,
    prices: list[float],
    window: int = ANOMALY_WINDOW,
    threshold: float = ANOMALY_Z,
) -> list[dict]:
    """Flag a return when its |z| versus the previous `window` returns is high."""
    returns = simple_returns(prices)
    flags = []
    for j in range(window, len(returns)):
        prior = returns[j - window:j]
        sigma = float(np.std(prior, ddof=1))
        if sigma == 0 or math.isnan(sigma):
            continue
        mu = float(np.mean(prior))
        z = (float(returns[j]) - mu) / sigma
        if abs(z) >= threshold:
            flags.append({
                "date": _as_date(dates[j + 1]),
                "return": round(float(returns[j]), 6),
                "z": round(z, 3),
            })
    return flags


def _examples(prices: list[float], horizon: int):
    """Rows use only information available at that close. The label is the sign of the next `horizon` closes."""
    returns = simple_returns(prices)
    features = []
    labels = []
    for j in range(FEATURE_SLOW - 1, len(returns) - horizon):
        slow = returns[j - FEATURE_SLOW + 1:j + 1]
        fast = returns[j - FEATURE_FAST + 1:j + 1]
        window = returns[j + 1:j + 1 + horizon]
        forward = float(np.prod(1.0 + window) - 1.0)
        features.append([
            float(returns[j]),
            float(np.mean(fast)),
            float(np.std(slow, ddof=1)),
        ])
        labels.append(1 if forward > 0 else 0)
    if not features:
        return np.empty((0, 3)), np.empty((0,), dtype=int)
    return np.asarray(features, dtype=float), np.asarray(labels, dtype=int)


def _predict(x_train, y_train, x_eval, min_confidence: float):
    majority = 1 if float(y_train.mean()) >= 0.5 else 0
    if np.unique(y_train).size < 2:
        predicted = np.full(len(x_eval), majority, dtype=int)
        acted = np.ones(len(x_eval), dtype=bool)
        return predicted, acted, "training labels had one class, so the prediction is that class"
    mu = x_train.mean(axis=0)
    sigma = x_train.std(axis=0)
    sigma = np.where(sigma == 0, 1.0, sigma)
    model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=500)
    model.fit((x_train - mu) / sigma, y_train)
    proba = model.predict_proba((x_eval - mu) / sigma)
    class_list = list(model.classes_)
    p_up = proba[:, class_list.index(1)] if 1 in class_list else np.zeros(len(x_eval))
    confidence = np.maximum(p_up, 1.0 - p_up)
    predicted = (p_up >= 0.5).astype(int)
    acted = confidence + 1e-12 >= min_confidence
    return predicted, acted, None


def _score_slice(y_true, predicted, acted, y_train, last_return, stride: int) -> dict:
    positions = np.arange(0, len(y_true), stride)
    positions = positions[acted[positions]]
    n_possible = int(np.ceil(len(y_true) / stride))
    coverage = float(len(positions) / n_possible) if n_possible else 0.0
    if len(positions) == 0:
        return {
            "n_acted": 0,
            "coverage": 0.0,
            "accuracy": None,
            "majority_baseline_accuracy": None,
            "persistence_baseline_accuracy": None,
            "margin": None,
            "standard_error": None,
            "up_rate": None,
        }
    actual = y_true[positions]
    chosen = predicted[positions]
    accuracy = float(np.mean(chosen == actual))
    majority = 1 if float(y_train.mean()) >= 0.5 else 0
    majority_accuracy = float(np.mean(np.full(len(positions), majority) == actual))
    persist = (last_return[positions] > 0).astype(int)
    persist_accuracy = float(np.mean(persist == actual))
    standard_error = math.sqrt(max(accuracy * (1.0 - accuracy), 0.0) / len(positions))
    return {
        "n_acted": int(len(positions)),
        "coverage": round(coverage, 4),
        "accuracy": round(accuracy, 4),
        "majority_baseline_accuracy": round(majority_accuracy, 4),
        "persistence_baseline_accuracy": round(persist_accuracy, 4),
        "margin": round(accuracy - majority_accuracy, 4),
        "standard_error": round(standard_error, 4),
        "up_rate": round(float(actual.mean()), 4),
    }


def _validation_row(name: str, horizon: int, min_confidence: float, prices: list[float]):
    features, labels = _examples(prices, horizon)
    n = int(labels.size)
    train_end = int(n * 0.50)
    val_end = int(n * 0.70)
    if train_end < 20 or val_end - train_end < 10 or n - val_end < 10:
        return None
    x_train, y_train = features[:train_end], labels[:train_end]
    x_val, y_val = features[train_end:val_end], labels[train_end:val_end]
    predicted, acted, fit_note = _predict(x_train, y_train, x_val, min_confidence)
    scored = _score_slice(y_val, predicted, acted, y_train, x_val[:, 0], horizon)
    eligible = (
        scored["n_acted"] >= MIN_ACTED
        and scored["coverage"] >= MIN_COVERAGE
        and scored["margin"] is not None
    )
    return {
        "name": name,
        "horizon": horizon,
        "min_confidence": min_confidence,
        "n_train": train_end,
        "n_validation": int(val_end - train_end),
        "fit_note": fit_note,
        "eligible": eligible,
        **scored,
    }


def _test_score(candidate: dict, prices: list[float]) -> dict:
    features, labels = _examples(prices, candidate["horizon"])
    n = int(labels.size)
    train_end = int(n * 0.50)
    val_end = int(n * 0.70)
    x_train, y_train = features[:train_end], labels[:train_end]
    x_test, y_test = features[val_end:], labels[val_end:]
    predicted, acted, fit_note = _predict(
        x_train, y_train, x_test, candidate["min_confidence"]
    )
    scored = _score_slice(y_test, predicted, acted, y_train, x_test[:, 0], candidate["horizon"])
    margin = scored["margin"]
    standard_error = scored["standard_error"]
    beats = (
        margin is not None
        and standard_error is not None
        and margin > 2 * standard_error
    )
    return {
        "n_train": train_end,
        "n_test": int(n - val_end),
        "fit_note": fit_note,
        "beats_majority_baseline": beats,
        "train_up_rate": round(float(y_train.mean()), 4),
        **scored,
    }


def evaluate_direction_model(prices: list[float]) -> dict:
    """Pick a horizon and confidence rule on the middle 20%, then score the last 30% once."""
    probe, _ = _examples(prices, 1)
    if int(probe.shape[0]) < MIN_MODEL_ROWS:
        return {"status": "insufficient_history", "n": int(probe.shape[0])}

    validation = []
    for candidate in CANDIDATES:
        row = _validation_row(
            candidate["name"], candidate["horizon"], candidate["min_confidence"], prices
        )
        if row is not None:
            validation.append(row)
    if not validation:
        return {"status": "insufficient_history", "n": int(probe.shape[0])}

    eligible = [row for row in validation if row["eligible"]]
    if eligible:
        chosen = max(eligible, key=lambda row: (row["margin"], row["coverage"]))
        adopted = chosen["margin"] > 2 * chosen["standard_error"]
    else:
        chosen = next(row for row in validation if row["name"] == "next_day")
        adopted = False
    if not adopted:
        chosen = next(row for row in validation if row["name"] == "next_day")

    selected = next(candidate for candidate in CANDIDATES if candidate["name"] == chosen["name"])
    held_out = _test_score(selected, prices)
    return {
        "status": "ok",
        "split": "chronological 50% fit, 20% rule selection, 30% test scored once",
        "features": ["last_return", "mean_return_5", "std_return_20"],
        "selection_rule": (
            "On the validation slice, keep a candidate only if coverage is at least 30%, "
            "at least 30 non-overlapping periods are scored, and the accuracy gap over "
            "always-up exceeds two standard errors. Otherwise keep next-day direction."
        ),
        "adopted_new_rule": adopted and selected["name"] != "next_day",
        "selected_candidate": selected["name"],
        "validation": [
            {
                "name": row["name"],
                "horizon": row["horizon"],
                "min_confidence": row["min_confidence"],
                "n_acted": row["n_acted"],
                "coverage": row["coverage"],
                "accuracy": row["accuracy"],
                "majority_baseline_accuracy": row["majority_baseline_accuracy"],
                "margin": row["margin"],
                "standard_error": row["standard_error"],
                "eligible": row["eligible"],
            }
            for row in validation
        ],
        "n_train": held_out["n_train"],
        "n_test": held_out["n_test"],
        "test_accuracy": held_out["accuracy"],
        "majority_baseline_accuracy": held_out["majority_baseline_accuracy"],
        "persistence_baseline_accuracy": held_out["persistence_baseline_accuracy"],
        "accuracy_minus_majority": held_out["margin"],
        "accuracy_standard_error": held_out["standard_error"],
        "beats_majority_baseline": held_out["beats_majority_baseline"],
        "train_up_rate": held_out["train_up_rate"],
        "test_up_rate": held_out["up_rate"],
        "test_coverage": held_out["coverage"],
        "test_n_acted": held_out["n_acted"],
        "fit_note": held_out["fit_note"],
    }


def build_report(symbol: str, dates: list, prices: list[float]) -> dict:
    if len(prices) < 2:
        return {"symbol": symbol, "bars": len(prices), "error": "not enough daily bars"}

    returns = simple_returns(prices)
    eligible = max(int(returns.size) - ANOMALY_WINDOW, 0)
    flags = anomaly_flags(dates, prices)
    return {
        "symbol": symbol,
        "bars": len(prices),
        "start": _as_date(dates[0]),
        "end": _as_date(dates[-1]),
        "last_close": round(float(prices[-1]), 4),
        "moving_average_20": latest_moving_average(prices),
        "volatility": latest_volatility(prices),
        "anomalies": {
            "rule": "abs(z) >= 2 versus the prior 20 daily returns",
            "count": len(flags),
            "eligible_bars": eligible,
            "rate": round(len(flags) / eligible, 4) if eligible else None,
            "latest": flags[-5:],
        },
        "direction_model": evaluate_direction_model(prices),
    }
