def calculate_moving_average(prices: list[float]) -> float:
    if not prices:
        return 0.0
    return round(sum(prices) / len(prices), 2)
