"""Remote-control actions implemented with Android key events."""

from __future__ import annotations

import logging
from enum import IntEnum

from .adb_client import AdbClient

logger = logging.getLogger(__name__)


class RemoteAction(IntEnum):
    """Android keycodes used by common Fire TV remote actions."""

    HOME = 3
    BACK = 4
    MENU = 82
    UP = 19
    DOWN = 20
    LEFT = 21
    RIGHT = 22
    SELECT = 23
    OK = 23
    PLAY_PAUSE = 85
    REWIND = 89
    FAST_FORWARD = 90
    VOLUME_UP = 24
    VOLUME_DOWN = 25
    MUTE = 164


class RemoteControl:
    """Send navigation and playback commands to a connected Fire TV."""

    def __init__(self, adb_client: AdbClient) -> None:
        self._adb_client = adb_client

    def press(self, action: RemoteAction | str) -> None:
        """Send one supported remote action by enum or case-insensitive name."""
        if isinstance(action, str):
            action_name = action.strip().replace("-", "_").replace(" ", "_").upper()
            try:
                action = RemoteAction[action_name]
            except KeyError as exc:
                supported = ", ".join(item.name.lower() for item in RemoteAction)
                raise ValueError(f"Unsupported remote action '{action}'; choose from {supported}") from exc
        if not isinstance(action, RemoteAction):
            raise TypeError("action must be a RemoteAction or supported action name")

        self._adb_client.input_keyevent(int(action))
        logger.info("Sent remote action: %s", action.name.lower())

    def enter_text(self, text: str) -> None:
        """Type text into the currently focused Fire TV field."""
        self._adb_client.input_text(text)
        logger.info("Sent text input (%d characters)", len(text))