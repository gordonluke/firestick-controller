import json

import pytest

from firestick_controller.config import ConfigError, DeviceConfig, load_config


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