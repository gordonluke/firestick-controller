from unittest.mock import Mock

import pytest

from firestick_controller.remote import RemoteAction, RemoteControl


@pytest.fixture
def adb_client():
    return Mock()


@pytest.fixture
def remote(adb_client):
    return RemoteControl(adb_client)


@pytest.mark.parametrize(
    ("action", "keycode"),
    [
        (RemoteAction.HOME, 3),
        (RemoteAction.BACK, 4),
        (RemoteAction.MENU, 82),
        (RemoteAction.UP, 19),
        (RemoteAction.DOWN, 20),
        (RemoteAction.LEFT, 21),
        (RemoteAction.RIGHT, 22),
        (RemoteAction.SELECT, 23),
        (RemoteAction.PLAY_PAUSE, 85),
        (RemoteAction.REWIND, 89),
        (RemoteAction.FAST_FORWARD, 90),
        (RemoteAction.VOLUME_UP, 24),
        (RemoteAction.VOLUME_DOWN, 25),
        (RemoteAction.MUTE, 164),
    ],
)
def test_press_sends_android_keycode(remote, adb_client, action, keycode):
    remote.press(action)

    adb_client.input_keyevent.assert_called_once_with(keycode)


@pytest.mark.parametrize("action", ["home", "PLAY-PAUSE", "volume up", "ok"])
def test_press_accepts_action_names(remote, adb_client, action):
    remote.press(action)

    adb_client.input_keyevent.assert_called_once()


def test_press_rejects_unsupported_action(remote):
    with pytest.raises(ValueError, match="Unsupported remote action"):
        remote.press("launch-app")


def test_press_rejects_non_action_type(remote):
    with pytest.raises(TypeError, match="RemoteAction"):
        remote.press(23)


def test_enter_text_delegates_to_adb_and_does_not_log_text(remote, adb_client, caplog):
    remote.enter_text("private search")

    adb_client.input_text.assert_called_once_with("private search")
    assert "private search" not in caplog.text