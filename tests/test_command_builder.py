from app.execution.command_builder import FieldSpec, build_command


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
    try:
        build_command("path/to/test.py", fields, {})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "--users" in str(exc)
