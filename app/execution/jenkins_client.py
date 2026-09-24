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

