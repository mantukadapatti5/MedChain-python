from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def ensure_schema_updates():
    """create_all() never adds columns to tables that already exist, so databases created before the
    client-verification feature get its new columns here (safe to run on every start-up)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "clients" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("clients")}
    new_columns = ["verification_status", "onboarded_by", "verified_by", "verified_at", "rejection_reason"]
    with engine.begin() as conn:
        for name in new_columns:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE clients ADD COLUMN {name} VARCHAR"))
        # old rows: verified clients stay approved, the rest wait for the Admin
        conn.execute(text(
            "UPDATE clients SET verification_status = "
            "CASE WHEN license_verified THEN 'approved' ELSE 'pending' END "
            "WHERE verification_status IS NULL"
        ))


def get_db():
    """FastAPI dependency: yields one request-scoped SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
