import pytest

from app.execution.command_builder import FieldSpec, FlagSpec, build_command


def test_build_command_orders_flags_and_applies_type_rules():
    fields = [
        FieldSpec(label="Users", flag_name="--users", type="number", required=True),
        FieldSpec(label="Verbose", flag_name="--verbose", type="checkbox", required=False),
        FieldSpec(label="Timeout", flag_name="--timeout", type="number", required=False),
    ]
    values = {"--users": 25, "--verbose": False, "--timeout": 300}

    command = build_command("tests/checkout/test_checkout.py", fields, values)

    assert command == [
        "tests/checkout/test_checkout.py",
        "--users=25",
        "--timeout=300",
    ]


def test_build_command_checkbox_true_is_bare_flag():
    fields = [FieldSpec(label="Verbose", flag_name="--verbose", type="checkbox", required=False)]
    command = build_command("path/to/test.py", fields, {"--verbose": True})
    assert command == ["path/to/test.py", "--verbose"]


def test_build_command_missing_required_field_raises():
    fields = [FieldSpec(label="Users", flag_name="--users", type="number", required=True)]
    with pytest.raises(ValueError, match="--users"):
        build_command("path/to/test.py", fields, {})


def test_build_command_appends_flags_not_covered_by_fields():
    fields = [FieldSpec(label="Users", flag_name="--users", type="number", required=True)]
    flags = [
        FlagSpec(name="--headless", kind="bool"),
        FlagSpec(name="--env", kind="value", default="stage"),
        FlagSpec(name="--no-default", kind="value"),
    ]

    command = build_command("path/to/test.py", fields, {"--users": 5}, flags)

    assert command == ["path/to/test.py", "--users=5", "--headless", "--env=stage"]


def test_build_command_flag_default_fills_empty_field():
    fields = [FieldSpec(label="Env", flag_name="--env", type="text", required=True)]
    flags = [FlagSpec(name="--env", kind="value", default="stage")]

    assert build_command("t.py", fields, {"--env": ""}, flags) == ["t.py", "--env=stage"]
    assert build_command("t.py", fields, {}, flags) == ["t.py", "--env=stage"]
    assert build_command("t.py", fields, {"--env": "prod"}, flags) == ["t.py", "--env=prod"]


def test_build_command_checkbox_field_overrides_bool_flag():
    fields = [FieldSpec(label="Verbose", flag_name="--verbose", type="checkbox", required=False)]
    flags = [FlagSpec(name="--verbose", kind="bool")]

    assert build_command("t.py", fields, {"--verbose": False}, flags) == ["t.py"]
    assert build_command("t.py", fields, {"--verbose": True}, flags) == ["t.py", "--verbose"]
