from datetime import date, timedelta

from app.services.analytics import (
    anomaly_flags,
    build_report,
    evaluate_direction_model,
    latest_volatility,
)


def _dates(n):
    start = date(2020, 1, 1)
    return [start + timedelta(days=i) for i in range(n)]


def _prices_from_returns(start, returns):
    prices = [start]
    for ret in returns:
        prices.append(prices[-1] * (1 + ret))
    return prices


def test_volatility_matches_known_window():
    returns = [0.01, -0.01] * 10
    prices = _prices_from_returns(100.0, returns)
    stats = latest_volatility(prices, window=20)
    # Sample std of ten +1% and ten -1% returns.
    assert stats["window"] == 20
    assert abs(stats["daily_std"] - 0.010259) < 1e-4
    assert stats["annualized"] > stats["daily_std"]


def test_anomaly_flags_a_jump_against_a_quiet_baseline():
    returns = [0.001, -0.001] * 20
    returns.append(0.08)
    prices = _prices_from_returns(100.0, returns)
    flags = anomaly_flags(_dates(len(prices)), prices, window=20, threshold=2.0)
    assert flags[-1]["z"] > 2
    assert flags[-1]["return"] == 0.08


def test_direction_model_on_a_series_that_always_rises():
    prices = [100.0 + i for i in range(150)]
    result = evaluate_direction_model(prices)
    assert result["status"] == "ok"
    assert result["n_train"] + result["n_test"] > 80
    assert result["test_accuracy"] == 1.0
    assert result["majority_baseline_accuracy"] == 1.0
    assert result["beats_majority_baseline"] is False


def test_direction_model_refuses_a_short_series():
    result = evaluate_direction_model([100.0, 101.0, 102.0])
    assert result["status"] == "insufficient_history"


def test_report_includes_volatility_and_model():
    returns = [0.001, -0.001] * 80
    prices = _prices_from_returns(50.0, returns)
    report = build_report("TEST", _dates(len(prices)), prices)
    assert report["symbol"] == "TEST"
    assert report["volatility"]["window"] == 20
    assert report["direction_model"]["status"] == "ok"
    assert report["anomalies"]["eligible_bars"] > 0
