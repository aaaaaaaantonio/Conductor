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


def build_command(path: str, fields: list[FieldSpec], values: dict[str, Any]) -> list[str]:
    command = [path]
    for field in fields:
        if field.flag_name not in values:
            if field.required:
                raise ValueError(f"Missing required field for flag {field.flag_name}")
            continue
        value = values[field.flag_name]
        if field.type == "checkbox":
            if value:
                command.append(field.flag_name)
            continue
        if value is None or value == "":
            if field.required:
                raise ValueError(f"Missing required field for flag {field.flag_name}")
            continue
        command.append(f"{field.flag_name}={value}")
    return command
