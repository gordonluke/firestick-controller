"""Installed application discovery, launching, and favorites."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

from .adb_client import AdbClient, AdbError
from .config import AppConfig, ConfigError, is_valid_package_name, save_app_preferences

logger = logging.getLogger(__name__)

_KNOWN_APPLICATION_NAMES = {
    "air.ITVMobilePlayer": "ITVX",
    "com.amazon.firetv.youtube": "YouTube",
    "com.apple.atve.amazon.appletv": "Apple TV",
    "com.bskyb.nowtv.beta": "NOW",
    "com.channel4.ondemand": "Channel 4",
    "com.dazn": "DAZN",
    "com.discovery.discoplus": "discovery+",
    "com.disney.disneyplus": "Disney+",
    "com.netflix.ninja": "Netflix",
    "com.spotify.tv.android": "Spotify",
    "com.viaplay.android": "Viaplay",
    "org.mozilla.tv.firefox": "Firefox",
    "tv.twitch.android.viewer": "Twitch",
    "uk.co.bbc.iplayer": "BBC iPlayer",
    "uk.co.uktv.dave": "U",
}


@dataclass(frozen=True)
class Application:
    """An installed package and the name shown to the user."""

    package_name: str
    display_name: str
    is_favorite: bool


class ApplicationManager:
    """Manage installed Fire TV apps and config-backed favorites."""

    def __init__(
        self,
        adb_client: AdbClient,
        config: AppConfig,
        config_path: str | Path,
    ) -> None:
        self._adb_client = adb_client
        self._config = config
        self._config_path = Path(config_path)

    @property
    def favorites(self) -> tuple[str, ...]:
        """Return the configured favorite package IDs."""
        return self._config.favorites

    def list_applications(self, include_system: bool = False) -> list[Application]:
        """List installed apps, showing third-party packages by default."""
        package_names = self._adb_client.list_packages(include_system=include_system)
        aliases = self._config.application_names
        favorites = set(self._config.favorites)
        applications = [
            Application(
                package_name=package_name,
                display_name=aliases.get(
                    package_name,
                    _KNOWN_APPLICATION_NAMES.get(package_name, package_name),
                ),
                is_favorite=package_name in favorites,
            )
            for package_name in package_names
        ]
        return sorted(applications, key=lambda application: application.display_name.casefold())

    def launch(self, package_name: str, force_stop_first: bool = False) -> str:
        """Launch an installed app by its package name."""
        self._validate_package_name(package_name)
        if package_name not in self._adb_client.list_packages(include_system=True):
            raise AdbError(f"Application package is not installed: {package_name}")
        result = self._adb_client.launch_package(
            package_name,
            force_stop_first=force_stop_first,
        )
        logger.info("Launched application package %s", package_name)
        return result

    def add_favorite(self, package_name: str) -> None:
        """Add an installed package to the persisted favorites list."""
        self._validate_package_name(package_name)
        if package_name not in self._adb_client.list_packages(include_system=True):
            raise AdbError(f"Application package is not installed: {package_name}")
        favorites = list(self._config.favorites)
        if package_name not in favorites:
            favorites.append(package_name)
        self._save_preferences(favorites)

    def remove_favorite(self, package_name: str) -> None:
        """Remove a package from the persisted favorites list."""
        self._validate_package_name(package_name)
        favorites = list(self._config.favorites)
        if package_name not in favorites:
            raise AdbError(f"Application is not a favorite: {package_name}")
        favorites.remove(package_name)
        self._save_preferences(favorites)

    def _save_preferences(self, favorites: list[str]) -> None:
        aliases = self._config.application_names or {}
        save_app_preferences(self._config_path, tuple(favorites), aliases)
        self._config = replace(self._config, favorites=tuple(favorites))

    @staticmethod
    def _validate_package_name(package_name: str) -> None:
        if not is_valid_package_name(package_name):
            raise ConfigError("Application package name is invalid")