from typing import Literal

import httpx


async def trigger_build(
    base_url: str, job_name: str, params: dict, client: httpx.AsyncClient
) -> str:
    response = await client.post(
        f"{base_url}/job/{job_name}/buildWithParameters", params=params
    )
    response.raise_for_status()
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError(
            "Jenkins did not return a Location header for the queued build"
        )
    return location


async def poll_build_status(
    base_url: str, build_url: str, client: httpx.AsyncClient
) -> Literal["running", "success", "failed"]:
    response = await client.get(f"{build_url.rstrip('/')}/api/json")
    response.raise_for_status()
    data = response.json()
    if "building" not in data:
        raise RuntimeError(
            f"Jenkins build status response is missing the 'building' field: {data!r}"
        )
    if data["building"]:
        return "running"
    # `result` is null while `building` is False for states like an aborted
    # or otherwise-incomplete build. Treat any non-"SUCCESS" result
    # (including a missing/null one) as "failed".
    return "success" if data.get("result") == "SUCCESS" else "failed"
