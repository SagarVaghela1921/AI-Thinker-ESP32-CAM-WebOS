# SPDX-License-Identifier: GPL-3.0-or-later
# BosW-V1.2 - Copyright (C) 2026 the BosW authors. See LICENSE.
"""watchdog_guard.py - hardware watchdog for the board (not code.py). Same style as the other modules.

Other programs:   import watchdog_guard as wd
                  wd.start(15)            # board resets itself if feed() is not called for 15 s
                  while True:
                      wd.feed()           # call at least once every loop
                      ...
                  wd.stop()               # before a normal exit (a no-op if it was never started)
Serial terminal:  import watchdog_guard as wd; wd.test()          # starts, feeds, stops
                  wd.trip_test()                                   # DELIBERATELY hangs to prove the reset
Why: the web server, link polling and recorder share one loop. A frozen loop (for example
"while True" typed into the desktop terminal) stops everything, and only a reset recovers it.
Keep anything that can block (Wi-Fi connect, SD formatting) shorter than the timeout, or call feed() first.
After a reset, was_watchdog() tells you whether the watchdog caused it.
"""
import time
import microcontroller

_w = None
_timeout = 0


def start(timeout=15):
    """Returns True if the watchdog is running."""
    global _w, _timeout
    try:
        from watchdog import WatchDogMode
        w = microcontroller.watchdog
        w.timeout = timeout
        w.mode = WatchDogMode.RESET
        w.feed()
        _w, _timeout = w, timeout
        return True
    except Exception as e:
        print("watchdog not started:", e)
        _w = None
        return False


def feed():
    if _w is not None:
        _w.feed()


def stop():
    """Returns True if the watchdog is off. Some builds cannot switch it off until the next reset."""
    global _w
    if _w is None:
        return True
    try:
        _w.deinit()
    except Exception as e:
        print("watchdog cannot be stopped on this build (%s): the board resets in %d s unless fed" % (e, _timeout))
        return False
    _w = None
    return True


def status():
    return {"running": _w is not None, "timeout_s": _timeout, "last_reset": str(microcontroller.cpu.reset_reason)}


def was_watchdog():
    return "WATCHDOG" in str(microcontroller.cpu.reset_reason)


def test(timeout=5):
    """Safe test: runs the watchdog for a few seconds while feeding it, then stops it."""
    print("last reset:", status()["last_reset"])
    if not start(timeout):
        return
    for i in range(3):
        time.sleep(1)
        feed()
        print("fed", i + 1, status())
    print("stopped:", stop())


def trip_test(timeout=5):
    """Hangs on purpose. The board should reset after `timeout` seconds and was_watchdog() then says True."""
    start(timeout)
    print("hanging now; expect a reset in %d s" % timeout)
    while True:
        pass
