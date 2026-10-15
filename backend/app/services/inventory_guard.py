"""Direct port of backend/utils/inventoryGuard.js."""

EDITABLE_FIELDS = ["stock", "reorderPoint", "unitPrice", "expiryDate", "coldChain", "category"]
NUMERIC_FIELDS = ["stock", "reorderPoint", "unitPrice"]

_FIELD_TO_COLUMN = {
    "stock": "stock",
    "reorderPoint": "reorder_point",
    "unitPrice": "unit_price",
    "expiryDate": "expiry_date",
    "coldChain": "cold_chain",
    "category": "category",
}


def apply_safe_inventory_update(item, body: dict) -> str | None:
    """Applies only allow-listed fields from `body` onto the ORM `item`.
    Returns an error message string on invalid input, or None on success."""
    for field in NUMERIC_FIELDS:
        if body.get(field) is not None:
            try:
                num = float(body[field])
            except (TypeError, ValueError):
                return f"{field} must be a valid number that is zero or greater."
            if num < 0:
                return f"{field} must be a valid number that is zero or greater."

    for field in EDITABLE_FIELDS:
        if field not in body or body[field] is None:
            continue
        column = _FIELD_TO_COLUMN[field]
        if not hasattr(item, column):
            continue
        value = float(body[field]) if field in NUMERIC_FIELDS else body[field]
        setattr(item, column, value)

    return None
