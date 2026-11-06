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


def test_input_keyevent_uses_device_keyevent(client):
    with patch.object(client, "_run") as run:
        client.input_keyevent(23)
    run.assert_called_once_with(
        ["-s", "192.168.1.25:5555", "shell", "input", "keyevent", "23"]
    )


@pytest.mark.parametrize("keycode", [-1, True, "23"])
def test_input_keyevent_rejects_invalid_keycodes(client, keycode):
    from firestick_controller.adb_client import AdbError

    with pytest.raises(AdbError, match="keycode"):
        client.input_keyevent(keycode)


def test_input_text_encodes_spaces(client):
    with patch.object(client, "_run") as run:
        client.input_text("hello fire tv")
    run.assert_called_once_with(
        ["-s", "192.168.1.25:5555", "shell", "input", "text", "hello%sfire%stv"]
    )


@pytest.mark.parametrize("text", ["", "hello; reboot", "two\nlines", "hello%sworld"])
def test_input_text_rejects_unsupported_characters(client, text):
    from firestick_controller.adb_client import AdbError

    with pytest.raises(AdbError, match="Text input supports"):
        client.input_text(text)


def test_list_packages_parses_adb_output(client):
    with patch.object(
        client,
        "_run",
        return_value=Mock(stdout="package:com.netflix.ninja\npackage:com.spotify.tv.android\n"),
    ) as run:
        assert client.list_packages() == ["com.netflix.ninja", "com.spotify.tv.android"]
    run.assert_called_once_with(
        ["-s", "192.168.1.25:5555", "shell", "pm", "list", "packages"]
    )


def test_list_packages_can_filter_system_apps(client):
    with patch.object(client, "_run", return_value=Mock(stdout="")) as run:
        client.list_packages(include_system=False)
    run.assert_called_once_with(
        ["-s", "192.168.1.25:5555", "shell", "pm", "list", "packages", "-3"]
    )


def test_launch_package_uses_monkey_launcher(client):
    with patch.object(client, "_run", return_value=Mock(stdout="Events injected: 1")) as run:
        assert client.launch_package("com.netflix.ninja") == "Events injected: 1"
    run.assert_called_once_with(
        ["-s", "192.168.1.25:5555", "shell", "monkey", "-p", "com.netflix.ninja", "1"]
    )


def test_launch_package_force_stops_before_launch(client):
    with patch.object(
        client,
        "_run",
        side_effect=[Mock(stdout=""), Mock(stdout="Events injected: 1")],
    ) as run:
        client.launch_package("com.netflix.ninja", force_stop_first=True)

    assert [call.args[0] for call in run.call_args_list] == [
        ["-s", "192.168.1.25:5555", "shell", "am", "force-stop", "com.netflix.ninja"],
        ["-s", "192.168.1.25:5555", "shell", "monkey", "-p", "com.netflix.ninja", "1"],
    ]


def test_launch_package_force_stop_option_must_be_boolean(client):
    from firestick_controller.adb_client import AdbError

    with pytest.raises(AdbError, match="must be a boolean"):
        client.launch_package("com.netflix.ninja", force_stop_first="yes")


@pytest.mark.parametrize("package_name", ["bad package", "com.example;reboot", "not-a-package"])
def test_launch_package_rejects_invalid_package_name(client, package_name):
    from firestick_controller.adb_client import AdbError

    with pytest.raises(AdbError, match="package name is invalid"):
        client.launch_package(package_name)


def test_launch_package_reports_package_without_launchable_activity(client):
    with patch.object(
        client,
        "_run",
        return_value=Mock(stdout="No activities found to run, monkey aborted."),
    ):
        with pytest.raises(AdbCommandError, match="No launchable activity"):
            client.launch_package("com.example.app")