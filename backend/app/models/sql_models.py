"""
SQLAlchemy models — the PostgreSQL side of the polyglot persistence design.

Every entity that was previously a top-level array in db.json (users,
clients, vendorInventory, stockRequests, sales, billing, anomalies, ...)
becomes its own table here. Nested, variable-shape sub-structures that the
original app treats as opaque blobs (gpsLog, coldChainLog, batchesAllocated,
affectedHolders, acknowledgedBy) are kept as JSON columns rather than being
fully normalized into further tables — this preserves 1:1 behavioural
fidelity with the original app (the route logic reads/writes them as
plain lists/dicts) while still getting real relational guarantees
(foreign keys, NOT NULL, transactions) on the fields that matter.

Works unchanged against either PostgreSQL (JSONB) or the SQLite dev/test
fallback (JSON) — SQLAlchemy's generic ``JSON`` type maps to the right
column type for whichever engine is configured in app.config.DATABASE_URL.
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Text
)
from sqlalchemy.orm import relationship

from app.db.postgres import Base


def now():
    return datetime.utcnow().isoformat()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # admin | vendor | distributor | client
    mfa_enabled = Column(Boolean, default=False)
    license_verified = Column(Boolean, default=False)


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    type = Column(String)
    region = Column(String)
    contact_person = Column(String)
    phone = Column(String)
    email = Column(String)
    license_verified = Column(Boolean, default=False)
    onboarded_at = Column(String, default=now)
    # Admin verification workflow (see services/client_verification.py)
    verification_status = Column(String, default="pending")  # pending | approved | rejected
    onboarded_by = Column(String)     # email of the Distributor/Admin who added the client
    verified_by = Column(String)      # email of the Admin who approved/rejected
    verified_at = Column(String)
    rejection_reason = Column(String)


class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)


class VendorInventory(Base):
    __tablename__ = "vendor_inventory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_name = Column(String, nullable=False, index=True)
    category = Column(String, default="General")
    batch = Column(String, nullable=False, index=True)
    manufacturer = Column(String)
    manufacture_date = Column(String)
    stock = Column(Float, nullable=False, default=0)
    reorder_point = Column(Float, default=50)
    unit_price = Column(Float, default=0)
    expiry_date = Column(String)
    cold_chain = Column(Boolean, default=False)
    provenance_checksum = Column(String)


class DistributorInventory(Base):
    __tablename__ = "distributor_inventory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_name = Column(String, nullable=False, index=True)
    category = Column(String, default="General")
    batch = Column(String, nullable=False, index=True)
    manufacturer = Column(String)
    region = Column(String, index=True)
    stock = Column(Float, nullable=False, default=0)
    reorder_point = Column(Float, default=50)
    unit_price = Column(Float, default=0)
    expiry_date = Column(String)
    cold_chain = Column(Boolean, default=False)
    provenance_checksum = Column(String)
    lead_time_days = Column(Float, default=3)


class ClientInventory(Base):
    __tablename__ = "client_inventory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    client_name = Column(String)
    drug_name = Column(String, nullable=False, index=True)
    batch = Column(String, nullable=False)
    manufacturer = Column(String)
    stock = Column(Float, default=0)
    reorder_point = Column(Float, default=10)
    unit_price = Column(Float, default=0)
    expiry_date = Column(String)
    cold_chain = Column(Boolean, default=False)
    provenance_checksum = Column(String)


class StockRequest(Base):
    """Distributor -> Vendor stock requests."""
    __tablename__ = "stock_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_name = Column(String, nullable=False)
    qty_requested = Column(Float, nullable=False)
    region = Column(String)
    priority = Column(String, default="routine")
    status = Column(String, default="pending", index=True)
    requested_by = Column(String, default="distributor")
    created_at = Column(String, default=now)
    approved_at = Column(String)
    dispatched_at = Column(String)
    received_at = Column(String)
    qty_dispatched = Column(Float)
    qty_received = Column(Float)
    batches_allocated = Column(JSON, default=list)
    gps_log = Column(JSON, default=list)
    cold_chain_log = Column(JSON, default=list)
    rejection_reason = Column(String)
    destination = Column(JSON, default=dict)


class ClientRequest(Base):
    """Client -> Distributor last-mile requests."""
    __tablename__ = "client_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    client_name = Column(String)
    drug_name = Column(String, nullable=False)
    qty_requested = Column(Float, nullable=False)
    region = Column(String)
    priority = Column(String, default="routine")
    status = Column(String, default="pending", index=True)
    created_at = Column(String, default=now)
    approved_at = Column(String)
    dispatched_at = Column(String)
    received_at = Column(String)
    qty_dispatched = Column(Float)
    qty_received = Column(Float)
    batches_allocated = Column(JSON, default=list)
    gps_log = Column(JSON, default=list)
    cold_chain_log = Column(JSON, default=list)
    rejection_reason = Column(String)
    destination = Column(JSON, default=dict)


class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_name = Column(String, nullable=False, index=True)
    batch = Column(String)
    qty = Column(Float, nullable=False)
    unit_price = Column(Float)
    amount = Column(Float)
    buyer = Column(String)
    region = Column(String)
    date = Column(String, default=now, index=True)


class Billing(Base):
    __tablename__ = "billing"
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer)
    drug_name = Column(String)
    amount = Column(Float)
    status = Column(String, default="pending")
    date = Column(String, default=now)


class Anomaly(Base):
    __tablename__ = "anomalies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, nullable=False)
    drug_name = Column(String)
    batch = Column(String, index=True)
    severity = Column(String)
    detected_at = Column(String, default=now)
    status = Column(String, default="open", index=True)
    source = Column(String)
    message = Column(Text)
    model = Column(String)
    anomaly_score = Column(Float)
    features = Column(JSON, default=dict)
    updated_at = Column(String)
    updated_by = Column(String)


class ColdChainLog(Base):
    """Kept for backward-compatible per-batch cold-chain reads on top of the
    InfluxDB time-series store (see app/services/telemetry.py) — every
    reading is written to both, InfluxDB for time-series analysis, this
    table for quick "latest reading per batch" lookups without a Flux query."""
    __tablename__ = "cold_chain_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    portal = Column(String)
    batch = Column(String, index=True)
    temp = Column(Float)
    humidity = Column(Float)
    timestamp = Column(String, default=now)
    alert = Column(Boolean, default=False)


class SupplierPerformance(Base):
    __tablename__ = "supplier_performance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_name = Column(String)
    on_time_delivery_rate = Column(Float)
    quality_score = Column(Float)
    avg_response_hours = Column(Float)
    orders_fulfilled = Column(Integer)


class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, default=1)
    emergency_mode = Column(Boolean, default=False)
    updated_at = Column(String)
    updated_by = Column(String)


class Recall(Base):
    __tablename__ = "recalls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch = Column(String, index=True)
    drug_name = Column(String)
    reason = Column(Text)
    severity = Column(String, default="high")
    issued_by = Column(String)
    issued_at = Column(String, default=now)
    status = Column(String, default="active", index=True)
    resolved_at = Column(String)
    resolved_by = Column(String)
    affected_holders = Column(JSON, default=dict)
    acknowledged_by = Column(JSON, default=list)


class ProductionRun(Base):
    __tablename__ = "production_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_name = Column(String)
    batch = Column(String)
    qty_produced = Column(Float)
    stock_before = Column(Float)
    stock_after = Column(Float)
    reason = Column(String)
    triggered_by = Column(String)
    emergency_mode = Column(Boolean)
    created_at = Column(String, default=now)


class ClientUsageLog(Base):
    __tablename__ = "client_usage_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    client_name = Column(String)
    drug_name = Column(String)
    qty = Column(Float)
    note = Column(String)
    batches_used = Column(JSON, default=list)
    recorded_at = Column(String, default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)
    role = Column(String, nullable=True)
    type = Column(String, default="SYSTEM")
    severity = Column(String, default="info")
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    related_drug = Column(String)
    related_batch = Column(String)
    related_request_id = Column(Integer)
    action_path = Column(String)
    event_key = Column(String, index=True)
    read = Column(Boolean, default=False)
    created_at = Column(String, default=now)
    read_at = Column(String)


class ProcurementSelection(Base):
    __tablename__ = "procurement_selections"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_name = Column(String)
    qty = Column(Float)
    region = Column(String)
    supplier_name = Column(String)
    reason = Column(String)
    created_at = Column(String, default=now)
    created_by = Column(String)


class RedistributionTransfer(Base):
    __tablename__ = "redistribution_transfers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_name = Column(String)
    from_region = Column(String)
    to_region = Column(String)
    qty = Column(Float)
    moved_batches = Column(JSON, default=list)
    created_at = Column(String, default=now)
    created_by = Column(String)


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, default="live")
    drug_name = Column(String)
    batch = Column(String)
    region = Column(String)
    current_stock = Column(Float)
    demand_increase_percent = Column(Float)
    days_ahead = Column(Integer)
    baseline_forecast = Column(Float)
    scenario_forecast = Column(Float)
    additional_demand_units = Column(Float)
    baseline_risk = Column(String)
    baseline_days_of_supply = Column(Float)
    scenario_shortage_probability = Column(Float)
    scenario_risk_level = Column(String)
    model = Column(String)
    created_at = Column(String, default=now)
    created_by = Column(String)
