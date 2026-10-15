"""Direct port of backend/utils/geo.js."""
import math
from datetime import datetime

EARTH_RADIUS_KM = 6371
DEFAULT_SPEED_KMH = 45

REGION_DESTINATIONS = {
    "North Zone": {"lat": 28.6139, "lng": 77.2090, "label": "North Zone Hub"},
    "South Zone": {"lat": 13.0827, "lng": 80.2707, "label": "South Zone Hub"},
    "East Zone": {"lat": 22.5726, "lng": 88.3639, "label": "East Zone Hub"},
    "West Zone": {"lat": 19.0760, "lng": 72.8777, "label": "West Zone Hub"},
    "Central Zone": {"lat": 21.1458, "lng": 79.0882, "label": "Central Zone Hub"},
}


def _parse_dt(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def to_radians(v):
    return float(v) * math.pi / 180


def haversine_distance(a, b) -> float:
    if not a or not b or a.get("lat") is None or a.get("lng") is None or b.get("lat") is None or b.get("lng") is None:
        return 0.0
    d_lat = to_radians(b["lat"] - a["lat"])
    d_lng = to_radians(b["lng"] - a["lng"])
    lat1, lat2 = to_radians(a["lat"]), to_radians(b["lat"])
    x = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))
    return EARTH_RADIUS_KM * c


def speed_between(a, b):
    if not a or not b:
        return None
    try:
        elapsed_hours = (_parse_dt(b["timestamp"]) - _parse_dt(a["timestamp"])).total_seconds() / 3600
    except Exception:
        return None
    if elapsed_hours <= 0 or elapsed_hours < 1 / 60:
        return None
    return haversine_distance(a, b) / elapsed_hours


def get_destination_for_request(request: dict):
    dest = request.get("destination") or {}
    if dest.get("lat") is not None and dest.get("lng") is not None:
        return {"lat": float(dest["lat"]), "lng": float(dest["lng"]), "label": dest.get("label", "Destination")}
    return REGION_DESTINATIONS.get(request.get("region"), REGION_DESTINATIONS["South Zone"])


def calculate_shipment_tracking(request: dict) -> dict:
    gps_log = sorted(request.get("gpsLog") or [], key=lambda p: p.get("timestamp", ""))
    destination = get_destination_for_request(request)
    origin = gps_log[0] if gps_log else None
    latest = gps_log[-1] if gps_log else None

    travelled_km = 0.0
    speed_samples = []
    for i in range(1, len(gps_log)):
        travelled_km += haversine_distance(gps_log[i - 1], gps_log[i])
        s = speed_between(gps_log[i - 1], gps_log[i])
        if s is not None and 0 < s < 150:
            speed_samples.append(s)

    remaining_km = haversine_distance(latest, destination) if latest else (haversine_distance(origin, destination) if origin else 0)
    direct_km = haversine_distance(origin, destination) if origin else 0
    avg_speed = sum(speed_samples) / len(speed_samples) if speed_samples else DEFAULT_SPEED_KMH

    eta_hours = remaining_km / avg_speed if avg_speed > 0 else None
    eta_at = None
    if eta_hours is not None and latest:
        from datetime import timedelta
        eta_at = (_parse_dt(latest["timestamp"]) + timedelta(hours=eta_hours)).isoformat()

    progress = max(0.0, min(100.0, ((direct_km - remaining_km) / direct_km) * 100)) if direct_km > 0 else 0.0

    return {
        "requestId": request.get("id"),
        "status": request.get("status"),
        "origin": origin,
        "latest": latest,
        "destination": destination,
        "directDistanceKm": round(direct_km, 2),
        "travelledKm": round(travelled_km, 2),
        "remainingKm": round(remaining_km, 2),
        "averageSpeedKmh": round(avg_speed, 1),
        "etaMinutes": None if eta_hours is None else max(0, round(eta_hours * 60)),
        "etaAt": eta_at,
        "progressPercent": round(progress, 1),
        "gpsPoints": len(gps_log),
        "speedSource": "calculated from GPS timestamps" if speed_samples else "default simulated transit speed",
    }
