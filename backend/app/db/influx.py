"""
InfluxDB is the home for cold-chain (temperature/humidity) and GPS telemetry
— exactly the timestamped-sensor-reading shape a time-series database is
built for, per the polyglot-persistence design.

If INFLUX_URL isn't set (or InfluxDB isn't reachable), telemetry writes fall
back to append-only local JSONL files under ./data/telemetry/, so the app
still works end-to-end without Docker. The read-side (history queries)
transparently reads from whichever backend is active.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET, DATA_DIR

logger = logging.getLogger("medchain.influx")

_write_api = None
_query_api = None
_influx_available = False

if INFLUX_URL:
    try:
        from influxdb_client import InfluxDBClient, Point
        from influxdb_client.client.write_api import SYNCHRONOUS

        _client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=2000)
        _write_api = _client.write_api(write_options=SYNCHRONOUS)
        _query_api = _client.query_api()
        _influx_available = True
        logger.info("Connected to InfluxDB at %s", INFLUX_URL)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("InfluxDB unavailable (%s). Falling back to local JSONL telemetry files.", exc)
        _influx_available = False
else:
    logger.info("INFLUX_URL not set. Using local JSONL fallback store for telemetry.")

TELEMETRY_DIR = DATA_DIR / "telemetry"
TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def _fallback_path(measurement: str) -> Path:
    return TELEMETRY_DIR / f"{measurement}.jsonl"


def write_point(measurement: str, tags: dict, fields: dict, timestamp: Optional[str] = None):
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    if _influx_available:
        try:
            from influxdb_client import Point

            point = Point(measurement)
            for k, v in tags.items():
                point = point.tag(k, str(v))
            for k, v in fields.items():
                point = point.field(k, v)
            point = point.time(ts)
            _write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            return
        except Exception as exc:  # InfluxDB down/unreachable: keep the app working
            logger.warning("InfluxDB write failed (%s). Saving this point to the local JSONL file instead.", exc)
    row = {"timestamp": ts, "tags": tags, "fields": fields}
    with open(_fallback_path(measurement), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _read_influx(measurement: str, tag_filters: dict, limit: int) -> list:
    filters = " and ".join([f'r["{k}"] == "{v}"' for k, v in tag_filters.items()])
    flux = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -30d)
      |> filter(fn: (r) => r["_measurement"] == "{measurement}")
      {f'|> filter(fn: (r) => {filters})' if filters else ''}
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: {limit})
    '''
    tables = _query_api.query(flux)
    rows = []
    for table in tables:
        for record in table.records:
            rows.append({
                "timestamp": record.get_time().isoformat(),
                "field": record.get_field(),
                "value": record.get_value(),
                **{k: record.values.get(k) for k in tag_filters},
            })
    return rows


def read_points(measurement: str, tag_filters: Optional[dict] = None, limit: int = 200) -> list:
    tag_filters = tag_filters or {}
    if _influx_available:
        try:
            return _read_influx(measurement, tag_filters, limit)
        except Exception as exc:  # InfluxDB down/unreachable: read the local file store instead
            logger.warning("InfluxDB read failed (%s). Reading the local JSONL file instead.", exc)

    path = _fallback_path(measurement)
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if all(str(row.get("tags", {}).get(k)) == str(v) for k, v in tag_filters.items()):
                rows.append(row)
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows[:limit]


def is_influx_live() -> bool:
    return _influx_available
