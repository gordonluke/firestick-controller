# FireStick Controller

A local-network Python application for controlling an Amazon Fire TV device through Android Debug Bridge (ADB). The project is being built in milestones. This first milestone provides configuration, ADB detection, pairing/connection, device status and identification, and a small CLI. Remote buttons, app launching, automation, and the graphical interface are not implemented yet.

## Architecture

- `src/firestick_controller/config.py` loads and validates the device IP, connection ports, and timeout from JSON.
- `src/firestick_controller/adb_client.py` runs ADB with subprocess argument lists, enforces timeouts, and exposes connection operations.
- `src/firestick_controller/device.py` defines the device information returned by ADB.
- `src/firestick_controller/main.py` offers basic `connect`, `pair`, `status`, and `disconnect` commands.
- `tests/` tests configuration and ADB behavior with mocked subprocess calls; no physical Fire TV is needed.

Runtime code uses only the Python standard library. Pytest is the only development dependency.

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
  }
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

The commands can also be run as `python -m firestick_controller.main ...`. Supply an alternate configuration with `--config /path/to/settings.json` before the action.

## Run tests

```bash
source .venv/bin/activate
python -m pytest
```

All tests mock ADB subprocess responses and do not require a Fire TV device.

## Troubleshooting

- **ADB not found:** run `adb version`; install with `sudo apt install adb` and check that `adb` is on `PATH`.
- **Connection refused or times out:** verify the IP, current connection port, same Wi-Fi network, and that ADB Debugging/Wireless Debugging is enabled. Some routers isolate wireless clients.
- **Pairing fails:** ensure the pairing port and code are current, use the pairing port rather than the connection port, and repeat pairing from the Fire TV Wireless Debugging screen.
- **Device appears offline or unauthorized:** check the Fire TV for an authorization prompt, accept it, then retry `firestick-controller status`.
- **Menus differ:** Fire OS menus vary by device generation and version; look under My Fire TV or Device & Software for Developer Options and debugging settings.

## Security

ADB grants powerful device access. Use it only on a trusted local network, never forward its ports from the internet, and turn off debugging when it is not needed. Configuration rejects globally routable IP addresses. Pairing codes are prompted without echo and are not logged. The application invokes ADB without a shell and applies a timeout to each command.

## Milestones

1. Project foundation: configuration, ADB detection and connection, tests, and setup instructions (current).
2. Remote controls and remote-command tests.
3. Application listing, launch, and configurable favourites.
4. PySide6 graphical interface.
5. Configurable automation sequences.