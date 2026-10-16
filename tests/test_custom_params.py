import pytest

from app.test_params import CustomParam as P
from app.test_params import (
    ParamError,
    dump_params,
    jenkins_values,
    load_params,
    validate_params,
    vm_args,
)


def test_normalizes_text_and_flag():
    out = validate_params(
        [P(key=" env ", type="text", value="  stage "), P(key="headless", type="flag", value="")],
        "java",
    )
    assert out == [
        P(key="env", type="text", value="stage"),
        P(key="headless", type="flag", value=None),
    ]


@pytest.mark.parametrize(
    "param, fragment",
    [
        (P(key="", type="flag"), "Пустой ключ"),
        (P(key="-x", type="flag"), "Недопустимый ключ"),
        (P(key="ключ", type="flag"), "Недопустимый ключ"),
        (P(key="env", type="text", value="  "), "выберите тип «без значения»"),
        (P(key="env", type="text", value=None), "выберите тип «без значения»"),
        (P(key="retry", type="bool", value="yes"), "true или false"),
        (P(key="retry", type="bool", value="True"), "true или false"),
        (P(key="headless", type="flag", value="1"), "не может быть значения"),
    ],
)
def test_rejects_bad_param(param, fragment):
    with pytest.raises(ParamError, match=fragment):
        validate_params([param], "java")


def test_rejects_duplicate_keys_case_insensitively():
    with pytest.raises(ParamError, match="указан дважды"):
        validate_params([P(key="a", type="flag"), P(key="A", type="flag")], "java")


@pytest.mark.parametrize("key", ["team_id", "Team_ID", "THREAD_MODE", "part"])
def test_java_rejects_reserved_key_any_case(key):
    with pytest.raises(ParamError, match="служебным"):
        validate_params([P(key=key, type="flag")], "java")


@pytest.mark.parametrize("key", ["dataset_id", "test-name", "tea", "test", "regression", "Stan"])
def test_python_rejects_reserved_and_vm_flag_prefix(key):
    with pytest.raises(ParamError):
        validate_params([P(key=key, type="flag")], "python")


def test_python_accepts_key_longer_than_flag():
    validate_params([P(key="teams", type="flag")], "python")


def test_java_accepts_python_only_names():
    validate_params([P(key="dataset", type="flag")], "java")


def test_dump_load_roundtrip_and_empty():
    ps = [P(key="retry", type="bool", value="false"), P(key="headless", type="flag")]
    assert load_params(dump_params(ps)) == ps
    assert dump_params([]) is None
    assert load_params(None) == []


def test_jenkins_values_and_vm_args():
    ps = [
        P(key="env", type="text", value="a b"),
        P(key="retry", type="bool", value="true"),
        P(key="headless", type="flag"),
    ]
    assert jenkins_values(ps) == {"env": "a b", "retry": "true", "headless": None}
    assert vm_args(ps) == ["--env=a b", "--retry=true", "--headless"]


@pytest.mark.parametrize("key", ["token", "delay", "Cause"])
@pytest.mark.parametrize("language", ["java", "python"])
def test_rejects_jenkins_own_query_params(key, language):
    # buildWithParameters consumes these itself (quiet period, trigger token).
    with pytest.raises(ParamError, match="служебным"):
        validate_params([P(key=key, type="flag")], language)


@pytest.mark.parametrize("key", ["h", "he", "help"])
def test_python_rejects_abbreviations_of_help(key):
    # argparse would expand --h into --help: the runner prints usage and exits 0.
    with pytest.raises(ParamError, match="--help"):
        validate_params([P(key=key, type="flag")], "python")
