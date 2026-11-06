# FireStick Controller

A local-network Python application for controlling an Amazon Fire TV device through Android Debug Bridge (ADB). Milestones 1-4 provide configuration, ADB pairing and connection, device information, remote commands, application listing and launching, configurable favorites, a CLI, and a PySide6 desktop interface. Configurable automation sequences are the current milestone.

## Architecture

- `src/firestick_controller/config.py` loads and validates the device IP, connection ports, and timeout from JSON.
- `src/firestick_controller/adb_client.py` runs ADB with subprocess argument lists, enforces timeouts, and exposes connection operations.
- `src/firestick_controller/device.py` defines the device information returned by ADB.
- `src/firestick_controller/remote.py` maps named remote actions to Android key events and handles text entry.
- `src/firestick_controller/applications.py` lists installed apps, launches packages, and manages favorites.
- `src/firestick_controller/automation.py` validates, persists, and runs button, text, wait, and app-launch steps.
- `src/firestick_controller/main.py` provides connection, remote-control, and application commands.
- `src/firestick_controller/gui/app.py` provides the PySide6 desktop interface and runs ADB operations in background workers.
- `tests/` covers configuration, ADB, remote controls, applications, and headless GUI startup.

Core functionality uses Python's standard library. PySide6 powers the GUI; pytest is the development test dependency.

## Prerequisites

- Ubuntu Linux, Python 3.10 or later, and a Fire TV Stick on the same local network as the laptop.
- Android Platform Tools (`adb`).

Install the prerequisites and create a virtual environment:

```bash
sudo apt update
sudo apt install adb python3 python3-venv
cd ~/Documents/git/control_firestick
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Confirm ADB is installed:

```bash
adb version
```

## Prepare Fire TV

Menu labels vary by Fire TV model and Fire OS release. On the Fire TV, open **Settings > My Fire TV** (sometimes **Device & Software**) > **About** and select the device name repeatedly until Developer Options are enabled. Return to Developer Options and enable **ADB Debugging** or **Wireless Debugging**. Keep the laptop and Fire TV on the same trusted Wi-Fi network.

Find the Fire TV IP address under **Settings > My Fire TV > About > Network** (or the network settings screen). For traditional ADB debugging, the default connection port is commonly `5555`. For Wireless Debugging, open its pairing screen and note both the pairing port/code and the separate connection port shown on the main Wireless Debugging screen. Ports may change; use the values shown by the device.

## Configure and connect

Create your local settings file and edit the host address and ports:

```bash
cp config/settings.example.json config/settings.json
nano config/settings.json
```

Example:

```json
{
  "device": {
    "host": "192.168.0.12",
    "port": 5555,
    "pairing_port": null,
    "timeout_seconds": 5
  },
  "favorites": [],
  "application_names": {},
  "automations": []
}
```

The host must be a valid non-public IP address. `port` is the ADB connection port. Set `pairing_port` to the pairing port temporarily when using Wireless Debugging; pairing codes are entered interactively and are never saved in the settings file or logs.

For traditional ADB debugging, connect and inspect the device:

```bash
firestick-controller connect
firestick-controller status
```

For Wireless Debugging, set `pairing_port` to the current pairing port in `config/settings.json`, then pair and connect. Enter the short-lived code when prompted:

```bash
firestick-controller pair
firestick-controller connect
```

After successful pairing you can clear `pairing_port` or leave the value; pairing is separate from connecting. The connection `port` must be the connection port, not the pairing port. To disconnect:

```bash
firestick-controller disconnect
```

## Remote control

Connect first, then send one button at a time:

```bash
firestick-controller press home
firestick-controller press up
firestick-controller press select
firestick-controller press play-pause
firestick-controller press volume-up
```

Available buttons are `home`, `back`, `menu`, `up`, `down`, `left`, `right`, `select`/`ok`, `play-pause`, `rewind`, `fast-forward`, `volume-up`, `volume-down`, and `mute`. Volume commands send Android volume key events; they may not control the television's speakers because Fire TV remote volume can be routed through IR or HDMI-CEC, which ADB key events do not emulate.

To enter text, focus a text field on the Fire TV first, then run:

```bash
firestick-controller text "hello fire tv"
```

Text input supports ASCII letters, numbers, spaces, and `. , _ @ / + : -`; spaces are encoded using Android's `%s` convention. This sends keyboard events, not clipboard paste. If no text field is focused, the foreground app may interpret them as shortcuts; for example, a video player may pause when it receives a space. Other characters are rejected rather than sent through ADB's remote shell. Playback and navigation behavior can vary by Fire OS version and application.

The commands can also be run as `python -m firestick_controller.main ...`. Supply an alternate configuration with `--config /path/to/settings.json` before the action.

## Applications and favorites

List third-party packages installed on the connected Fire TV:

```bash
firestick-controller apps list
```

Use `firestick-controller apps list --all` to include system packages. Known apps show friendly names; unknown packages show their IDs unless you add an `application_names` entry in `config/settings.json`. Launch an app by its package ID:

```bash
firestick-controller apps launch com.netflix.ninja
```

Favorites persist in `config/settings.json` and can be managed from the CLI:

```bash
firestick-controller apps favorite-add com.netflix.ninja
firestick-controller apps favorites
firestick-controller apps favorite-remove com.netflix.ninja
```

Package IDs differ by app, region, and device. Use `apps list` on your Fire TV to find the exact ID.

## Desktop interface

Start the PySide6 interface from the project virtual environment:

```bash
firestick-controller-gui
```

The connection panel accepts the Fire TV IP, connection port, and Wireless Debugging pairing port. Pairing codes are entered into a password-style field and are not saved. After connecting, the interface shows device information, enables remote and text controls, and loads installed apps and favorites. Select an app and use **Launch selected** to open it. ADB operations run in background workers so network timeouts do not freeze the window.

Use an alternate settings file with:

```bash
firestick-controller-gui --config /path/to/settings.json
```

## Automations

Connect to the Fire TV, open the **Automations** tab, create a sequence, add steps, and save it. To edit an existing sequence, select it, change its name or steps, then save. Select a step to load its values into the editor; change them and choose **Replace selected** to update that step. Supported steps are remote button presses, text entry, waits from 0 to 300 seconds, and launching an installed app by package ID. Reorder steps before saving; run the selected sequence to execute each step in order. Progress appears in the status bar, and an error stops the remaining steps.

New app-launch steps have **Force-stop before launch** enabled by default. This stops the app process before reopening it, which can return it to its initial screen. It does not clear app data, sign you out, or erase viewing history, and an app may still restore state it saved persistently. Existing saved launch steps keep their previous behavior until you edit and enable this option.

For a Disney+ search, launch `com.disney.disneyplus`, add button-press steps to navigate to and focus its search field, add an **Enter text** step with `Iron Man`, then add button presses to choose the result. Text entry only types into the currently focused field; it does not open search or identify a result. The exact navigation and selection steps depend on the app's current screen and may need adjustment. Query text is saved in `config/settings.json` with the sequence, so do not use passwords or other secrets.

Text steps use the same supported characters as direct remote text entry: ASCII letters, numbers, spaces, and `. , _ @ / + : -`. Their progress message reports only the character count, not the query.

Sequences are stored in the `automations` array in `config/settings.json` and remain available after restarting the application. For example:

```json
{
  "automations": [
    {
      "name": "Movie night",
      "steps": [
        {"type": "press", "action": "home"},
        {"type": "wait", "seconds": 2},
        {"type": "launch", "package_name": "com.netflix.ninja"},
        {"type": "wait", "seconds": 5}
      ]
    }
  ]
}
```

## Run tests

```bash
source .venv/bin/activate
python -m pytest
```

The unit tests mock ADB subprocess responses and run GUI tests in offscreen mode; they do not require a physical Fire TV. The connection, package listing, and app-launch workflow should still be checked against the target device and Fire OS version.

## Troubleshooting

- **ADB not found:** run `adb version`; install with `sudo apt install adb` and check that `adb` is on `PATH`.
- **Connection refused or times out:** verify the IP, current connection port, same Wi-Fi network, and that ADB Debugging/Wireless Debugging is enabled. Some routers isolate wireless clients.
- **Pairing fails:** ensure the pairing port and code are current, use the pairing port rather than the connection port, and repeat pairing from the Fire TV Wireless Debugging screen.
- **Device appears offline or unauthorized:** check the Fire TV for an authorization prompt, accept it, then retry `firestick-controller status`.
- **Menus differ:** Fire OS menus vary by device generation and version; look under My Fire TV or Device & Software for Developer Options and debugging settings.

## Security

ADB grants powerful device access. Use it only on a trusted local network, never forward its ports from the internet, and turn off debugging when it is not needed. Configuration rejects globally routable IP addresses. Pairing codes are prompted without echo and are not logged. Automation query text is stored locally in plain text but is not logged. The application invokes ADB without a shell and applies a timeout to each command.

## Milestones

1. Project foundation: configuration, ADB detection and connection, tests, and setup instructions (complete).
2. Remote controls and remote-command tests (complete).
3. Application listing, launch, and configurable favorites (complete).
4. PySide6 graphical interface (complete).
5. Configurable automation sequences (complete).