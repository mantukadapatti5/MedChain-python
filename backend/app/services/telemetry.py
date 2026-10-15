"""
Writes every cold-chain reading and GPS ping to InfluxDB (the time-series
store of record, per the polyglot-persistence design) so history/analytics
queries — "show temperature for batch B123 over the last 24 hours",
"find every breach" — run against a database built for exactly that shape
of data, instead of scanning a growing JSON array.

The request's own `coldChainLog` / `gpsLog` JSON column in Postgres keeps a
lightweight copy of the same events, because the existing ETA/shipment-
tracking math (app.services.geo) reads that list directly and re-deriving
it from Influx on every dashboard refresh would be unnecessary latency for
data that's already sitting on the row. Both writes happen atomically from
the caller's point of view: InfluxDB point write, then Postgres commit.
"""
from app.db import influx


def record_cold_chain_reading(portal: str, batch: str, temp: float, humidity: float, timestamp: str, breached: bool):
    influx.write_point(
        measurement="cold_chain",
        tags={"portal": portal, "batch": batch},
        fields={"temperature": float(temp), "humidity": float(humidity), "breached": bool(breached)},
        timestamp=timestamp,
    )


def record_gps_ping(shipment_id, direction: str, lat: float, lng: float, timestamp: str, label: str = ""):
    influx.write_point(
        measurement="gps_tracking",
        tags={"shipment_id": str(shipment_id), "direction": direction},
        fields={"lat": float(lat), "lng": float(lng), "label": label or ""},
        timestamp=timestamp,
    )


def cold_chain_history(batch: str, limit: int = 200):
    return influx.read_points("cold_chain", {"batch": batch}, limit=limit)


def gps_history(shipment_id, limit: int = 500):
    return influx.read_points("gps_tracking", {"shipment_id": str(shipment_id)}, limit=limit)
