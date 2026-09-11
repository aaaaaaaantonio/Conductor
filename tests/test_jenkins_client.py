import httpx
import pytest

from app.execution.jenkins_client import poll_build_status, trigger_build


@pytest.mark.asyncio
async def test_trigger_build_returns_queue_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/job/my-job/buildWithParameters"
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/42/"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        queue_url = await trigger_build("https://jenkins", "my-job", {"STAND": "stage-1"}, client)

    assert queue_url == "https://jenkins/queue/item/42/"


@pytest.mark.asyncio
async def test_trigger_build_raises_clear_error_when_location_header_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="Location header"):
            await trigger_build("https://jenkins", "my-job", {"STAND": "stage-1"}, client)


@pytest.mark.asyncio
async def test_trigger_build_propagates_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await trigger_build("https://jenkins", "my-job", {"STAND": "stage-1"}, client)


@pytest.mark.asyncio
async def test_poll_build_status_maps_jenkins_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"building": False, "result": "SUCCESS"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status = await poll_build_status(
            "https://jenkins", "https://jenkins/job/my-job/17/", client
        )

    assert status == "success"


@pytest.mark.asyncio
async def test_poll_build_status_maps_running():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"building": True, "result": None})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status = await poll_build_status(
            "https://jenkins", "https://jenkins/job/my-job/17/", client
        )

    assert status == "running"


@pytest.mark.asyncio
async def test_poll_build_status_maps_non_success_result_to_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"building": False, "result": "FAILURE"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status = await poll_build_status(
            "https://jenkins", "https://jenkins/job/my-job/17/", client
        )

    assert status == "failed"


@pytest.mark.asyncio
async def test_poll_build_status_maps_null_result_while_not_building_to_failed():
    # Jenkins reports result: null while building: False for states such as
    # an aborted build. This should map to "failed", not raise.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"building": False, "result": None})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status = await poll_build_status(
            "https://jenkins", "https://jenkins/job/my-job/17/", client
        )

    assert status == "failed"


@pytest.mark.asyncio
async def test_poll_build_status_raises_clear_error_when_building_field_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "SUCCESS"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="building"):
            await poll_build_status(
                "https://jenkins", "https://jenkins/job/my-job/17/", client
            )


@pytest.mark.asyncio
async def test_poll_build_status_propagates_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await poll_build_status(
                "https://jenkins", "https://jenkins/job/my-job/17/", client
            )
