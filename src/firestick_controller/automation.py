"""Validated automation sequences, persistence, and sequential execution."""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .adb_client import is_supported_text_input
from .applications import ApplicationManager
from .config import ConfigError, is_valid_package_name, save_automation_data
from .remote import RemoteAction, RemoteControl

logger = logging.getLogger(__name__)
_MAX_AUTOMATION_STEPS = 40
_MAX_WAIT_SECONDS = 300.0


class AutomationError(ValueError):
    """Raised when an automation sequence is invalid or cannot be executed."""


@dataclass(frozen=True)
class AutomationStep:
    """A button press, text entry, delay, or app launch in a sequence."""

    kind: str
    value: str | float
    force_stop_first: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.force_stop_first, bool):
            raise AutomationError("force_stop_first must be a boolean")
        if self.kind != "launch" and self.force_stop_first:
            raise AutomationError("force_stop_first is only valid for launch steps")
        if self.kind == "press":
            if not isinstance(self.value, str):
                raise AutomationError("Press steps need a remote button name")
            action_name = self.value.strip().replace("-", "_").replace(" ", "_").upper()
            try:
                action = RemoteAction[action_name]
            except KeyError as exc:
                raise AutomationError(f"Unsupported remote button: {self.value}") from exc
            object.__setattr__(self, "value", action.name.lower().replace("_", "-"))
        elif self.kind == "wait":
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, (int, float))
                or not math.isfinite(self.value)
                or not 0 <= self.value <= _MAX_WAIT_SECONDS
            ):
                raise AutomationError(
                    f"Wait duration must be between 0 and {_MAX_WAIT_SECONDS:g} seconds"
                )
            object.__setattr__(self, "value", float(self.value))
        elif self.kind == "launch":
            if not is_valid_package_name(self.value):
                raise AutomationError("Launch steps need a valid app package name")
        elif self.kind == "text":
            if not is_supported_text_input(self.value):
                raise AutomationError(
                    "Text steps support letters, numbers, spaces, and . , _ @ / + : - only"
                )
        else:
            raise AutomationError(f"Unsupported automation step type: {self.kind}")

    @classmethod
    def from_dict(cls, data: object) -> AutomationStep:
        if not isinstance(data, dict):
            raise AutomationError("Each automation step must be a JSON object")
        kind = data.get("type")
        if kind == "press" and set(data) == {"type", "action"}:
            return cls(kind="press", value=data["action"])
        if kind == "wait" and set(data) == {"type", "seconds"}:
            return cls(kind="wait", value=data["seconds"])
        if kind == "launch" and set(data) in (
            {"type", "package_name"},
            {"type", "package_name", "force_stop_first"},
        ):
            return cls(
                kind="launch",
                value=data["package_name"],
                force_stop_first=data.get("force_stop_first", False),
            )
        if kind == "text" and set(data) == {"type", "text"}:
            return cls(kind="text", value=data["text"])
        raise AutomationError("Automation steps must be press, text, wait, or launch objects")

    def to_dict(self) -> dict[str, str | float | bool]:
        if self.kind == "press":
            return {"type": self.kind, "action": str(self.value)}
        if self.kind == "wait":
            return {"type": self.kind, "seconds": float(self.value)}
        if self.kind == "launch":
            return {
                "type": self.kind,
                "package_name": str(self.value),
                "force_stop_first": self.force_stop_first,
            }
        return {"type": self.kind, "text": str(self.value)}

    def description(self, application_names: dict[str, str] | None = None) -> str:
        if self.kind == "press":
            return f"Press {str(self.value).replace('-', ' ').title()}"
        if self.kind == "wait":
            return f"Wait {self.value:g} seconds"
        if self.kind == "launch":
            display_name = (application_names or {}).get(str(self.value), str(self.value))
            action = "Restart and launch" if self.force_stop_first else "Launch"
            return f"{action} {display_name}"
        return f"Enter text ({len(str(self.value))} characters)"


@dataclass(frozen=True)
class AutomationSequence:
    """A named sequence of automation steps."""

    name: str
    steps: tuple[AutomationStep, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name.strip()) > 64:
            raise AutomationError("Automation name must be between 1 and 64 characters")
        object.__setattr__(self, "name", self.name.strip())
        if len(self.steps) > _MAX_AUTOMATION_STEPS:
            raise AutomationError(f"Automations can contain at most {_MAX_AUTOMATION_STEPS} steps")
        if any(not isinstance(step, AutomationStep) for step in self.steps):
            raise AutomationError("Automation steps must be validated AutomationStep values")

    @classmethod
    def from_dict(cls, data: object) -> AutomationSequence:
        if not isinstance(data, dict) or set(data) != {"name", "steps"}:
            raise AutomationError("Each automation must have a name and steps")
        steps = data["steps"]
        if not isinstance(steps, list):
            raise AutomationError("Automation steps must be a list")
        return cls(
            name=data["name"],
            steps=tuple(AutomationStep.from_dict(step) for step in steps),
        )

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "steps": [step.to_dict() for step in self.steps]}


def load_automation_sequences(path: str | Path) -> tuple[AutomationSequence, ...]:
    """Load and validate automation definitions from the main JSON settings file."""
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        raise AutomationError(f"Cannot read automations from {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AutomationError("Settings must contain a JSON object")
    raw_sequences = data.get("automations", [])
    if not isinstance(raw_sequences, list):
        raise AutomationError("automations must be a list")
    sequences = tuple(AutomationSequence.from_dict(item) for item in raw_sequences)
    names = [sequence.name.casefold() for sequence in sequences]
    if len(set(names)) != len(names):
        raise AutomationError("Automation names must be unique")
    return sequences


def save_automation_sequences(
    path: str | Path,
    sequences: tuple[AutomationSequence, ...] | list[AutomationSequence],
) -> None:
    """Validate and persist automation definitions while preserving other settings."""
    names = [sequence.name.casefold() for sequence in sequences]
    if len(set(names)) != len(names):
        raise AutomationError("Automation names must be unique")
    save_automation_data(path, [sequence.to_dict() for sequence in sequences])


class AutomationRunner:
    """Execute sequence steps in order using the existing remote and app services."""

    def __init__(
        self,
        remote: RemoteControl,
        applications: ApplicationManager,
        delay: Callable[[float], None] = time.sleep,
    ) -> None:
        self._remote = remote
        self._applications = applications
        self._delay = delay

    def run(
        self,
        sequence: AutomationSequence,
        progress: Callable[[str], None] | None = None,
    ) -> str:
        if not sequence.steps:
            raise AutomationError(f"Automation '{sequence.name}' has no steps")
        logger.info("Starting automation '%s' with %d steps", sequence.name, len(sequence.steps))
        for index, step in enumerate(sequence.steps, start=1):
            message = f"Step {index}/{len(sequence.steps)}: {step.description()}"
            if progress is not None:
                progress(message)
            if step.kind == "press":
                self._remote.press(str(step.value))
            elif step.kind == "wait":
                self._delay(float(step.value))
            elif step.kind == "text":
                self._remote.enter_text(str(step.value))
            else:
                self._applications.launch(
                    str(step.value),
                    force_stop_first=step.force_stop_first,
                )
        logger.info("Completed automation '%s'", sequence.name)
        return f"Completed {sequence.name}"