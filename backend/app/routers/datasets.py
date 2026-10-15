from fastapi import APIRouter, Depends, HTTPException

from app.deps import require_roles
from app.services.dataset_loader import load_datasets, dataset_summary

router = APIRouter(prefix="/api/datasets", tags=["datasets"], dependencies=[Depends(require_roles("admin"))])


def _page(rows: list, limit: int = 100, offset: int = 0):
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    return {"total": len(rows), "limit": limit, "offset": offset, "rows": rows[offset:offset + limit]}


@router.get("/summary")
def summary():
    try:
        return dataset_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sales")
def sales(drugName: str = None, region: str = None, hospital: str = None, limit: int = 100, offset: int = 0):
    data = [r for r in load_datasets()["sales"]
            if (not drugName or r.get("drug_name") == drugName)
            and (not region or r.get("region") == region)
            and (not hospital or r.get("hospital_name") == hospital)]
    return _page(data, limit, offset)


@router.get("/inventory")
def inventory(drugName: str = None, region: str = None, batchId: str = None, limit: int = 100, offset: int = 0):
    data = [r for r in load_datasets()["inventory"]
            if (not drugName or r.get("drug_name") == drugName)
            and (not region or r.get("region") == region)
            and (not batchId or r.get("batch_id") == batchId)]
    return _page(data, limit, offset)


@router.get("/hospital-demand")
def hospital_demand(drugName: str = None, region: str = None, hospitalId: str = None, limit: int = 100, offset: int = 0):
    data = [r for r in load_datasets()["hospitalDemand"]
            if (not drugName or r.get("drug_name") == drugName)
            and (not region or r.get("region") == region)
            and (not hospitalId or str(r.get("hospital_id")) == str(hospitalId))]
    return _page(data, limit, offset)


@router.get("/shipments")
def shipments(shipmentId: str = None, status: str = None, drugName: str = None, limit: int = 100, offset: int = 0):
    data = [r for r in load_datasets()["shipments"]
            if (not shipmentId or r.get("shipment_id") == shipmentId)
            and (not status or r.get("status") == status)
            and (not drugName or r.get("drug_name") == drugName)]
    return _page(data, limit, offset)


@router.get("/cold-chain")
def cold_chain(shipmentId: str = None, batchId: str = None, status: str = None, limit: int = 100, offset: int = 0):
    data = [r for r in load_datasets()["coldChain"]
            if (not shipmentId or r.get("shipment_id") == shipmentId)
            and (not batchId or r.get("batch_id") == batchId)
            and (not status or r.get("status") == status)]
    return _page(data, limit, offset)


@router.get("/suppliers")
def suppliers(supplierId: str = None, drugName: str = None, supplierName: str = None, limit: int = 100, offset: int = 0):
    data = [r for r in load_datasets()["suppliers"]
            if (not supplierId or r.get("supplier_id") == supplierId)
            and (not drugName or r.get("drug_name") == drugName)
            and (not supplierName or r.get("supplier_name") == supplierName)]
    return _page(data, limit, offset)
