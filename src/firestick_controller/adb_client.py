"""Safe subprocess-based interface to Android Debug Bridge."""

from __future__ import annotations

import ipaddress
import logging
import shutil
import subprocess
from dataclasses import dataclass

from .config import DeviceConfig
from .device import DeviceInfo

logger = logging.getLogger(__name__)


class AdbError(RuntimeError):
    """Base class for ADB-related failures."""


class AdbNotFoundError(AdbError):
    """Raised when the ADB executable cannot be found or started."""


class AdbTimeoutError(AdbError):
    """Raised when an ADB command exceeds its timeout."""


class AdbCommandError(AdbError):
    """Raised when ADB returns a failed command result."""


@dataclass(frozen=True)
class _CommandResult:
    stdout: str
    stderr: str
    returncode: int


class AdbClient:
    """Run ADB operations against a configured local Fire TV device."""

    def __init__(self, config: DeviceConfig, adb_path: str | None = None) -> None:
        self.config = config
        self._adb_path = adb_path

    @property
    def endpoint(self) -> str:
        address = ipaddress.ip_address(self.config.host)
        host = f"[{address}]" if address.version == 6 else str(address)
        return f"{host}:{self.config.port}"

    def _executable(self) -> str:
        executable = self._adb_path or shutil.which("adb")
        if executable is None:
            raise AdbNotFoundError(
                "ADB was not found. Install Android Platform Tools and ensure 'adb' is on PATH."
            )
        return executable

    def _run(self, arguments: list[str], *, sensitive: bool = False) -> _CommandResult:
        operation = arguments[0] if arguments else "command"
        logger.debug("Running ADB operation: %s", operation)
        try:
            result = subprocess.run(
                [self._executable(), *arguments],
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AdbNotFoundError("ADB could not be started; verify its installation and PATH") from exc
        except subprocess.TimeoutExpired as exc:
            logger.warning("ADB operation timed out: %s", operation)
            raise AdbTimeoutError(f"ADB {operation} timed out") from exc

        output = result.stdout.strip()
        error = result.stderr.strip()
        if result.returncode != 0:
            detail = "" if sensitive else (error or output)
            message = f"ADB {operation} failed (exit code {result.returncode})"
            if detail:
                message = f"{message}: {detail}"
            raise AdbCommandError(message)
        return _CommandResult(output, error, result.returncode)

    def is_installed(self) -> bool:
        """Return whether the ADB executable is available on PATH."""
        executable = self._adb_path or "adb"
        return shutil.which(executable) is not None

    def version(self) -> str:
        """Return ADB's version string, or raise a useful error."""
        result = self._run(["version"])
        return result.stdout.splitlines()[0] if result.stdout else "ADB version unavailable"

    def pair(self, pairing_code: str) -> str:
        """Pair with wireless debugging using the separately displayed pairing port."""
        port = self.config.pairing_port
        if port is None:
            raise AdbError("Set device.pairing_port to the Wireless Debugging pairing port first")
        if not isinstance(pairing_code, str) or len(pairing_code) != 6 or not pairing_code.isdigit():
            raise AdbError("Wireless debugging pairing code must contain six digits")
        logger.info("Starting wireless ADB pairing with %s:%s", self.config.host, port)
        try:
            result = self._run(
                ["pair", self._format_endpoint(port), pairing_code], sensitive=True
            )
        except AdbError:
            logger.warning("Wireless ADB pairing failed")
            raise
        logger.info("Wireless ADB pairing completed")
        return result.stdout

    def connect(self) -> str:
        """Connect to the configured ADB endpoint."""
        logger.info("Connecting to Fire TV at %s", self.endpoint)
        try:
            result = self._run(["connect", self.endpoint])
        except AdbError:
            logger.warning("Connection to Fire TV at %s failed", self.endpoint)
            raise
        message = result.stdout or result.stderr
        if "failed to connect" in message.lower() or "cannot connect" in message.lower():
            logger.warning("Connection to Fire TV at %s failed", self.endpoint)
            raise AdbCommandError(f"Could not connect to {self.endpoint}: {message}")
        logger.info("ADB connection response: %s", message or "connected")
        return message

    def is_connected(self) -> bool:
        """Check whether the configured endpoint appears as an online ADB device."""
        result = self._run(["devices"])
        return any(
            len(fields := line.split()) >= 2
            and fields[0] == self.endpoint
            and fields[1] == "device"
            for line in result.stdout.splitlines()[1:]
        )

    def device_info(self) -> DeviceInfo:
        """Retrieve the device serial and model for this endpoint."""
        if not self.is_connected():
            raise AdbError(f"No connected Fire TV found at {self.endpoint}")
        serial_result = self._run(["-s", self.endpoint, "get-serialno"])
        model_result = self._run(["-s", self.endpoint, "shell", "getprop", "ro.product.model"])
        serial = serial_result.stdout or "unknown"
        model = model_result.stdout or "unknown"
        return DeviceInfo(serial=serial, model=model)

    def disconnect(self) -> str:
        """Disconnect the configured endpoint from the local ADB server."""
        logger.info("Disconnecting from Fire TV at %s", self.endpoint)
        result = self._run(["disconnect", self.endpoint])
        logger.info("ADB disconnect response: %s", result.stdout or "disconnected")
        return result.stdout

    def _format_endpoint(self, port: int) -> str:
        address = ipaddress.ip_address(self.config.host)
        host = f"[{address}]" if address.version == 6 else str(address)
        return f"{host}:{port}"