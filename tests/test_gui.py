import os
import subprocess
import sys
import textwrap

import pytest


def test_gui_starts_and_validates_connection_fields_in_isolated_process(tmp_path):
    settings_path = tmp_path / "settings.json"
    script = textwrap.dedent(
        """
        import sys
        import json
        from pathlib import Path
        from PySide6.QtWidgets import QApplication
        from firestick_controller.automation import load_automation_sequences
        from firestick_controller.gui.app import FireStickWindow
        from firestick_controller.config import save_config

        application = QApplication([])
        window = FireStickWindow(sys.argv[1])
        assert window.windowTitle() == "FireStick Controller"
        assert window.port_input.text() == "5555"
        assert window.connection_status.text() == "Not connected"
        assert not window.disconnect_button.isEnabled()
        assert not window.refresh_apps_button.isEnabled()

        window.host_input.setText("192.168.1.25")
        window.port_input.setText("5566")
        window.pairing_port_input.setText("37000")
        config = window._connection_config()
        assert config.device.host == "192.168.1.25"
        assert config.device.port == 5566
        assert config.device.pairing_port == 37000

        window.host_input.clear()
        try:
            window._connection_config()
        except ValueError:
            pass
        else:
            raise AssertionError("Empty IP address should be rejected")

        settings_path = Path(sys.argv[1])
        save_config(settings_path, config)
        window._new_automation()
        window.automation_name_input.setText("Open Netflix")
        window._add_automation_step()
        window.automation_step_type.setCurrentIndex(1)
        window.automation_wait_spin.setValue(2)
        window._add_automation_step()
        window.automation_step_type.setCurrentIndex(2)
        window.automation_app_combo.addItem("Netflix", "com.netflix.ninja")
        window._add_automation_step()
        window.automation_step_type.setCurrentIndex(3)
        window.automation_text_input.setText("Iron Man")
        window._add_automation_step()
        sequence = window._save_current_automation()
        assert sequence is not None
        assert len(sequence.steps) == 4
        assert sequence.steps[3].value == "Iron Man"
        assert sequence.steps[2].force_stop_first is True

        window.automation_sequence_list.setCurrentRow(0)
        window.automation_steps_list.setCurrentRow(3)
        assert window.automation_text_input.text() == "Iron Man"
        window.automation_text_input.setText("Iron Man 2")
        window._replace_selected_step()
        window.automation_name_input.setText("Search Iron Man 2")
        updated_sequence = window._save_current_automation()

        assert updated_sequence is not None
        assert updated_sequence.name == "Search Iron Man 2"
        assert updated_sequence.steps[3].value == "Iron Man 2"
        assert updated_sequence.steps[2].force_stop_first is True
        assert load_automation_sequences(settings_path) == (updated_sequence,)
        assert len(json.loads(settings_path.read_text())["automations"]) == 1

        window.close()
        application.processEvents()
        print("gui-smoke-ok")
        """
    )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script, str(settings_path)],
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "gui-smoke-ok" in result.stdout
