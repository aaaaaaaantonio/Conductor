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
async def test_poll_build_status_maps_jenkins_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"building": False, "result": "SUCCESS"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status = await poll_build_status(
            "https://jenkins", "https://jenkins/job/my-job/17/", client
        )

    assert status == "success"
