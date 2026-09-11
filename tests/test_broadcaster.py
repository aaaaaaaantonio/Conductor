import asyncio

import pytest

from app.execution.broadcaster import EventBroadcaster


@pytest.mark.asyncio
async def test_publish_delivers_to_all_subscribers():
    broadcaster = EventBroadcaster()
    queue_a = broadcaster.subscribe()
    queue_b = broadcaster.subscribe()

    await broadcaster.publish({"type": "log-line", "job_id": 1, "line": "hello"})

    event_a = await asyncio.wait_for(queue_a.get(), timeout=1)
    event_b = await asyncio.wait_for(queue_b.get(), timeout=1)
    assert event_a == {"type": "log-line", "job_id": 1, "line": "hello"}
    assert event_b == event_a


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    broadcaster = EventBroadcaster()
    queue = broadcaster.subscribe()
    broadcaster.unsubscribe(queue)

    await broadcaster.publish({"type": "job-status", "job_id": 1, "status": "success"})

    assert queue.empty()
