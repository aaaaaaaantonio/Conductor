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



@pytest.mark.asyncio
async def test_trigger_build_sends_bare_keys_and_encodes_values():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/1/"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await trigger_build(
            "https://jenkins",
            "job",
            {"team_id": 1, "env": "a b&c=d", "имя": "тест", "headless": None},
            client,
        )

    assert seen[0].query == (
        b"team_id=1&env=a%20b%26c%3Dd&%D0%B8%D0%BC%D1%8F=%D1%82%D0%B5%D1%81%D1%82&headless"
    )


@pytest.mark.asyncio
async def test_trigger_build_without_params_has_no_query():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/1/"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await trigger_build("https://jenkins", "job", {}, client)

    assert str(seen[0]) == "https://jenkins/job/job/buildWithParameters"
