from urllib.parse import quote

import httpx


async def trigger_build(
    base_url: str,
    job_name: str,
    params: dict[str, object | None],
    client: httpx.AsyncClient,
    auth: httpx.Auth | None = None,
) -> str:
    # Built by hand: a None value goes out as a bare key (`&headless`),
    # which httpx's params= can't express.
    query = "&".join(
        quote(key, safe="") if value is None else f"{quote(key, safe='')}={quote(str(value), safe='')}"
        for key, value in params.items()
    )
    url = f"{base_url}/job/{job_name}/buildWithParameters"
    if query:
        url = f"{url}?{query}"
    # With a user's API token Jenkins doesn't ask for a CSRF crumb.
    response = await client.post(url, auth=auth)
    response.raise_for_status()
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError(
            "Jenkins did not return a Location header for the queued build"
        )
    return location

