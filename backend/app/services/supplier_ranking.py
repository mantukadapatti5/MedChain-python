"""Direct port of backend/utils/supplierRanking.js."""
from app.services.dataset_loader import load_datasets


def rank_suppliers(drug_name_filter: str = None) -> list:
    rows = [r for r in load_datasets()["suppliers"] if not drug_name_filter or r.get("drug_name") == drug_name_filter]
    grouped = {}
    for r in rows:
        key = r.get("supplier_id")
        g = grouped.setdefault(key, {
            "supplierId": key, "supplierName": r.get("supplier_name"), "drugs": set(),
            "prices": [], "delivery": [], "onTime": [], "quality": [], "rejection": [], "orders": 0,
        })
        g["drugs"].add(r.get("drug_name"))
        g["prices"].append(float(r.get("price") or 0))
        g["delivery"].append(float(r.get("delivery_days") or 0))
        g["onTime"].append(float(r.get("on_time_rate") or 0))
        g["quality"].append(float(r.get("quality_score") or 0))
        g["rejection"].append(float(r.get("rejection_rate") or 0))
        g["orders"] += float(r.get("orders_completed") or 0)

    def avg(a):
        return sum(a) / len(a) if a else 0

    results = []
    for g in grouped.values():
        price, delivery, on_time, quality, rejection = avg(g["prices"]), avg(g["delivery"]), avg(g["onTime"]), avg(g["quality"]), avg(g["rejection"])
        price_score = max(0, min(100, 100 - max(0, price - 50)))
        delivery_score = max(0, min(100, 100 - max(0, delivery - 1) * 12))
        score = round(quality * 0.35 + on_time * 0.30 + delivery_score * 0.20 + price_score * 0.10 + (100 - rejection) * 0.05, 1)
        results.append({
            "supplierId": g["supplierId"], "supplierName": g["supplierName"], "drugsSupplied": list(g["drugs"]),
            "averagePrice": round(price, 2), "averageDeliveryDays": round(delivery, 1), "onTimeRate": round(on_time, 1),
            "qualityScore": round(quality, 1), "rejectionRate": round(rejection, 1), "ordersCompleted": g["orders"],
            "overallScore": score,
        })
    results.sort(key=lambda x: x["overallScore"], reverse=True)
    return results
