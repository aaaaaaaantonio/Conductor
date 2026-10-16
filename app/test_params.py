"""A test's own launch parameters, set in the reference editor and passed
to every run of that test: to Jenkins as query parameters and to the VM
runner as extra flags. Also the reserved names they may not take, shared by
the references API (which checks them on save) and the launch routers."""

import json
import re
from typing import Literal

from pydantic import BaseModel

ParamType = Literal["text", "bool", "flag"]
Language = Literal["java", "python"]

# Query parameters buildWithParameters consumes itself (quiet period,
# remote-trigger token, cause) instead of passing them to the job.
JENKINS_OWN = frozenset({"token", "delay", "cause"})
# Parameters a Java launch sends to Jenkins itself.
JAVA_RESERVED = frozenset(
    {"team_id", "stand_id", "regression_type", "part", "thread_mode", "test_name_id", "test_command", *JENKINS_OWN}
)
# The runner's own flags (without "--") in a Python VM launch.
PYTHON_VM_FLAGS = ("team", "stand", "regression-type", "test-name", "dataset")
# Parameters a Python launch sends to Jenkins, plus the VM flags.
PYTHON_RESERVED = frozenset(
    {"team_id", "stand_id", "regression_type", "test_name_id", "test_command", "dataset_id",
     *PYTHON_VM_FLAGS, *JENKINS_OWN}
)
# Flags argparse would expand an abbreviation into: --h means --help, and
# the runner would print usage and exit 0 without running anything.
_ARGPARSE_FLAGS = (*PYTHON_VM_FLAGS, "help")

_KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


class CustomParam(BaseModel):
    key: str
    type: ParamType = "text"
    value: str | None = None


class ParamError(ValueError):
    """A parameter can't be saved; the message is shown to the user."""


def _reserved_error(key: str, language: Language) -> str | None:
    lowered = key.lower()
    reserved = JAVA_RESERVED if language == "java" else PYTHON_RESERVED
    if lowered in reserved:
        return f"Ключ «{key}» занят служебным параметром запуска"
    if language == "python":
        # argparse (allow_abbrev) would expand --tea into --team.
        for flag in _ARGPARSE_FLAGS:
            if flag.startswith(lowered):
                return f"Ключ «{key}» совпадает с началом служебного флага --{flag}"
    return None


def _normalized(param: CustomParam, language: Language) -> CustomParam:
    key = param.key.strip()
    if not key:
        raise ParamError("Пустой ключ параметра")
    if not _KEY_RE.match(key):
        raise ParamError(f"Недопустимый ключ параметра «{key}»: только латиница, цифры, _ . -")
    error = _reserved_error(key, language)
    if error:
        raise ParamError(error)
    value = param.value.strip() if param.value is not None else ""
    if param.type == "text":
        if not value:
            raise ParamError(f"Укажите значение параметра «{key}» или выберите тип «без значения»")
        return CustomParam(key=key, type="text", value=value)
    if param.type == "bool":
        if value not in ("true", "false"):
            raise ParamError(f"Значение параметра «{key}» — только true или false")
        return CustomParam(key=key, type="bool", value=value)
    if value:
        raise ParamError(f"У параметра «{key}» с типом «без значения» не может быть значения")
    return CustomParam(key=key, type="flag", value=None)


def validate_params(params: list[CustomParam], language: Language) -> list[CustomParam]:
    """The params as they should be stored, or ParamError for the first bad one."""
    result = [_normalized(p, language) for p in params]
    seen: set[str] = set()
    for param in result:
        lowered = param.key.lower()
        if lowered in seen:
            raise ParamError(f"Параметр «{param.key}» указан дважды")
        seen.add(lowered)
    return result


def load_params(params_json: str | None) -> list[CustomParam]:
    if not params_json:
        return []
    return [CustomParam(**p) for p in json.loads(params_json)]


def dump_params(params: list[CustomParam]) -> str | None:
    if not params:
        return None
    return json.dumps([p.model_dump() for p in params], ensure_ascii=False)


def jenkins_values(params: list[CustomParam]) -> dict[str, str | None]:
    """Query values for Jenkins; None means a bare key."""
    return {p.key: p.value for p in params}


def vm_args(params: list[CustomParam]) -> list[str]:
    return [f"--{p.key}" if p.value is None else f"--{p.key}={p.value}" for p in params]
