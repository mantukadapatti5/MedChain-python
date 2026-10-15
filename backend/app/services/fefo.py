"""Direct port of backend/utils/fefo.js — First-Expiry-First-Out allocation."""
from datetime import datetime


def _parse_date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.max


def allocate_fefo(inventory_rows: list, drug_name: str, qty_needed: float) -> dict:
    """
    inventory_rows: list of ORM rows (VendorInventory / DistributorInventory / ClientInventory)
    Mutates `.stock` on the chosen rows in place (caller commits the session).
    Returns {allocated, totalAllocated, shortfall, fulfilled}.
    """
    candidates = sorted(
        [r for r in inventory_rows if r.drug_name == drug_name and r.stock > 0],
        key=lambda r: _parse_date(r.expiry_date),
    )

    allocated = []
    remaining = qty_needed

    for item in candidates:
        if remaining <= 0:
            break
        take = min(item.stock, remaining)
        if take <= 0:
            continue
        item.stock -= take
        allocated.append({
            "batch": item.batch,
            "qty": take,
            "expiryDate": item.expiry_date,
            "unitPrice": item.unit_price,
            "coldChain": bool(item.cold_chain),
            "manufacturer": item.manufacturer,
            "category": getattr(item, "category", None),
        })
        remaining -= take

    return {
        "allocated": allocated,
        "totalAllocated": qty_needed - remaining,
        "shortfall": max(0, remaining),
        "fulfilled": remaining <= 0,
    }
