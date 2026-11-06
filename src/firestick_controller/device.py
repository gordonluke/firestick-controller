"""Device information returned by ADB."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceInfo:
    """Identifying information reported by a connected device."""

    serial: str
    model: str