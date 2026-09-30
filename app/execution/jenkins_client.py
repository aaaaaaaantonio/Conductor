import httpx


async def trigger_build(
    base_url: str,
    job_name: str,
    params: dict,
    client: httpx.AsyncClient,
    auth: httpx.Auth | None = None,
) -> str:
    # With a user's API token Jenkins doesn't ask for a CSRF crumb.
    response = await client.post(
        f"{base_url}/job/{job_name}/buildWithParameters", params=params, auth=auth
    )
    response.raise_for_status()
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError(
            "Jenkins did not return a Location header for the queued build"
        )
    return location

