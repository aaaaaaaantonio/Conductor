import time
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.credentials import (
    Credentials,
    clear_cookie,
    get_credentials,
    mark_changed,
    set_cookie,
)
from app.execution.credential_checks import CredentialsRejected, check_allure, check_jenkins, check_zephyr
from app.templating import templates

router = APIRouter(tags=["credentials"])


def _page(
    request: Request,
    creds: Credentials | None,
    error: str | None = None,
    jenkins_user: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    expires = datetime.fromtimestamp(creds.expires_at).strftime("%d.%m.%Y") if creds else None
    return templates.TemplateResponse(
        request,
        "credentials.html",
        {
            "creds": creds,
            "expires": expires,
            "error": error,
            "jenkins_user": jenkins_user or (creds.jenkins_user if creds else ""),
            "saved": request.query_params.get("saved") == "1",
        },
        status_code=status_code,
    )


@router.get("/credentials", response_class=HTMLResponse)
def credentials_page(
    request: Request, creds: Credentials | None = Depends(get_credentials)
) -> HTMLResponse:
    return _page(request, creds)


@router.post("/credentials")
async def save_credentials(
    request: Request,
    jenkins_user: str = Form(...),
    jenkins_token: str = Form(...),
    allure_token: str = Form(""),
    zephyr_token: str = Form(""),
    remember: bool = Form(False),
    creds: Credentials | None = Depends(get_credentials),
) -> Response:
    jenkins_user, jenkins_token, allure_token, zephyr_token = (
        jenkins_user.strip(),
        jenkins_token.strip(),
        allure_token.strip(),
        zephyr_token.strip(),
    )
    try:
        await check_jenkins(jenkins_user, jenkins_token)
        if allure_token:
            await check_allure(allure_token)
        if zephyr_token:
            await check_zephyr(zephyr_token)
    except CredentialsRejected as exc:
        return _page(request, creds, str(exc), jenkins_user, status_code=400)

    new_creds = Credentials(
        jenkins_user=jenkins_user,
        jenkins_token=jenkins_token,
        allure_token=allure_token or None,
        zephyr_token=zephyr_token or None,
        remember=remember,
        issued_at=int(time.time()),
    )
    response = RedirectResponse("/credentials?saved=1", status_code=303)
    set_cookie(response, new_creds)
    mark_changed(request)
    return response


@router.post("/credentials/forget")
def forget_credentials(request: Request) -> Response:
    response = RedirectResponse("/credentials", status_code=303)
    clear_cookie(response)
    mark_changed(request)
    return response
