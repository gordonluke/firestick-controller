import json

import pytest

from firestick_controller.config import (
    AppConfig,
    ConfigError,
    DeviceConfig,
    load_config,
    save_config,
    save_app_preferences,
)
from firestick_controller.config import (
    ConfigError,
    DeviceConfig,
    load_config,
    save_app_preferences,
)


def test_load_config_reads_device_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"device": {"host": "192.168.1.25", "port": 5556, "pairing_port": 37000}}
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.device == DeviceConfig("192.168.1.25", 5556, 37000, 5.0)


@pytest.mark.parametrize(
    ("host", "port"),
    [("not-an-ip", 5555), ("8.8.8.8", 5555), ("192.168.1.2", 0), ("192.168.1.2", 65536)],
)
def test_invalid_device_configuration_is_rejected(host, port):
    with pytest.raises(ConfigError):
        DeviceConfig(host=host, port=port)


def test_missing_config_has_setup_guidance(tmp_path):
    with pytest.raises(ConfigError, match="settings.example.json"):
        load_config(tmp_path / "missing.json")


def test_invalid_json_is_reported(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ConfigError, match="Cannot read configuration"):
        load_config(path)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), "5", True])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(ConfigError, match="timeout_seconds"):
        DeviceConfig(host="192.168.1.2", timeout_seconds=timeout)


def test_load_config_reads_favorites_and_display_names(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "device": {"host": "192.168.1.25"},
                "favorites": ["com.netflix.ninja"],
                "application_names": {"com.netflix.ninja": "Netflix TV"},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.favorites == ("com.netflix.ninja",)
    assert config.application_names == {"com.netflix.ninja": "Netflix TV"}


@pytest.mark.parametrize(
    "preferences",
    [
        {"favorites": "com.netflix.ninja"},
        {"favorites": ["bad package"]},
        {"favorites": ["com.netflix.ninja", "com.netflix.ninja"]},
        {"application_names": {"com.netflix.ninja": "  "}},
        {"application_names": {"bad package": "Netflix"}},
    ],
)
def test_invalid_app_preferences_are_rejected(tmp_path, preferences):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"device": {"host": "192.168.1.25"}, **preferences}), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(path)


def test_save_favorites_preserves_device_and_name_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "device": {"host": "192.168.1.25", "port": 5556},
                "application_names": {"com.netflix.ninja": "Netflix TV"},
            }
        ),
        encoding="utf-8",
    )

    save_app_preferences(
        path,
        ("com.netflix.ninja",),
        {"com.netflix.ninja": "Netflix TV"},
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["device"] == {"host": "192.168.1.25", "port": 5556}
    assert saved["favorites"] == ["com.netflix.ninja"]
    assert saved["application_names"] == {"com.netflix.ninja": "Netflix TV"}


def test_save_config_persists_connection_and_app_preferences(tmp_path):
    path = tmp_path / "settings.json"
    config = AppConfig(
        device=DeviceConfig("192.168.1.25", port=5566, pairing_port=37000),
        favorites=("com.netflix.ninja",),
        application_names={"com.netflix.ninja": "Netflix"},
    )

    save_config(path, config)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["device"] == {
        "host": "192.168.1.25",
        "port": 5566,
        "pairing_port": 37000,
        "timeout_seconds": 5.0,
    }
    assert saved["favorites"] == ["com.netflix.ninja"]
    assert saved["application_names"] == {"com.netflix.ninja": "Netflix"}


def test_save_config_preserves_unknown_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "device": {"host": "192.168.1.25", "custom_option": "keep"},
                "automation_sequences": [{"name": "existing"}],
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig(device=DeviceConfig("192.168.1.26"))

    save_config(path, config)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["device"]["custom_option"] == "keep"
    assert saved["automation_sequences"] == [{"name": "existing"}]