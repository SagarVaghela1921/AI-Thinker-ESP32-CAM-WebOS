# SPDX-License-Identifier: GPL-3.0-or-later
# BosW-V1.2 - Copyright (C) 2026 the BosW authors. See LICENSE.
"""BosW-V1.2 - a small web desktop for CircuitPython boards (ESP32-CAM tested).

code.py:    import boswv12
            boswv12.run()                      # desktop at http://<board-ip>:8082

Needs settings.toml:  CIRCUITPY_WIFI_SSID, CIRCUITPY_WIFI_PASSWORD and CIRCUITPY_WEB_API_PASSWORD
(the last one switches on CircuitPython's built-in file manager and terminal, which the desktop
shows in windows). Also needs adafruit_httpserver in /lib.
Modules: desktop (server, time), apps (app packages and run control), storage_mgr (SD/flash helper), ntp_time, watchdog_guard.
"""
import os, time, wifi

__version__ = "1.2"
NAME = "BosW-V1.2"

from boswv12 import storage_mgr as sm, ntp_time, desktop, apps, watchdog_guard as wd


def _connect(timeout=8):                       # keep this shorter than the watchdog
    wd.feed()
    ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    if not ssid:
        print("Wi-Fi: set CIRCUITPY_WIFI_SSID and CIRCUITPY_WIFI_PASSWORD in settings.toml")
        return False
    try:
        wifi.radio.connect(ssid, os.getenv("CIRCUITPY_WIFI_PASSWORD"), timeout=timeout)
    except Exception as e:
        print("Wi-Fi:", e)
        return False
    return wifi.radio.connected


def _servers(port):
    desktop.stop()
    ntp_time._pool = None                      # the old socket pool died with the connection
    try:
        return desktop.start(port) is not None
    except Exception as e:
        print("desktop start failed:", e)
        return False


def run(port=8082, watchdog_s=15):
    """Start everything and loop forever: SD card, Wi-Fi (reconnects), desktop, NTP, watchdog."""
    print(NAME, "starting")
    print("SD card:", "mounted" if sm.mount_sd() else "not available")
    if not sm.workflow_enabled():
        print("NOTE: add CIRCUITPY_WEB_API_PASSWORD to settings.toml for the Files and Terminal windows")
    if watchdog_s and wd.was_watchdog():
        print("NOTE: the last reset was caused by the watchdog (something froze)")
    online = _connect() and _servers(port)
    if watchdog_s:
        wd.start(watchdog_s)
    apps.boot()                                # apps marked startup
    now = last_chk = last_ntp = time.monotonic()
    try:
        while True:
            wd.feed()
            try:
                if online:
                    if ntp_time._st["fails"] < 3 or now - last_ntp >= 30:   # a dead NTP server cannot slow the loop
                        last_ntp = now
                        ntp_time.poll()
                    desktop.poll()
                apps.poll()                    # background and foreground apps
                sm.poll()                      # flushes buffered log files
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print("loop error: %s: %s" % (type(e).__name__, e))
                time.sleep(0.1)
            now = time.monotonic()
            if now - last_chk >= 10:           # Wi-Fi watchdog
                last_chk = now
                if not wifi.radio.connected:
                    online = _connect() and _servers(port)
                elif not online:
                    online = _servers(port)
    finally:
        apps.stop_all()
        wd.stop()
        sm.flush_all()
