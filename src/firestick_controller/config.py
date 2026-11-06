"""Configuration loading and validation."""

from __future__ import annotations

import ipaddress
import json
import math
from dataclasses import dataclass
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
    return AppConfig(
        device=DeviceConfig(
            host=host,
            port=port,
            pairing_port=pairing_port,
            timeout_seconds=float(timeout_seconds),
        )
    )