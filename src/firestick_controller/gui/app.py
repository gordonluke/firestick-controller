"""PySide6 desktop application for Fire TV control."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..adb_client import AdbClient, AdbError
from ..applications import Application, ApplicationManager
from ..automation import (
    AutomationError,
    AutomationRunner,
    AutomationSequence,
    AutomationStep,
    load_automation_sequences,
    save_automation_sequences,
)
from ..config import AppConfig, ConfigError, DeviceConfig, load_config, save_config
from ..device import DeviceInfo
from ..remote import RemoteAction, RemoteControl

logger = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    finished = Signal()


class _Worker(QRunnable):
    def __init__(
        self,
        operation: Callable[[], object],
        progress_operation: Callable[[Callable[[str], None]], object] | None = None,
    ) -> None:
        super().__init__()
        self.operation = operation
        self.progress_operation = progress_operation
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.progress_operation is None:
                result = self.operation()
            else:
                result = self.progress_operation(self.signals.progress.emit)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


class FireStickWindow(QMainWindow):
    def __init__(self, config_path: str | Path = "config/settings.json") -> None:
        super().__init__()
        self.config_path = Path(config_path)
        self.thread_pool = QThreadPool.globalInstance()
        self._workers: set[_Worker] = set()
        self._busy = False
        self._refresh_apps_after_task = False
        self._client: AdbClient | None = None
        self._application_manager: ApplicationManager | None = None
        self._app_config: AppConfig | None = None
        self._all_applications: list[Application] = []
        self._automation_sequences: list[AutomationSequence] = []
        self._automation_load_error: str | None = None
        self._settings_error: str | None = None

        try:
            self._app_config = load_config(self.config_path)
        except ConfigError as exc:
            if self.config_path.exists():
                self._settings_error = str(exc)
                logger.warning("Could not load settings: %s", exc)
        try:
            self._automation_sequences = list(load_automation_sequences(self.config_path))
        except AutomationError as exc:
            self._automation_load_error = str(exc)
            logger.warning("Could not load automation sequences: %s", exc)

        self.setWindowTitle("FireStick Controller")
        self.setMinimumSize(900, 680)
        self.resize(1080, 780)
        self._build_ui()
        self._populate_connection_fields()
        self._set_connection_state("Not connected", "idle")
        self._update_controls()
        if self._settings_error:
            self.statusBar().showMessage(self._settings_error)
        elif self._automation_load_error:
            self.statusBar().showMessage(self._automation_load_error)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        page = QVBoxLayout(root)
        page.setContentsMargins(22, 18, 22, 16)
        page.setSpacing(14)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("FireStick Controller")
        title.setObjectName("pageTitle")
        subtitle = QLabel("LOCAL ADB REMOTE")
        subtitle.setObjectName("subtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch(1)
        self.connection_status = QLabel("Not connected")
        self.connection_status.setObjectName("connectionStatus")
        header.addWidget(self.connection_status, alignment=Qt.AlignmentFlag.AlignTop)
        page.addLayout(header)

        page.addWidget(self._build_connection_panel())

        self.main_tabs = QTabWidget()
        controls_page = QWidget()
        content = QHBoxLayout(controls_page)
        content.setSpacing(14)
        content.addWidget(self._build_remote_panel(), 1)
        content.addWidget(self._build_applications_panel(), 1)
        self.main_tabs.addTab(controls_page, "Remote and apps")
        self.main_tabs.addTab(self._build_automation_panel(), "Automations")
        page.addWidget(self.main_tabs, 1)

        self.setCentralWidget(root)
        self._apply_styles()
        self.statusBar().showMessage("Enter your Fire TV address and connect")

    def _build_connection_panel(self) -> QGroupBox:
        panel = QGroupBox("Connection")
        grid = QGridLayout(panel)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("Fire TV IP address")
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("5555")
        self.port_input.setMaximumWidth(110)
        self.pairing_port_input = QLineEdit()
        self.pairing_port_input.setPlaceholderText("Wireless pairing port")
        self.pairing_port_input.setMaximumWidth(155)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("primary", True)
        self.disconnect_button = QPushButton("Disconnect")
        self.pair_code_input = QLineEdit()
        self.pair_code_input.setPlaceholderText("Pairing code")
        self.pair_code_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pair_code_input.setMaximumWidth(150)
        self.pair_button = QPushButton("Pair")

        grid.addWidget(QLabel("IP address"), 0, 0)
        grid.addWidget(self.host_input, 0, 1)
        grid.addWidget(QLabel("Connection port"), 0, 2)
        grid.addWidget(self.port_input, 0, 3)
        grid.addWidget(self.connect_button, 0, 4)
        grid.addWidget(self.disconnect_button, 0, 5)
        grid.addWidget(QLabel("Pairing port"), 1, 0)
        grid.addWidget(self.pairing_port_input, 1, 1)
        grid.addWidget(QLabel("Pairing code"), 1, 2)
        grid.addWidget(self.pair_code_input, 1, 3)
        grid.addWidget(self.pair_button, 1, 4)
        self.device_info_label = QLabel("Device information will appear after connecting")
        self.device_info_label.setObjectName("deviceInfo")
        grid.addWidget(self.device_info_label, 2, 0, 1, 6)

        self.connect_button.clicked.connect(self._connect_device)
        self.disconnect_button.clicked.connect(self._disconnect_device)
        self.pair_button.clicked.connect(self._pair_device)
        return panel

    def _build_remote_panel(self) -> QGroupBox:
        panel = QGroupBox("Remote")
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        navigation = QGridLayout()
        navigation.setSpacing(7)
        self._remote_buttons: list[QPushButton] = []
        for row, column, label, action in (
            (0, 0, "Home", RemoteAction.HOME),
            (0, 1, "Back", RemoteAction.BACK),
            (0, 2, "Menu", RemoteAction.MENU),
            (1, 1, "UP", RemoteAction.UP),
            (2, 0, "LEFT", RemoteAction.LEFT),
            (2, 1, "OK", RemoteAction.SELECT),
            (2, 2, "RIGHT", RemoteAction.RIGHT),
            (3, 1, "DOWN", RemoteAction.DOWN),
        ):
            button = QPushButton(label)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, remote_action=action: self._send_action(remote_action))
            navigation.addWidget(button, row, column)
            self._remote_buttons.append(button)
        layout.addLayout(navigation)

        playback = QHBoxLayout()
        for label, action in (
            ("Rewind", RemoteAction.REWIND),
            ("Play / Pause", RemoteAction.PLAY_PAUSE),
            ("Forward", RemoteAction.FAST_FORWARD),
        ):
            button = QPushButton(label)
            button.setMinimumHeight(40)
            button.clicked.connect(lambda checked=False, remote_action=action: self._send_action(remote_action))
            playback.addWidget(button)
            self._remote_buttons.append(button)
        layout.addLayout(playback)

        volume = QHBoxLayout()
        for label, action in (
            ("Volume -", RemoteAction.VOLUME_DOWN),
            ("Mute", RemoteAction.MUTE),
            ("Volume +", RemoteAction.VOLUME_UP),
        ):
            button = QPushButton(label)
            button.setMinimumHeight(40)
            button.clicked.connect(lambda checked=False, remote_action=action: self._send_action(remote_action))
            volume.addWidget(button)
            self._remote_buttons.append(button)
        layout.addLayout(volume)

        text_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Text for a focused Fire TV field")
        self.send_text_button = QPushButton("Send")
        self.send_text_button.clicked.connect(self._send_text)
        self.text_input.returnPressed.connect(self._send_text)
        text_row.addWidget(self.text_input, 1)
        text_row.addWidget(self.send_text_button)
        layout.addLayout(text_row)
        layout.addStretch(1)
        return panel

    def _build_applications_panel(self) -> QGroupBox:
        panel = QGroupBox("Applications")
        layout = QVBoxLayout(panel)
        toolbar = QHBoxLayout()
        self.app_search = QLineEdit()
        self.app_search.setPlaceholderText("Filter applications")
        self.refresh_apps_button = QPushButton("Refresh")
        toolbar.addWidget(self.app_search, 1)
        toolbar.addWidget(self.refresh_apps_button)
        layout.addLayout(toolbar)

        self.include_system_checkbox = QCheckBox("Include system packages")
        layout.addWidget(self.include_system_checkbox)
        self.app_tabs = QTabWidget()
        self.installed_apps_list = QListWidget()
        self.favorite_apps_list = QListWidget()
        self.app_tabs.addTab(self.installed_apps_list, "Installed")
        self.app_tabs.addTab(self.favorite_apps_list, "Favorites")
        layout.addWidget(self.app_tabs, 1)

        actions = QHBoxLayout()
        self.launch_app_button = QPushButton("Launch selected")
        self.launch_app_button.setProperty("primary", True)
        self.add_favorite_button = QPushButton("Add favorite")
        self.remove_favorite_button = QPushButton("Remove favorite")
        actions.addWidget(self.launch_app_button)
        actions.addWidget(self.add_favorite_button)
        actions.addWidget(self.remove_favorite_button)
        layout.addLayout(actions)

        self.refresh_apps_button.clicked.connect(self._refresh_applications)
        self.include_system_checkbox.toggled.connect(self._refresh_applications)
        self.app_search.textChanged.connect(self._filter_applications)
        self.launch_app_button.clicked.connect(self._launch_selected)
        self.add_favorite_button.clicked.connect(self._add_selected_favorite)
        self.remove_favorite_button.clicked.connect(self._remove_selected_favorite)
        self.installed_apps_list.itemDoubleClicked.connect(lambda item: self._launch_item(item))
        self.favorite_apps_list.itemDoubleClicked.connect(lambda item: self._launch_item(item))
        self.installed_apps_list.currentItemChanged.connect(self._update_controls)
        self.favorite_apps_list.currentItemChanged.connect(self._update_controls)
        self.app_tabs.currentChanged.connect(self._update_controls)
        return panel

    def _build_automation_panel(self) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        sequences_group = QGroupBox("Sequences")
        sequences_layout = QVBoxLayout(sequences_group)
        self.automation_sequence_list = QListWidget()
        self.new_automation_button = QPushButton("New sequence")
        self.delete_automation_button = QPushButton("Delete sequence")
        sequences_layout.addWidget(self.automation_sequence_list, 1)
        sequences_layout.addWidget(self.new_automation_button)
        sequences_layout.addWidget(self.delete_automation_button)
        layout.addWidget(sequences_group, 1)

        editor_group = QGroupBox("Sequence editor")
        editor_layout = QVBoxLayout(editor_group)
        self.automation_name_input = QLineEdit()
        self.automation_name_input.setPlaceholderText("Sequence name")
        editor_layout.addWidget(self.automation_name_input)
        self.automation_steps_list = QListWidget()
        editor_layout.addWidget(self.automation_steps_list, 1)

        step_row = QHBoxLayout()
        self.automation_step_type = QComboBox()
        self.automation_step_type.addItem("Button press", "press")
        self.automation_step_type.addItem("Wait", "wait")
        self.automation_step_type.addItem("Launch app", "launch")
        self.automation_step_type.addItem("Enter text", "text")
        self.automation_action_combo = QComboBox()
        for action in RemoteAction:
            self.automation_action_combo.addItem(
                action.name.replace("_", " ").title(),
                action.name.lower().replace("_", "-"),
            )
        self.automation_wait_spin = QDoubleSpinBox()
        self.automation_wait_spin.setRange(0, 300)
        self.automation_wait_spin.setDecimals(1)
        self.automation_wait_spin.setSuffix(" sec")
        self.automation_wait_spin.setValue(2)
        self.automation_app_combo = QComboBox()
        self.automation_text_input = QLineEdit()
        self.automation_text_input.setPlaceholderText("Text for the focused field")
        self.automation_force_stop_checkbox = QCheckBox("Force-stop before launch")
        self.automation_force_stop_checkbox.setChecked(True)
        self.automation_add_step_button = QPushButton("Add step")
        self.automation_replace_step_button = QPushButton("Replace selected")
        step_row.addWidget(self.automation_step_type)
        step_row.addWidget(self.automation_action_combo, 1)
        step_row.addWidget(self.automation_wait_spin)
        step_row.addWidget(self.automation_app_combo, 2)
        step_row.addWidget(self.automation_text_input, 2)
        step_row.addWidget(self.automation_add_step_button)
        step_row.addWidget(self.automation_replace_step_button)
        editor_layout.addLayout(step_row)
        editor_layout.addWidget(self.automation_force_stop_checkbox)

        step_actions = QHBoxLayout()
        self.automation_move_up_button = QPushButton("Move up")
        self.automation_move_down_button = QPushButton("Move down")
        self.automation_remove_step_button = QPushButton("Remove step")
        step_actions.addWidget(self.automation_move_up_button)
        step_actions.addWidget(self.automation_move_down_button)
        step_actions.addWidget(self.automation_remove_step_button)
        step_actions.addStretch(1)
        self.save_automation_button = QPushButton("Save sequence")
        self.save_automation_button.setProperty("primary", True)
        self.run_automation_button = QPushButton("Run sequence")
        self.run_automation_button.setProperty("primary", True)
        step_actions.addWidget(self.save_automation_button)
        step_actions.addWidget(self.run_automation_button)
        editor_layout.addLayout(step_actions)
        layout.addWidget(editor_group, 2)

        self._draft_automation_steps: list[AutomationStep] = []
        self._selected_automation_name: str | None = None
        self.automation_sequence_list.currentRowChanged.connect(self._select_automation)
        self.automation_steps_list.currentRowChanged.connect(self._select_automation_step)
        self.new_automation_button.clicked.connect(self._new_automation)
        self.delete_automation_button.clicked.connect(self._delete_automation)
        self.automation_step_type.currentIndexChanged.connect(self._update_step_editor)
        self.automation_add_step_button.clicked.connect(self._add_automation_step)
        self.automation_replace_step_button.clicked.connect(self._replace_selected_step)
        self.automation_remove_step_button.clicked.connect(self._remove_automation_step)
        self.automation_move_up_button.clicked.connect(lambda: self._move_automation_step(-1))
        self.automation_move_down_button.clicked.connect(lambda: self._move_automation_step(1))
        self.save_automation_button.clicked.connect(self._save_current_automation)
        self.run_automation_button.clicked.connect(self._run_current_automation)
        self._populate_automation_sequence_list()
        self._update_step_editor()
        return panel

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget#root { background: #eef2ef; color: #1b2a2a; }
            QLabel#pageTitle { color: #153c3d; font-size: 23px; font-weight: 700; }
            QLabel#subtitle { color: #657978; font-size: 10px; font-weight: 700; }
            QLabel#deviceInfo { color: #536665; padding-top: 4px; }
            QLabel#connectionStatus { border-radius: 6px; padding: 7px 11px; font-weight: 700; }
            QGroupBox {
                background: #ffffff; border: 1px solid #d4dfd9; border-radius: 6px;
                margin-top: 10px; padding: 12px; font-weight: 700; color: #234447;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLineEdit, QListWidget, QTabWidget::pane {
                background: #fbfcfb; border: 1px solid #cbd8d2; border-radius: 5px;
                padding: 7px; selection-background-color: #cce9e3;
            }
            QPushButton {
                background: #e7eeea; border: 1px solid #cbd8d2; border-radius: 5px;
                color: #213b3c; padding: 8px 10px; min-height: 20px; font-weight: 600;
            }
            QPushButton:hover { background: #dbe9e3; }
            QPushButton:disabled { color: #98a7a2; background: #edf1ef; }
            QPushButton[primary="true"] { background: #087f78; border-color: #087f78; color: #ffffff; }
            QPushButton[primary="true"]:hover { background: #066a64; }
            QTabBar::tab { background: #e7eeea; padding: 8px 14px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: #cce9e3; color: #153c3d; }
            QStatusBar { background: #e5ece8; color: #526461; }
            """
        )

    def _populate_connection_fields(self) -> None:
        if self._app_config is None:
            self.port_input.setText("5555")
            return
        device = self._app_config.device
        self.host_input.setText(device.host)
        self.port_input.setText(str(device.port))
        if device.pairing_port is not None:
            self.pairing_port_input.setText(str(device.pairing_port))

    def _connection_config(self) -> AppConfig:
        if self._settings_error:
            raise ConfigError(
                f"Fix the existing settings file before connecting: {self._settings_error}"
            )
        try:
            port = int(self.port_input.text().strip())
            pairing_port_text = self.pairing_port_input.text().strip()
            pairing_port = int(pairing_port_text) if pairing_port_text else None
        except ValueError as exc:
            raise ConfigError("Connection and pairing ports must be integers") from exc

        existing = self._app_config
        return AppConfig(
            device=DeviceConfig(
                host=self.host_input.text().strip(),
                port=port,
                pairing_port=pairing_port,
                timeout_seconds=existing.device.timeout_seconds if existing else 5.0,
            ),
            favorites=existing.favorites if existing else (),
            application_names=existing.application_names if existing else {},
        )

    def _connect_device(self) -> None:
        try:
            config = self._connection_config()
            save_config(self.config_path, config)
        except (ConfigError, OSError) as exc:
            self._show_error(str(exc))
            return

        self._set_connection_state("Connecting", "busy")

        def operation() -> tuple[AdbClient, str, DeviceInfo]:
            client = AdbClient(config.device)
            response = client.connect()
            info = client.device_info()
            return client, response, info

        self._run_task(operation, self._connected)

    def _connected(self, result: tuple[AdbClient, str, DeviceInfo]) -> None:
        self._client, response, info = result
        self._app_config = AppConfig(
            device=self._client.config,
            favorites=self._app_config.favorites if self._app_config else (),
            application_names=self._app_config.application_names if self._app_config else {},
        )
        self._application_manager = ApplicationManager(
            self._client, self._app_config, self.config_path
        )
        self.device_info_label.setText(f"{info.model}  |  Serial: {info.serial}")
        self._set_connection_state("Connected", "connected")
        self.statusBar().showMessage(response or "Connected to Fire TV", 5000)
        self._refresh_apps_after_task = True

    def _disconnect_device(self) -> None:
        client = self._client
        if client is None:
            return
        self._run_task(client.disconnect, self._disconnected)

    def _disconnected(self, response: str) -> None:
        self._client = None
        self._application_manager = None
        self._application_cache = []
        self._populate_app_lists([], [])
        self.device_info_label.setText("Device information will appear after connecting")
        self._set_connection_state("Not connected", "idle")
        self.statusBar().showMessage(response or "Disconnected", 5000)

    def _pair_device(self) -> None:
        try:
            config = self._connection_config()
            if config.device.pairing_port is None:
                raise ConfigError("Enter the Wireless Debugging pairing port first")
            pairing_code = self.pair_code_input.text()
            if len(pairing_code) != 6 or not pairing_code.isdigit():
                raise ConfigError("Enter the six-digit Wireless Debugging pairing code")
            save_config(self.config_path, config)
        except (ConfigError, OSError) as exc:
            self._show_error(str(exc))
            return

        self.pair_code_input.clear()
        client = AdbClient(config.device)
        self._set_connection_state("Pairing", "busy")
        self._run_task(lambda: client.pair(pairing_code), self._paired)

    def _paired(self, response: str) -> None:
        self.pair_code_input.clear()
        self._set_connection_state("Paired", "idle")
        self.statusBar().showMessage(response or "Wireless debugging paired", 6000)

    def _refresh_applications(self) -> None:
        manager = self._application_manager
        if manager is None or self._busy:
            return

        include_system = self.include_system_checkbox.isChecked()

        def operation() -> tuple[list[Application], list[Application]]:
            visible_apps = manager.list_applications(include_system=include_system)
            all_apps = manager.list_applications(include_system=True)
            return visible_apps, all_apps

        self._run_task(operation, self._applications_loaded)

    def _applications_loaded(self, result: tuple[list[Application], list[Application]]) -> None:
        visible_apps, self._all_applications = result
        self._populate_app_lists(visible_apps, self._all_applications)
        self._populate_automation_app_choices()
        self.statusBar().showMessage(f"Loaded {len(visible_apps)} applications", 4000)

    def _populate_app_lists(
        self,
        visible_apps: list[Application],
        all_apps: list[Application],
    ) -> None:
        self.installed_apps_list.clear()
        self.favorite_apps_list.clear()
        for application in visible_apps:
            item = self._application_item(application)
            self.installed_apps_list.addItem(item)
        favorite_packages = set(self._application_manager.favorites) if self._application_manager else set()
        all_by_package = {application.package_name: application for application in all_apps}
        for package_name in sorted(favorite_packages):
            application = all_by_package.get(package_name)
            if application is None:
                application = Application(package_name, package_name, True)
            self.favorite_apps_list.addItem(self._application_item(application))
        self._filter_applications()
        self._update_controls()

    def _populate_automation_app_choices(self) -> None:
        self.automation_app_combo.clear()
        for application in self._all_applications:
            self.automation_app_combo.addItem(
                f"{application.display_name}  ({application.package_name})",
                application.package_name,
            )

    def _populate_automation_sequence_list(self, selected_name: str | None = None) -> None:
        self.automation_sequence_list.blockSignals(True)
        self.automation_sequence_list.clear()
        selected_row = -1
        for row, sequence in enumerate(self._automation_sequences):
            item = QListWidgetItem(sequence.name)
            item.setData(Qt.ItemDataRole.UserRole, sequence.name)
            self.automation_sequence_list.addItem(item)
            if sequence.name == selected_name:
                selected_row = row
        if selected_row < 0 and self._automation_sequences:
            selected_row = 0
        self.automation_sequence_list.setCurrentRow(selected_row)
        self.automation_sequence_list.blockSignals(False)
        self._select_automation(selected_row)

    def _select_automation(self, row: int) -> None:
        if row < 0 or row >= len(self._automation_sequences):
            self._selected_automation_name = None
            self._draft_automation_steps = []
            self.automation_name_input.clear()
            self.automation_steps_list.clear()
        else:
            sequence = self._automation_sequences[row]
            self._selected_automation_name = sequence.name
            self._draft_automation_steps = list(sequence.steps)
            self.automation_name_input.setText(sequence.name)
            self._render_automation_steps()
        self._update_controls()

    def _render_automation_steps(self) -> None:
        self.automation_steps_list.clear()
        names = self._app_config.application_names if self._app_config else {}
        for step in self._draft_automation_steps:
            self.automation_steps_list.addItem(step.description(names))

    def _new_automation(self) -> None:
        base_name = "New automation"
        existing_names = {sequence.name.casefold() for sequence in self._automation_sequences}
        name = base_name
        suffix = 2
        while name.casefold() in existing_names:
            name = f"{base_name} {suffix}"
            suffix += 1
        self._automation_sequences.append(AutomationSequence(name))
        self._populate_automation_sequence_list(name)

    def _delete_automation(self) -> None:
        if self._selected_automation_name is None:
            return
        self._automation_sequences = [
            sequence
            for sequence in self._automation_sequences
            if sequence.name != self._selected_automation_name
        ]
        self._persist_automation_sequences()
        self._populate_automation_sequence_list()

    def _save_current_automation(self, *_args: object) -> AutomationSequence | None:
        if self._selected_automation_name is None:
            return None
        try:
            sequence = AutomationSequence(
                self.automation_name_input.text(),
                tuple(self._draft_automation_steps),
            )
            remaining = [
                current
                for current in self._automation_sequences
                if current.name != self._selected_automation_name
            ]
            if any(current.name.casefold() == sequence.name.casefold() for current in remaining):
                raise AutomationError("Automation names must be unique")
            self._automation_sequences = [*remaining, sequence]
            self._automation_sequences.sort(key=lambda current: current.name.casefold())
            if not self._persist_automation_sequences():
                return None
        except AutomationError as exc:
            self._show_error(str(exc))
            return None

        self._selected_automation_name = sequence.name
        self._populate_automation_sequence_list(sequence.name)
        self.statusBar().showMessage(f"Saved automation: {sequence.name}", 5000)
        return sequence

    def _persist_automation_sequences(self) -> bool:
        try:
            save_automation_sequences(self.config_path, self._automation_sequences)
        except (AutomationError, ConfigError) as exc:
            self._show_error(str(exc))
            return False
        return True

    def _update_step_editor(self, *_args: object) -> None:
        kind = self.automation_step_type.currentData()
        self.automation_action_combo.setVisible(kind == "press")
        self.automation_wait_spin.setVisible(kind == "wait")
        self.automation_app_combo.setVisible(kind == "launch")
        self.automation_text_input.setVisible(kind == "text")
        self.automation_force_stop_checkbox.setVisible(kind == "launch")
        self._update_controls()

    def _select_automation_step(self, row: int) -> None:
        if row < 0 or row >= len(self._draft_automation_steps):
            self._update_controls()
            return
        step = self._draft_automation_steps[row]
        kind_index = self.automation_step_type.findData(step.kind)
        if kind_index >= 0:
            self.automation_step_type.setCurrentIndex(kind_index)
        if step.kind == "press":
            action_index = self.automation_action_combo.findData(step.value)
            if action_index >= 0:
                self.automation_action_combo.setCurrentIndex(action_index)
        elif step.kind == "wait":
            self.automation_wait_spin.setValue(float(step.value))
        elif step.kind == "launch":
            app_index = self.automation_app_combo.findData(step.value)
            if app_index >= 0:
                self.automation_app_combo.setCurrentIndex(app_index)
            self.automation_force_stop_checkbox.setChecked(step.force_stop_first)
        else:
            self.automation_text_input.setText(str(step.value))
        self._update_controls()

    def _build_automation_step(self) -> AutomationStep:
        kind = self.automation_step_type.currentData()
        if kind == "press":
            value = self.automation_action_combo.currentData()
        elif kind == "wait":
            value = self.automation_wait_spin.value()
        elif kind == "launch":
            value = self.automation_app_combo.currentData()
        else:
            value = self.automation_text_input.text()
        return AutomationStep(
            kind,
            value,
            force_stop_first=(
                self.automation_force_stop_checkbox.isChecked() if kind == "launch" else False
            ),
        )

    def _add_automation_step(self) -> None:
        try:
            step = self._build_automation_step()
        except AutomationError as exc:
            self._show_error(str(exc))
            return
        self._draft_automation_steps.append(step)
        self._render_automation_steps()
        self.automation_steps_list.setCurrentRow(len(self._draft_automation_steps) - 1)

    def _replace_selected_step(self) -> None:
        row = self.automation_steps_list.currentRow()
        if row < 0 or row >= len(self._draft_automation_steps):
            self._show_error("Select a step to replace")
            return
        try:
            step = self._build_automation_step()
        except AutomationError as exc:
            self._show_error(str(exc))
            return
        self._draft_automation_steps[row] = step
        self._render_automation_steps()
        self.automation_steps_list.setCurrentRow(row)
        self.statusBar().showMessage("Updated step; save the sequence to keep the change", 5000)

    def _remove_automation_step(self) -> None:
        row = self.automation_steps_list.currentRow()
        if 0 <= row < len(self._draft_automation_steps):
            self._draft_automation_steps.pop(row)
            self._render_automation_steps()
            self.automation_steps_list.setCurrentRow(
                min(row, len(self._draft_automation_steps) - 1)
            )

    def _move_automation_step(self, offset: int) -> None:
        row = self.automation_steps_list.currentRow()
        target = row + offset
        if 0 <= row < len(self._draft_automation_steps) and 0 <= target < len(self._draft_automation_steps):
            self._draft_automation_steps[row], self._draft_automation_steps[target] = (
                self._draft_automation_steps[target],
                self._draft_automation_steps[row],
            )
            self._render_automation_steps()
            self.automation_steps_list.setCurrentRow(target)

    def _run_current_automation(self) -> None:
        sequence = self._save_current_automation()
        if sequence is None:
            return
        if self._client is None or self._application_manager is None:
            self._show_error("Connect to the Fire TV before running an automation")
            return
        runner = AutomationRunner(RemoteControl(self._client), self._application_manager)
        self._run_task(
            lambda: None,
            self._automation_completed,
            on_progress=self._automation_progress,
            progress_operation=lambda report: runner.run(sequence, report),
        )

    def _automation_progress(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _automation_completed(self, message: object) -> None:
        self.statusBar().showMessage(str(message), 10000)

    @staticmethod
    def _application_item(application: Application) -> QListWidgetItem:
        prefix = "* " if application.is_favorite else ""
        item = QListWidgetItem(f"{prefix}{application.display_name}  ({application.package_name})")
        item.setData(Qt.ItemDataRole.UserRole, application.package_name)
        return item

    def _filter_applications(self) -> None:
        query = self.app_search.text().casefold()
        for index in range(self.installed_apps_list.count()):
            item = self.installed_apps_list.item(index)
            item.setHidden(query not in item.text().casefold())

    def _launch_selected(self) -> None:
        item = self._selected_application_item()
        if item is not None:
            self._launch_item(item)

    def _launch_item(self, item: QListWidgetItem) -> None:
        manager = self._application_manager
        if manager is None:
            return
        package_name = item.data(Qt.ItemDataRole.UserRole)
        self._run_task(lambda: manager.launch(package_name), lambda _: self.statusBar().showMessage(
            f"Launched {package_name}", 5000
        ))

    def _add_selected_favorite(self) -> None:
        manager = self._application_manager
        item = self._selected_application_item()
        if manager is None or item is None:
            return
        package_name = item.data(Qt.ItemDataRole.UserRole)

        def operation() -> tuple[list[Application], list[Application]]:
            manager.add_favorite(package_name)
            return manager.list_applications(), manager.list_applications(include_system=True)

        self._run_task(operation, self._applications_loaded)

    def _remove_selected_favorite(self) -> None:
        manager = self._application_manager
        item = self._selected_application_item()
        if manager is None or item is None:
            return
        package_name = item.data(Qt.ItemDataRole.UserRole)

        def operation() -> tuple[list[Application], list[Application]]:
            manager.remove_favorite(package_name)
            return manager.list_applications(), manager.list_applications(include_system=True)

        self._run_task(operation, self._applications_loaded)

    def _selected_application_item(self) -> QListWidgetItem | None:
        if self.app_tabs.currentIndex() == 0:
            return self.installed_apps_list.currentItem()
        return self.favorite_apps_list.currentItem()

    def _send_action(self, action: RemoteAction) -> None:
        if self._client is None:
            return
        client = self._client
        self._run_task(lambda: RemoteControl(client).press(action), lambda _: None)

    def _send_text(self) -> None:
        if self._client is None or not self.text_input.text():
            return
        client = self._client
        text = self.text_input.text()
        self._run_task(lambda: RemoteControl(client).enter_text(text), self.text_input.clear)

    def _run_task(
        self,
        operation: Callable[[], object],
        on_success: Callable[[object], None],
        on_progress: Callable[[str], None] | None = None,
        progress_operation: Callable[[Callable[[str], None]], object] | None = None,
    ) -> None:
        if self._busy:
            return
        self._busy = True
        self.statusBar().showMessage("Working...")
        self._update_controls()
        worker = _Worker(operation, progress_operation)
        self._workers.add(worker)
        worker.signals.succeeded.connect(on_success)
        worker.signals.failed.connect(self._operation_failed)
        if on_progress is not None:
            worker.signals.progress.connect(on_progress)
        worker.signals.finished.connect(lambda current=worker: self._operation_finished(current))
        self.thread_pool.start(worker)

    def _operation_failed(self, message: str) -> None:
        logger.error("GUI operation failed: %s", message)
        self.statusBar().showMessage(message, 10000)
        if self._client is None:
            self._set_connection_state("Connection failed", "error")
        else:
            self._set_connection_state("Connected", "connected")

    def _operation_finished(self, worker: _Worker) -> None:
        self._workers.discard(worker)
        self._busy = False
        self._update_controls()
        if self._refresh_apps_after_task:
            self._refresh_apps_after_task = False
            self._refresh_applications()

    def _show_error(self, message: str) -> None:
        logger.error("GUI action failed: %s", message)
        self.statusBar().showMessage(message, 10000)

    def _set_connection_state(self, message: str, state: str) -> None:
        colors = {
            "idle": ("#e7eeea", "#405653"),
            "busy": ("#fff0d6", "#795516"),
            "connected": ("#d9f0e5", "#176545"),
            "error": ("#fce4e1", "#9b3327"),
        }
        background, foreground = colors[state]
        self.connection_status.setText(message)
        self.connection_status.setStyleSheet(
            f"background: {background}; color: {foreground}; border-radius: 6px; padding: 7px 11px; font-weight: 700;"
        )

    def _update_controls(self, *_args: object) -> None:
        connected = self._client is not None
        self.connect_button.setEnabled(not self._busy and not connected)
        self.disconnect_button.setEnabled(not self._busy and connected)
        self.pair_button.setEnabled(not self._busy)
        for button in self._remote_buttons:
            button.setEnabled(not self._busy and connected)
        self.send_text_button.setEnabled(not self._busy and connected)
        self.text_input.setEnabled(not self._busy and connected)
        self.refresh_apps_button.setEnabled(not self._busy and connected)
        self.include_system_checkbox.setEnabled(not self._busy and connected)
        has_selection = connected and self._selected_application_item() is not None
        self.launch_app_button.setEnabled(not self._busy and has_selection)
        self.add_favorite_button.setEnabled(not self._busy and has_selection)
        self.remove_favorite_button.setEnabled(
            not self._busy
            and has_selection
            and self.app_tabs.currentIndex() == 1
        )
        has_automation = self._selected_automation_name is not None
        has_selected_step = self.automation_steps_list.currentRow() >= 0
        self.new_automation_button.setEnabled(not self._busy)
        self.delete_automation_button.setEnabled(not self._busy and has_automation)
        self.automation_name_input.setEnabled(not self._busy and has_automation)
        self.automation_sequence_list.setEnabled(not self._busy)
        self.automation_steps_list.setEnabled(not self._busy and has_automation)
        self.automation_step_type.setEnabled(not self._busy and has_automation)
        self.automation_action_combo.setEnabled(not self._busy and has_automation)
        self.automation_wait_spin.setEnabled(not self._busy and has_automation)
        self.automation_text_input.setEnabled(not self._busy and has_automation)
        self.automation_app_combo.setEnabled(
            not self._busy and has_automation and self.automation_app_combo.count() > 0
        )
        self.automation_force_stop_checkbox.setEnabled(not self._busy and has_automation)
        self.automation_add_step_button.setEnabled(not self._busy and has_automation)
        self.automation_replace_step_button.setEnabled(
            not self._busy and has_automation and has_selected_step
        )
        self.automation_remove_step_button.setEnabled(
            not self._busy and has_automation and has_selected_step
        )
        self.automation_move_up_button.setEnabled(
            not self._busy and has_selected_step and self.automation_steps_list.currentRow() > 0
        )
        self.automation_move_down_button.setEnabled(
            not self._busy
            and has_selected_step
            and self.automation_steps_list.currentRow() < len(self._draft_automation_steps) - 1
        )
        self.save_automation_button.setEnabled(not self._busy and has_automation)
        self.run_automation_button.setEnabled(
            not self._busy and connected and has_automation and bool(self._draft_automation_steps)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FireStick Controller desktop interface")
    parser.add_argument("--config", default="config/settings.json", help="JSON settings file")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    application = QApplication(sys.argv[:1])
    application.setApplicationName("FireStick Controller")
    application.setFont(QFont("Noto Sans", 10))
    window = FireStickWindow(arguments.config)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())