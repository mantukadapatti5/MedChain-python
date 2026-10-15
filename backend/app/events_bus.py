"""Direct port of backend/utils/eventBus.js's intent, adapted to asyncio
queues (Node's EventEmitter has no async equivalent in Python's stdlib)."""
import asyncio

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)


def broadcast_update():
    """Call this after any mutating commit so every connected browser tab's
    SSE stream gets a 'something changed' nudge, exactly like the original
    store.js:save() -> eventBus.emit('update')."""
    for q in list(_subscribers):
        try:
            q.put_nowait("update")
        except Exception:
            pass
