"""Command-line entry point for Milestone 1 connection checks."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from .adb_client import AdbClient, AdbError
from .config import ConfigError, load_config

logger = logging.getLogger("firestick_controller")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Connect to a Fire TV using local ADB")
    parser.add_argument("--config", default="config/settings.json", help="JSON settings file")
    parser.add_argument("action", choices=("connect", "status", "disconnect", "pair"))
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arguments = _parser().parse_args(argv)
    try:
        config = load_config(Path(arguments.config))
        client = AdbClient(config.device)
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


if __name__ == "__main__":
    sys.exit(main())