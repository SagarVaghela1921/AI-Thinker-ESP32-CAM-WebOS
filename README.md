# BosW-V1.2

A small web desktop for CircuitPython boards (tested on the ESP32-CAM, CircuitPython 10.3.1): taskbar,
Start menu, clock and calendar with NTP time (12 or 24 hour), CircuitPython's built-in file manager and
terminal in windows, and an App manager that installs apps from `.zip` files.

## Install
1. Copy the `lib/boswv12` folder (with its `www` folder) to `/lib` on the board. Use `tools/build_mpy.sh`
   first if you want the compiled `.mpy` version.
2. Put `adafruit_httpserver` in `/lib`.
3. Copy `settings.toml.example` to the board as `settings.toml` and fill in your Wi-Fi and a web workflow password.
4. `code.py`:
   ```python
   import boswv12
   boswv12.run()
   ```
5. Open `http://<board-ip>:8082` on a phone or computer.

`boswv12.run(port=8082, watchdog_s=15)` also mounts the SD card, reconnects Wi-Fi, syncs the time, starts
apps marked `startup`, and resets the board if the loop freezes for `watchdog_s` seconds (0 = off).

## Apps
Install a `.zip` from *Start, App manager*. See `app_development.md` for the format. `examples/` has four
ready apps: `hello` (window), `ticker` (background, starts at boot), `boss` and `helper` (master and slave).

## Modules
`desktop` (web server, time), `apps` (app packages, run modes, roles), `storage_mgr` (SD and flash helper,
buffered logger), `ntp_time`, `watchdog_guard`.

## Security
There is no password on the desktop itself, and an app's `app.py` runs with full access to the board.
Use it on a network you trust and install only apps you trust.

## License
GNU General Public License v3.0 or later. See `LICENSE`.
