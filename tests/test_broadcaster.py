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


@pytest.mark.asyncio
async def test_overflowing_subscriber_is_disconnected_others_keep_receiving():
    broadcaster = EventBroadcaster(queue_limit=2)
    slow = broadcaster.subscribe()
    fast = broadcaster.subscribe()

    for i in range(3):
        await broadcaster.publish({"n": i})
        if i < 2:
            assert fast.get_nowait() == {"n": i}

    # The slow one gets only the disconnect marker and no further events.
    assert slow.get_nowait() is None
    assert slow.empty()
    await broadcaster.publish({"n": 3})
    assert slow.empty()
    assert fast.get_nowait() == {"n": 2}
    assert fast.get_nowait() == {"n": 3}


@pytest.mark.asyncio
async def test_publish_never_blocks_on_a_full_queue():
    broadcaster = EventBroadcaster(queue_limit=1)
    broadcaster.subscribe()

    for i in range(5):
        await asyncio.wait_for(broadcaster.publish({"n": i}), timeout=1)
