"""Configuration loading and validation."""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the application configuration is missing or invalid."""


@dataclass(frozen=True)
class DeviceConfig:
    """Connection details for one Fire TV device."""

    host: str
    port: int = 5555
    pairing_port: int | None = None
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise ConfigError("device.host must be a valid IP address") from exc
        if address.is_global:
            raise ConfigError("device.host must be a local, non-public IP address")
        _validate_port("device.port", self.port)
        if self.pairing_port is not None:
            _validate_port("device.pairing_port", self.pairing_port)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ConfigError("device.timeout_seconds must be greater than zero")


@dataclass(frozen=True)
class AppConfig:
    """Application settings loaded from JSON."""

    device: DeviceConfig
    favorites: tuple[str, ...] = ()
    application_names: dict[str, str] = field(default_factory=dict)


_PACKAGE_NAME = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\Z")


def is_valid_package_name(package_name: str) -> bool:
    """Return whether a string is safe and shaped like an Android package ID."""
    return isinstance(package_name, str) and _PACKAGE_NAME.fullmatch(package_name) is not None


def _validate_port(name: str, port: int) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError(f"{name} must be an integer between 1 and 65535")


def load_config(path: str | Path) -> AppConfig:
    """Load and validate settings from a JSON file."""
    config_path = Path(path)
    try:
        data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Configuration file not found: {config_path}. "
            "Copy config/settings.example.json to config/settings.json and edit it."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read configuration file {config_path}: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("device"), dict):
        raise ConfigError("Configuration must contain a [device] object")

    device = data["device"]
    host = device.get("host")
    if not isinstance(host, str):
        raise ConfigError("device.host must be an IP address string")
    port = device.get("port", 5555)
    pairing_port = device.get("pairing_port")
    timeout_seconds = device.get("timeout_seconds", 5.0)
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise ConfigError("device.timeout_seconds must be a number")
    favorites = data.get("favorites", [])
    if not isinstance(favorites, list) or any(
        not is_valid_package_name(package_name) for package_name in favorites
    ):
        raise ConfigError("favorites must be a list of valid Android package names")
    if len(set(favorites)) != len(favorites):
        raise ConfigError("favorites must not contain duplicate package names")
    application_names = data.get("application_names", {})
    if not isinstance(application_names, dict) or any(
        not is_valid_package_name(package_name)
        or not isinstance(display_name, str)
        or not display_name.strip()
        for package_name, display_name in application_names.items()
    ):
        raise ConfigError("application_names must map package names to non-empty display names")
    return AppConfig(
        device=DeviceConfig(
            host=host,
            port=port,
            pairing_port=pairing_port,
            timeout_seconds=float(timeout_seconds),
        ),
        favorites=tuple(favorites),
        application_names=application_names,
    )


def save_app_preferences(
    path: str | Path,
    favorites: tuple[str, ...],
    application_names: dict[str, str] | None = None,
) -> None:
    """Atomically save app favorites and optional display-name overrides."""
    config_path = Path(path)
    try:
        data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot update configuration file {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Configuration must contain a JSON object")
    if any(not is_valid_package_name(package_name) for package_name in favorites):
        raise ConfigError("favorites must contain valid Android package names")

    data["favorites"] = list(favorites)
    if application_names is not None:
        data["application_names"] = application_names

    _write_json_atomically(config_path, data)


def save_config(path: str | Path, config: AppConfig) -> None:
    """Persist device connection details and app preferences as JSON."""
    config_path = Path(path)
    try:
        data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot update configuration file {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Configuration must contain a JSON object")

    device_settings = data.get("device", {})
    if not isinstance(device_settings, dict):
        device_settings = {}
    device_settings.update(
        {
            "host": config.device.host,
            "port": config.device.port,
            "pairing_port": config.device.pairing_port,
            "timeout_seconds": config.device.timeout_seconds,
        }
    )
    data["device"] = device_settings
    data["favorites"] = list(config.favorites)
    data["application_names"] = config.application_names
    _write_json_atomically(
        config_path,
        data,
    )


def save_automation_data(path: str | Path, automations: list[dict[str, Any]]) -> None:
    """Update automation data without replacing other user configuration."""
    config_path = Path(path)
    try:
        data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot update configuration file {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Configuration must contain a JSON object")
    data["automations"] = automations
    _write_json_atomically(config_path, data)


def _write_json_atomically(config_path: Path, data: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=config_path.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, config_path)
    except OSError as exc:
        raise ConfigError(f"Cannot update configuration file {config_path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)