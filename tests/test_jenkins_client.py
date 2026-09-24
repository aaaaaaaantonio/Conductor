import httpx
import pytest

from app.execution.jenkins_client import trigger_build


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

