import json
from unittest.mock import Mock

import pytest

from firestick_controller.applications import ApplicationManager
from firestick_controller.adb_client import AdbError
from firestick_controller.config import ConfigError, load_config


@pytest.fixture
def manager_and_client(tmp_path):
    config_path = tmp_path / "settings.json"
    config_path.write_text(
        json.dumps(
            {
                "device": {"host": "192.168.1.25"},
                "favorites": ["com.netflix.ninja"],
                "application_names": {"com.example.player": "My Player"},
            }
        ),
        encoding="utf-8",
    )
    client = Mock()
    config = load_config(config_path)
    return ApplicationManager(client, config, config_path), client, config_path


def test_list_applications_uses_friendly_names_and_favorite_status(manager_and_client):
    manager, client, _ = manager_and_client
    client.list_packages.return_value = [
        "com.netflix.ninja",
        "com.example.player",
        "com.unknown.package",
    ]

    applications = manager.list_applications()

    assert [(app.display_name, app.package_name, app.is_favorite) for app in applications] == [
        ("com.unknown.package", "com.unknown.package", False),
        ("My Player", "com.example.player", False),
        ("Netflix", "com.netflix.ninja", True),
    ]
    client.list_packages.assert_called_once_with(include_system=False)


def test_launch_requires_installed_package(manager_and_client):
    manager, client, _ = manager_and_client
    client.list_packages.return_value = ["com.netflix.ninja"]
    client.launch_package.return_value = "Events injected: 1"

    assert manager.launch("com.netflix.ninja") == "Events injected: 1"
    client.launch_package.assert_called_once_with(
        "com.netflix.ninja",
        force_stop_first=False,
    )


def test_launch_can_force_stop_before_starting(manager_and_client):
    manager, client, _ = manager_and_client
    client.list_packages.return_value = ["com.netflix.ninja"]
    client.launch_package.return_value = "Events injected: 1"

    manager.launch("com.netflix.ninja", force_stop_first=True)

    client.launch_package.assert_called_once_with(
        "com.netflix.ninja",
        force_stop_first=True,
    )


def test_launch_rejects_uninstalled_package(manager_and_client):
    manager, client, _ = manager_and_client
    client.list_packages.return_value = []

    with pytest.raises(AdbError, match="not installed"):
        manager.launch("com.missing.app")
    client.launch_package.assert_not_called()


def test_add_favorite_persists_to_config(manager_and_client):
    manager, client, config_path = manager_and_client
    client.list_packages.return_value = ["com.netflix.ninja", "com.example.player"]

    manager.add_favorite("com.example.player")

    assert manager.favorites == ("com.netflix.ninja", "com.example.player")
    assert load_config(config_path).favorites == manager.favorites


def test_add_existing_favorite_does_not_duplicate(manager_and_client):
    manager, client, _ = manager_and_client
    client.list_packages.return_value = ["com.netflix.ninja"]

    manager.add_favorite("com.netflix.ninja")

    assert manager.favorites == ("com.netflix.ninja",)


def test_remove_favorite_persists_to_config(manager_and_client):
    manager, _, config_path = manager_and_client

    manager.remove_favorite("com.netflix.ninja")

    assert manager.favorites == ()
    assert load_config(config_path).favorites == ()


def test_add_favorite_rejects_uninstalled_package(manager_and_client):
    manager, client, _ = manager_and_client
    client.list_packages.return_value = []

    with pytest.raises(AdbError, match="not installed"):
        manager.add_favorite("com.missing.app")


def test_remove_non_favorite_reports_error(manager_and_client):
    manager, _, _ = manager_and_client

    with pytest.raises(AdbError, match="not a favorite"):
        manager.remove_favorite("com.example.player")


def test_invalid_package_name_is_rejected(manager_and_client):
    manager, _, _ = manager_and_client

    with pytest.raises(ConfigError, match="package name is invalid"):
        manager.launch("com.example;reboot")