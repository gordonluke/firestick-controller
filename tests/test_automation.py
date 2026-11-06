import json
from unittest.mock import Mock

import pytest

from firestick_controller.automation import (
    AutomationError,
    AutomationRunner,
    AutomationSequence,
    AutomationStep,
    load_automation_sequences,
    save_automation_sequences,
)


def test_run_sequence_executes_steps_in_order_and_reports_progress():
    events = []
    remote = Mock()
    remote.press.side_effect = lambda action: events.append(("press", action))
    remote.enter_text.side_effect = lambda text: events.append(("text", text))
    applications = Mock()
    applications.launch.side_effect = lambda package, **_: events.append(("launch", package))
    runner = AutomationRunner(
        remote,
        applications,
        delay=lambda seconds: events.append(("wait", seconds)),
    )
    sequence = AutomationSequence(
        "Open player",
        (
            AutomationStep("press", "home"),
            AutomationStep("wait", 2),
            AutomationStep("text", "Iron Man"),
            AutomationStep("launch", "com.netflix.ninja"),
        ),
    )
    progress = []

    result = runner.run(sequence, progress.append)

    assert result == "Completed Open player"
    assert events == [
        ("press", "home"),
        ("wait", 2.0),
        ("text", "Iron Man"),
        ("launch", "com.netflix.ninja"),
    ]
    assert progress == [
        "Step 1/4: Press Home",
        "Step 2/4: Wait 2 seconds",
        "Step 3/4: Enter text (8 characters)",
        "Step 4/4: Launch com.netflix.ninja",
    ]
    assert "Iron Man" not in " ".join(progress)
    applications.launch.assert_called_once_with(
        "com.netflix.ninja",
        force_stop_first=False,
    )


def test_run_empty_sequence_fails_with_useful_message():
    runner = AutomationRunner(Mock(), Mock())

    with pytest.raises(AutomationError, match="has no steps"):
        runner.run(AutomationSequence("Empty"))


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("press", "not-a-button"),
        ("press", 3),
        ("wait", -0.1),
        ("wait", 301),
        ("wait", float("nan")),
        ("wait", True),
        ("launch", "com.example;reboot"),
        ("text", "Iron Man;reboot"),
        ("text", ""),
        ("unknown", "value"),
    ],
)
def test_invalid_automation_step_is_rejected(kind, value):
    with pytest.raises(AutomationError):
        AutomationStep(kind, value)


def test_force_stop_option_is_only_valid_for_launch_steps():
    with pytest.raises(AutomationError, match="only valid for launch"):
        AutomationStep("press", "home", force_stop_first=True)


def test_sequence_round_trips_config_and_preserves_other_settings(tmp_path):
    config_path = tmp_path / "settings.json"
    config_path.write_text(
        json.dumps(
            {
                "device": {"host": "192.168.1.25"},
                "favorites": ["com.netflix.ninja"],
                "existing_setting": True,
            }
        ),
        encoding="utf-8",
    )
    sequences = (
        AutomationSequence(
            "Movie night",
            (
                AutomationStep("press", "home"),
                AutomationStep("text", "Iron Man"),
                AutomationStep("launch", "com.netflix.ninja", force_stop_first=True),
                AutomationStep("wait", 2.5),
            ),
        ),
    )

    save_automation_sequences(config_path, sequences)

    assert load_automation_sequences(config_path) == sequences
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["device"] == {"host": "192.168.1.25"}
    assert saved["favorites"] == ["com.netflix.ninja"]
    assert saved["existing_setting"] is True


def test_runner_forwards_force_stop_option_to_app_launch():
    applications = Mock()
    runner = AutomationRunner(Mock(), applications)
    sequence = AutomationSequence(
        "Fresh app",
        (AutomationStep("launch", "com.netflix.ninja", force_stop_first=True),),
    )

    runner.run(sequence)

    applications.launch.assert_called_once_with(
        "com.netflix.ninja",
        force_stop_first=True,
    )


def test_load_rejects_duplicate_sequence_names(tmp_path):
    config_path = tmp_path / "settings.json"
    config_path.write_text(
        json.dumps(
            {
                "automations": [
                    {"name": "Evening", "steps": []},
                    {"name": "evening", "steps": []},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AutomationError, match="unique"):
        load_automation_sequences(config_path)


def test_save_rejects_duplicate_sequence_names(tmp_path):
    config_path = tmp_path / "settings.json"
    config_path.write_text("{}", encoding="utf-8")
    sequences = (AutomationSequence("A"), AutomationSequence("a"))

    with pytest.raises(AutomationError, match="unique"):
        save_automation_sequences(config_path, sequences)