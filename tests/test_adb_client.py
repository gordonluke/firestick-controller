import subprocess
from unittest.mock import Mock, patch

import pytest

from firestick_controller.adb_client import (
    AdbClient,
    AdbCommandError,
    AdbNotFoundError,
    AdbTimeoutError,
)
from firestick_controller.config import DeviceConfig


@pytest.fixture
def client():
    return AdbClient(DeviceConfig("192.168.1.25", port=5555, pairing_port=37000))


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], stdout=stdout, stderr=stderr, returncode=returncode)


def test_detect_adb_installed(client):
    with patch("firestick_controller.adb_client.shutil.which", return_value="/usr/bin/adb"):
        assert client.is_installed()


def test_detect_adb_missing(client):
    with patch("firestick_controller.adb_client.shutil.which", return_value=None):
        assert not client.is_installed()
        with pytest.raises(AdbNotFoundError, match="ADB was not found"):
            client.version()


def test_explicit_adb_path_is_checked(client):
    client = AdbClient(client.config, adb_path="/custom/bin/adb")
    with patch("firestick_controller.adb_client.shutil.which", return_value=None):
        assert not client.is_installed()


def test_adb_version(client):
    with patch("firestick_controller.adb_client.shutil.which", return_value="/usr/bin/adb"):
        with patch("firestick_controller.adb_client.subprocess.run", return_value=completed("Android Debug Bridge version 1.0.41\n")):
            assert client.version() == "Android Debug Bridge version 1.0.41"


def test_connect_success(client):
    with patch.object(client, "_run", return_value=Mock(stdout="connected to 192.168.1.25:5555")) as run:
        assert client.connect() == "connected to 192.168.1.25:5555"
    run.assert_called_once_with(["connect", "192.168.1.25:5555"])


def test_connect_failure(client):
    with patch.object(client, "_run", return_value=Mock(stdout="failed to connect to 192.168.1.25:5555")):
        with pytest.raises(AdbCommandError, match="Could not connect"):
            client.connect()


@pytest.mark.parametrize(
    ("device_output", "expected"),
    [
        ("List of devices attached\n192.168.1.25:5555 device\n", True),
        ("List of devices attached\n192.168.1.25:5555 offline\n", False),
        ("List of devices attached\nother-device device\n", False),
    ],
)
def test_device_connection_status(client, device_output, expected):
    with patch.object(client, "_run", return_value=Mock(stdout=device_output)):
        assert client.is_connected() is expected


def test_device_info(client):
    with patch.object(client, "is_connected", return_value=True):
        with patch.object(
            client,
            "_run",
            side_effect=[Mock(stdout="G070VM"), Mock(stdout="AFTMM")],
        ):
            info = client.device_info()
    assert (info.serial, info.model) == ("G070VM", "AFTMM")


def test_pair_uses_configured_pairing_port_without_logging_code(client, caplog):
    with patch.object(client, "_run", return_value=Mock(stdout="Successfully paired")) as run:
        assert client.pair("123456") == "Successfully paired"
    run.assert_called_once_with(["pair", "192.168.1.25:37000", "123456"], sensitive=True)
    assert "123456" not in caplog.text


def test_pair_failure_does_not_expose_pairing_code(client):
    with patch("firestick_controller.adb_client.shutil.which", return_value="/usr/bin/adb"):
        with patch(
            "firestick_controller.adb_client.subprocess.run",
            return_value=completed(stderr="pairing failed", returncode=1),
        ):
            with pytest.raises(AdbCommandError) as error:
                client.pair("123456")
    assert "123456" not in str(error.value)


def test_timeout_is_translated_to_adb_error(client):
    with patch("firestick_controller.adb_client.shutil.which", return_value="/usr/bin/adb"):
        with patch(
            "firestick_controller.adb_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="adb", timeout=5),
        ):
            with pytest.raises(AdbTimeoutError, match="timed out"):
                client.version()


def test_disconnect_uses_configured_endpoint(client):
    with patch.object(client, "_run", return_value=Mock(stdout="disconnected")) as run:
        assert client.disconnect() == "disconnected"
    run.assert_called_once_with(["disconnect", "192.168.1.25:5555"])