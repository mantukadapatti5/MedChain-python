"""Direct port of backend/ml/shortageFeatures.js."""
FEATURE_NAMES = ["stock", "avgDailyDemand", "forecastDemand", "daysOfSupply", "leadTimeDays", "demandTrend", "demandVolatility"]


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _std(values):
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return (_mean([(v - m) ** 2 for v in values])) ** 0.5


def build_features(stock: float, history: list, forecast_demand: float = 0, lead_time_days: float = 3) -> list:
    clean = [float(v) for v in history if v is not None]
    recent = clean[-7:]
    previous = clean[-14:-7]
    avg_daily_demand = _mean(recent if recent else clean)
    previous_demand = _mean(previous if previous else recent)
    demand_trend = (avg_daily_demand / previous_demand) if previous_demand > 0 else 1.0
    demand_volatility = _std(recent if recent else clean)
    days_of_supply = (float(stock or 0) / avg_daily_demand) if avg_daily_demand > 0 else 999

    return [
        float(stock or 0),
        round(avg_daily_demand, 4),
        float(forecast_demand or 0),
        round(min(days_of_supply, 999), 4),
        float(lead_time_days or 3),
        round(min(demand_trend, 10), 4),
        round(demand_volatility, 4),
    ]
