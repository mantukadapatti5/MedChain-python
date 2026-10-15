"""
The React frontend (unchanged) expects camelCase JSON fields (drugName,
reorderPoint, qtyRequested, ...) exactly as the old Express API returned
them. SQLAlchemy models here use snake_case columns (the Python/Postgres
convention), so every response is passed through `to_camel_dict` on the way
out, and incoming camelCase request bodies are passed through
`to_snake_dict` on the way in. This is the only translation layer needed —
every route stays camelCase-in/camelCase-out from the frontend's point of
view, identical to the original API contract.
"""
import re
from sqlalchemy import inspect


def _snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _camel_to_snake(s: str) -> str:
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def row_to_dict(instance) -> dict:
    """Converts one SQLAlchemy model instance into a camelCase dict."""
    if instance is None:
        return None
    mapper = inspect(instance).mapper
    out = {}
    for column in mapper.columns:
        value = getattr(instance, column.key)
        out[_snake_to_camel(column.key)] = value
    return out


def rows_to_list(instances) -> list:
    return [row_to_dict(i) for i in instances]


def to_snake_dict(payload: dict) -> dict:
    """Converts an incoming camelCase JSON body into snake_case kwargs
    suitable for constructing/updating a SQLAlchemy model."""
    return {_camel_to_snake(k): v for k, v in (payload or {}).items()}
