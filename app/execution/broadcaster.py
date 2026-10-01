import asyncio

# Events a subscriber may fall behind by before it is cut off.
QUEUE_LIMIT = 1000


class EventBroadcaster:
    """Fan-out of job events to SSE subscribers.

    Each subscriber gets a bounded queue. One that falls QUEUE_LIMIT events
    behind (a stalled browser) is dropped and receives None, telling its
    stream to end; the browser's EventSource then reconnects.
    """

    def __init__(self, queue_limit: int = QUEUE_LIMIT) -> None:
        self._queue_limit = queue_limit
        self._subscribers: set[asyncio.Queue[dict | None]] = set()

    def subscribe(self) -> "asyncio.Queue[dict | None]":
        # One extra slot so the disconnect marker always fits.
        queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=self._queue_limit + 1)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict | None]") -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: dict) -> None:
        # Never awaits a slow subscriber: the runner calls this per log line.
        for queue in list(self._subscribers):
            if queue.qsize() < self._queue_limit:
                queue.put_nowait(event)
                continue
            self._subscribers.discard(queue)
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)


broadcaster = EventBroadcaster()
