"""Command-line entry point for Milestone 1 connection checks."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from .adb_client import AdbClient, AdbError
from .applications import ApplicationManager
from .config import ConfigError, load_config
from .remote import RemoteAction, RemoteControl

logger = logging.getLogger("firestick_controller")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Connect to a Fire TV using local ADB")
    parser.add_argument("--config", default="config/settings.json", help="JSON settings file")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("connect", "status", "disconnect", "pair"):
        commands.add_parser(action)

    press_parser = commands.add_parser("press", help="Send a remote-control button")
    press_parser.add_argument(
        "button",
        choices=(
            "home", "back", "menu", "up", "down", "left", "right", "select", "ok",
            "play-pause", "rewind", "fast-forward", "volume-up", "volume-down", "mute",
        ),
    )
    text_parser = commands.add_parser(
        "text", help="Send keyboard input to a focused Fire TV text field"
    )
    text_parser.add_argument("value", help="Text with letters, numbers, spaces, or . , _ @ / + : -")

    apps_parser = commands.add_parser("apps", help="List, launch, and favorite applications")
    app_commands = apps_parser.add_subparsers(dest="apps_action", required=True)
    list_parser = app_commands.add_parser("list", help="List installed applications")
    list_parser.add_argument("--all", action="store_true", help="Include system packages")
    launch_parser = app_commands.add_parser("launch", help="Launch an application by package ID")
    launch_parser.add_argument("package_name")
    app_commands.add_parser("favorites", help="List favorite applications")
    add_favorite_parser = app_commands.add_parser("favorite-add", help="Add an application favorite")
    add_favorite_parser.add_argument("package_name")
    remove_favorite_parser = app_commands.add_parser(
        "favorite-remove", help="Remove an application favorite"
    )
    remove_favorite_parser.add_argument("package_name")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arguments = _parser().parse_args(argv)
    try:
        config = load_config(Path(arguments.config))
        client = AdbClient(config.device)
        applications = ApplicationManager(client, config, arguments.config)
        if arguments.action == "pair":
            pairing_code = getpass.getpass("Wireless debugging pairing code: ")
            print(client.pair(pairing_code))
        elif arguments.action == "connect":
            print(client.connect())
            if client.is_connected():
                _show_device_info(client)
        elif arguments.action == "status":
            print(f"ADB installed: {'yes' if client.is_installed() else 'no'}")
            if client.is_installed():
                print(f"ADB version: {client.version()}")
            connected = client.is_connected()
            print(f"Device connected: {'yes' if connected else 'no'}")
            if connected:
                _show_device_info(client)
        elif arguments.action == "press":
            _require_connection(client)
            RemoteControl(client).press(arguments.button)
            print(f"Sent remote action: {arguments.button}")
        elif arguments.action == "text":
            _require_connection(client)
            logger.warning(
                "Text is sent as key events to the focused app; without a text field, "
                "the app may treat characters as shortcuts"
            )
            RemoteControl(client).enter_text(arguments.value)
            print(f"Sent text input ({len(arguments.value)} characters)")
        elif arguments.action == "apps":
            _require_connection(client)
            _handle_apps_command(applications, arguments)
        else:
            print(client.disconnect())
    except (ConfigError, AdbError) as exc:
        logger.error("%s", exc)
        return 1
    return 0


def _show_device_info(client: AdbClient) -> None:
    info = client.device_info()
    print(f"Serial: {info.serial}")
    print(f"Model: {info.model}")


def _require_connection(client: AdbClient) -> None:
    if not client.is_connected():
        raise AdbError("No connected Fire TV found; run 'firestick-controller connect' first")


def _handle_apps_command(applications: ApplicationManager, arguments: argparse.Namespace) -> None:
    if arguments.apps_action == "list":
        for application in applications.list_applications(include_system=arguments.all):
            marker = "* " if application.is_favorite else "  "
            print(f"{marker}{application.display_name}  ({application.package_name})")
    elif arguments.apps_action == "launch":
        applications.launch(arguments.package_name)
        print(f"Launched {arguments.package_name}")
    elif arguments.apps_action == "favorites":
        favorite_packages = set(applications.favorites)
        installed_apps = applications.list_applications(include_system=True)
        applications_by_package = {
            application.package_name: application for application in installed_apps
        }
        if not favorite_packages:
            print("No favorite applications configured")
        for package_name in sorted(favorite_packages):
            application = applications_by_package.get(package_name)
            if application is None:
                print(f"{package_name}  (not installed)")
            else:
                print(f"{application.display_name}  ({package_name})")
    elif arguments.apps_action == "favorite-add":
        applications.add_favorite(arguments.package_name)
        print(f"Added favorite: {arguments.package_name}")
    else:
        applications.remove_favorite(arguments.package_name)
        print(f"Removed favorite: {arguments.package_name}")


if __name__ == "__main__":
    sys.exit(main())