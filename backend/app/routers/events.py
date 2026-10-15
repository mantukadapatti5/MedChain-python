"""
Real-time push layer, port of server.js's /api/events/ticket + /api/events
SSE endpoints and utils/sseTickets.js.

EventSource (the browser API behind SSE) cannot send a custom Authorization
header, so the client first requests a one-time ticket over a normal
authenticated call, then opens the SSE stream with that ticket in the URL.
Tickets expire in 15 seconds and are single-use, so a leaked URL is already
worthless.

The "something changed, refresh" broadcast itself is implemented with a
simple in-process asyncio broadcaster — every mutating route can call
`broadcast_update()` (see app/events_bus.py) after a commit to nudge every
connected browser tab to refetch, exactly like the original's `eventBus`.
"""
import asyncio
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.deps import get_current_user
from app.events_bus import subscribe, unsubscribe

router = APIRouter(prefix="/api", tags=["events"])

_tickets: dict[str, dict] = {}
TICKET_TTL_SECONDS = 15


@router.get("/health")
def health():
    return {"status": "ok", "service": "medchain-python-backend", "time": datetime.now(timezone.utc).isoformat()}


@router.post("/events/ticket")
def issue_ticket(user: dict = Depends(get_current_user)):
    ticket = secrets.token_hex(24)
    _tickets[ticket] = {"user": user, "expiresAt": time.time() + TICKET_TTL_SECONDS}
    return {"ticket": ticket}


def _consume_ticket(ticket: str):
    entry = _tickets.pop(ticket, None)
    if not entry:
        return None
    if time.time() > entry["expiresAt"]:
        return None
    return entry["user"]


@router.get("/events")
async def events(request: Request, ticket: str = ""):
    user = _consume_ticket(ticket)
    if not user:
        raise HTTPException(status_code=401)

    queue = subscribe()

    async def stream():
        yield "retry: 3000\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(queue.get(), timeout=20)
                    yield "data: update\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
