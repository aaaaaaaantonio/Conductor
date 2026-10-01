import json
import time

from app import credentials
from app.config import (
    CREDS_MAX_LIFETIME,
    CREDS_REMEMBER_IDLE_TTL,
    CREDS_SESSION_IDLE_TTL,
)
from app.credentials import Credentials, decode, encode

NOW = 1_800_000_000


def _creds(remember=False, issued_at=NOW):
    return Credentials(
        jenkins_user="alice",
        jenkins_token="jt-secret",
        allure_token="at-secret",
        remember=remember,
        issued_at=issued_at,
    )


def test_round_trip():
    decoded = decode(encode(_creds(), now=NOW), now=NOW + 1)
    assert decoded.creds == _creds()
    assert decoded.refreshed_at == NOW


def test_cookie_does_not_contain_plain_tokens():
    value = encode(_creds(), now=NOW)
    assert "jt-secret" not in value
    assert "alice" not in value


def test_repr_hides_tokens():
    text = repr(_creds())
    assert "jt-secret" not in text
    assert "at-secret" not in text


def test_tampered_or_garbage_cookie_is_rejected():
    value = encode(_creds(), now=NOW)
    tampered = value[:-4] + ("AAAA" if not value.endswith("AAAA") else "BBBB")
    assert decode(tampered, now=NOW) is None
    assert decode("not-a-token", now=NOW) is None


def test_cookie_from_another_key_is_rejected(monkeypatch):
    value = encode(_creds(), now=NOW)
    monkeypatch.setattr(credentials, "_fernet_instance", None)
    monkeypatch.setattr(credentials, "CONDUCTOR_SECRET_KEY", "another-key")
    assert decode(value, now=NOW) is None


def test_session_mode_expires_after_idle_window():
    value = encode(_creds(), now=NOW)
    assert decode(value, now=NOW + CREDS_SESSION_IDLE_TTL) is not None
    assert decode(value, now=NOW + CREDS_SESSION_IDLE_TTL + 1) is None


def test_remember_mode_expires_after_longer_idle_window():
    value = encode(_creds(remember=True), now=NOW)
    assert decode(value, now=NOW + CREDS_SESSION_IDLE_TTL + 1) is not None
    assert decode(value, now=NOW + CREDS_REMEMBER_IDLE_TTL + 1) is None


def test_sliding_refresh_extends_idle_window():
    # Re-issued a day before the idle window would run out.
    later = NOW + CREDS_REMEMBER_IDLE_TTL - 86400
    value = encode(_creds(remember=True), now=later)
    assert decode(value, now=NOW + CREDS_REMEMBER_IDLE_TTL + 1) is not None


def test_max_lifetime_caps_sliding_refresh():
    last_refresh = NOW + CREDS_MAX_LIFETIME - 10
    value = encode(_creds(remember=True), now=last_refresh)
    assert decode(value, now=NOW + CREDS_MAX_LIFETIME) is not None
    assert decode(value, now=NOW + CREDS_MAX_LIFETIME + 1) is None


def test_default_now_is_current_time():
    value = encode(_creds(issued_at=int(time.time())))
    assert decode(value) is not None


def test_cookie_saved_before_zephyr_existed_still_decodes():
    payload = json.dumps(
        {
            "jenkins_user": "alice",
            "jenkins_token": "jt-secret",
            "allure_token": "at-secret",
            "remember": False,
            "issued_at": NOW,
        }
    ).encode()
    value = credentials._fernet().encrypt_at_time(payload, NOW).decode()

    decoded = decode(value, now=NOW + 1)

    assert decoded is not None
    assert decoded.creds.zephyr_token is None


def test_repr_hides_zephyr_token():
    creds = Credentials(jenkins_user="alice", jenkins_token="jt", zephyr_token="zt-secret")
    assert "zt-secret" not in repr(creds)


def test_vm_env_has_both_tokens():
    creds = Credentials(jenkins_user="a", jenkins_token="j", allure_token="al", zephyr_token="ze")
    assert creds.vm_env() == {"ALLURE_TOKEN": "al", "ZEPHYR_TOKEN": "ze"}


def test_vm_env_is_none_without_either_token():
    assert Credentials(jenkins_user="a", jenkins_token="j", allure_token="al").vm_env() is None
    assert Credentials(jenkins_user="a", jenkins_token="j", zephyr_token="ze").vm_env() is None
