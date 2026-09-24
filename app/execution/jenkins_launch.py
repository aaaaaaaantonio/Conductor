from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import JENKINS_BASE_URL, JENKINS_JOB_NAMES
from app.execution.jenkins_client import trigger_build


@dataclass
class LaunchResult:
    message: str
    url: Optional[str] = None


async def launch_in_jenkins(source: str, job_name: str, params: dict) -> LaunchResult:
    """Send a user's launch to Jenkins and build the reply shown to them.

    Called synchronously when the user presses "Запустить" in Jenkins mode
    (Java tab, or Python tab with mode=Jenkins). `source` is "java" or
    "python"; `params` are the non-empty form values. Whatever this returns
    is rendered in the log panel: `message` as text and `url`, if set, as a
    link. Raise to report a failure — the error text is shown instead.
    """
    async with httpx.AsyncClient() as client:
        url = await trigger_build(JENKINS_BASE_URL, job_name, params, client)
    return LaunchResult(message="Сборка отправлена в Jenkins", url=url)


async def restart_java(build_number: int) -> LaunchResult:
    """Restart a Java run: the "Перезапустить" button on the Java tab.

    `build_number` is the Jenkins build number the user entered (an int
    >= 1). Put your own processing here; the restart goes to the same
    Jenkins job as a normal Java launch. The return value / raised error is
    shown in the log panel exactly like launch_in_jenkins's.
    """
    params = {"restart_build": build_number}
    async with httpx.AsyncClient() as client:
        url = await trigger_build(JENKINS_BASE_URL, JENKINS_JOB_NAMES["java"], params, client)
    return LaunchResult(message=f"Перезапуск сборки #{build_number} отправлен в Jenkins", url=url)


async def restart_python(build_number: int) -> LaunchResult:
    """Restart a Python run: the "Перезапустить" button on the Python tab.

    Same contract as restart_java; the restart goes to the same Jenkins job
    as a normal Python launch in Jenkins mode.
    """
    params = {"restart_build": build_number}
    async with httpx.AsyncClient() as client:
        url = await trigger_build(JENKINS_BASE_URL, JENKINS_JOB_NAMES["python"], params, client)
    return LaunchResult(message=f"Перезапуск сборки #{build_number} отправлен в Jenkins", url=url)
