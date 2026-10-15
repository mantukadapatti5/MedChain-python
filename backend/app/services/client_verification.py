"""
Client verification workflow (Distributor adds a client -> Admin verifies it).

Status lifecycle stored on Client.verification_status:

    pending   : added by a Distributor, waiting for the Admin. The client cannot sign in yet.
    approved  : verified by the Admin. Full client-portal access.
    rejected  : refused by the Admin (a reason is stored). The client cannot sign in.

Admin transitions:
    approve : pending  -> approved,  rejected -> approved   (re-review is allowed)
    reject  : pending  -> rejected,  approved -> rejected   (rejecting an approved client suspends it)

This module is pure logic (no database / FastAPI imports) so it is easy to test.
"""

STATUSES = ("pending", "approved", "rejected")


def effective_status(status, license_verified=False) -> str:
    """Returns a valid status. Rows created before this feature existed have no status,
    so they fall back to the old license flag."""
    if status in STATUSES:
        return status
    return "approved" if license_verified else "pending"


def can_approve(status) -> bool:
    return effective_status(status) in ("pending", "rejected")


def can_reject(status) -> bool:
    return effective_status(status) in ("pending", "approved")


def login_block_message(status, reason=None, license_verified=False):
    """None when the client may sign in; otherwise the message shown on the login screen."""
    s = effective_status(status, license_verified)
    if s == "approved":
        return None
    if s == "rejected":
        why = f" Reason: {reason}." if reason else ""
        return f"Your client account was rejected by the Admin.{why} Please contact your Distributor."
    return ("Your client account is awaiting verification by the Admin. "
            "You will be able to sign in as soon as it is approved.")


def count_by_status(rows) -> dict:
    """rows: iterable of Client-like objects with .verification_status and .license_verified"""
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[effective_status(r.verification_status, r.license_verified)] += 1
    return counts
