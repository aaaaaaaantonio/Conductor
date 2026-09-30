from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass
class FlagSpec:
    name: str
    kind: Literal["bool", "value"]
    default: Optional[str] = None


@dataclass
class FieldSpec:
    label: str
    flag_name: str
    type: Literal["text", "number", "select", "checkbox", "path"]
    required: bool
    options: Optional[list[str]] = None


def build_command(
    path: str,
    fields: list[FieldSpec],
    values: dict[str, Any],
    flags: Optional[list[FlagSpec]] = None,
) -> list[str]:
    """Fields come first, in form order. A flag sharing a field's name only
    supplies that field's default; every other flag is appended after the
    fields: a bool flag bare, a value flag as `name=default` (skipped when it
    has no default)."""
    flags = flags or []
    defaults = {f.name: f.default for f in flags if f.kind == "value"}
    field_names = {field.flag_name for field in fields}

    command = [path]
    for field in fields:
        value = values.get(field.flag_name)
        if field.type == "checkbox":
            if value:
                command.append(field.flag_name)
            continue
        if value is None or value == "":
            value = defaults.get(field.flag_name)
        if value is None or value == "":
            if field.required:
                raise ValueError(f"Не заполнено обязательное поле {field.flag_name}")
            continue
        command.append(f"{field.flag_name}={value}")

    for flag in flags:
        if flag.name in field_names:
            continue
        if flag.kind == "bool":
            command.append(flag.name)
        elif flag.default is not None and flag.default != "":
            command.append(f"{flag.name}={flag.default}")
    return command
