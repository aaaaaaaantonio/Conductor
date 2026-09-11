from typing import Literal

import httpx


async def trigger_build(
    base_url: str, job_name: str, params: dict, client: httpx.AsyncClient
) -> str:
    response = await client.post(
        f"{base_url}/job/{job_name}/buildWithParameters", params=params
    )
    response.raise_for_status()
    return response.headers["Location"]


async def poll_build_status(
    base_url: str, build_url: str, client: httpx.AsyncClient
) -> Literal["running", "success", "failed"]:
    response = await client.get(f"{build_url.rstrip('/')}/api/json")
    response.raise_for_status()
    data = response.json()
    if data["building"]:
        return "running"
    return "success" if data["result"] == "SUCCESS" else "failed"
