"""
Drug-availability checks used when a request is RAISED (not only when it is
approved):

  - Distributor -> Vendor    : the drug must be in the Vendor inventory list
  - Client      -> Distributor: the drug must be in the Distributor inventory
                                for the client's region (that is the pool the
                                Distributor's FEFO approval draws from)

If the drug is missing (or listed but with zero stock) the request is refused
with a clear message, which the frontend shows as a pop-up (toast).

The functions work on any iterable of rows that expose `.drug_name`, `.stock`
(and `.region` for the regional check), so they have no database/FastAPI
dependency and are easy to unit-test.

The matching is case-insensitive and ignores extra spaces. On success the
canonical spelling stored in the inventory is returned, because FEFO
allocation (app/services/fefo.py) compares drug names with exact equality.
"""


def _norm(value) -> str:
    return " ".join(str(value or "").split()).lower()


def _names(rows) -> list:
    return sorted({r.drug_name for r in rows if r.drug_name})


def _total_stock(rows) -> float:
    return sum(float(r.stock or 0) for r in rows)


def _available_hint(rows) -> str:
    names = sorted({r.drug_name for r in rows if r.drug_name and float(r.stock or 0) > 0})
    return f" Available drugs: {', '.join(names)}." if names else ""


def check_vendor_availability(vendor_rows, drug_name):
    """Returns (canonical_drug_name, available_units, None) when the drug can
    be requested, or (None, 0, error_message) when it cannot."""
    rows = list(vendor_rows)
    wanted = _norm(drug_name)
    matches = [r for r in rows if _norm(r.drug_name) == wanted]

    if not matches:
        return None, 0, (
            f'Drug "{str(drug_name).strip()}" is not available in the Vendor inventory list, '
            f"so the request was not sent.{_available_hint(rows)}"
        )

    canonical = matches[0].drug_name
    units = _total_stock(matches)
    if units <= 0:
        return None, 0, (
            f'"{canonical}" is listed in the Vendor inventory but is currently out of stock '
            f"(0 units available), so the request was not sent."
        )
    return canonical, units, None


def check_distributor_availability(distributor_rows, drug_name, region):
    """Same idea for Client -> Distributor, limited to the client's region.
    `distributor_rows` should be ALL distributor inventory rows; the region
    filter is applied here so the error can mention other regions that do
    have the drug."""
    rows = list(distributor_rows)
    wanted = _norm(drug_name)
    all_matches = [r for r in rows if _norm(r.drug_name) == wanted]
    region_matches = [r for r in all_matches if _norm(r.region) == _norm(region)]

    if not all_matches:
        region_rows = [r for r in rows if _norm(r.region) == _norm(region)]
        return None, 0, (
            f'Drug "{str(drug_name).strip()}" is not available in the Distributor inventory list, '
            f"so the request was not sent.{_available_hint(region_rows or rows)}"
        )

    canonical = all_matches[0].drug_name
    if not region_matches:
        elsewhere = sorted({r.region for r in all_matches if float(r.stock or 0) > 0 and r.region})
        where = f" It is currently available in: {', '.join(elsewhere)}." if elsewhere else ""
        return None, 0, (
            f'"{canonical}" is not available in the Distributor stock for {region}, '
            f"so the request was not sent.{where}"
        )

    units = _total_stock(region_matches)
    if units <= 0:
        return None, 0, (
            f'"{canonical}" is listed in the Distributor inventory for {region} but is currently '
            f"out of stock (0 units available), so the request was not sent."
        )
    return canonical, units, None
