# SPDX-License-Identifier: GPL-3.0-or-later
# BosW-V1.2 - Copyright (C) 2026 the BosW authors. See LICENSE.
"""ntp_time.py - real time from a selectable NTP server, for other programs (not code.py).

Other programs:   import ntp_time as nt
                  nt.configure(server="time.google.com", interval=2, tz_min=330)
                  ... in your main loop:  nt.poll();  print(nt.text())
Serial terminal:  import ntp_time as nt; nt.sync(); nt.text(); nt.status()
Standalone demo: nt.run()      (needs Wi-Fi already connected, or settings.toml credentials)

No extra library: this speaks raw NTP (UDP port 123) itself.
Time is kept as INTEGER milliseconds, because CircuitPython floats are only ~7 digits and
cannot hold a Unix time to the second. Use now() / now_ms() / text(), not float seconds.
"""
import time

NTP_TO_UNIX = 2208988800                     # seconds between 1900 and 1970
SERVERS = ["pool.ntp.org", "time.google.com", "time.cloudflare.com",
           "time.windows.com", "time.apple.com"]

_pool = None
_cfg = {"server": SERVERS[0], "interval": 2, "tz_min": 0, "set_rtc": True, "timeout": 0.6}
_st = {"base_ms": 0, "base_mono": 0, "synced": False, "ip": None, "last_try": 0,
       "last_ok": 0, "offset_ms": 0, "rtt_ms": 0, "count": 0, "errors": 0, "fails": 0,
       "last_err": ""}


# ---------- configuration ----------
def servers():
    return list(SERVERS)


def set_server(host):
    """Pick one of servers() or any custom host name / IP."""
    _cfg["server"] = host
    _st["ip"] = None                         # resolve again on next sync


def set_interval(seconds):
    """1, 2 or 3 seconds as requested (any value >= 1 is accepted)."""
    _cfg["interval"] = max(1, seconds)


def set_tz(minutes):
    """Minutes east of UTC, e.g. 330 for UTC+5:30, -300 for UTC-5."""
    _cfg["tz_min"] = minutes


def configure(server=None, interval=None, tz_min=None, set_rtc=None):
    if server is not None:
        set_server(server)
    if interval is not None:
        set_interval(interval)
    if tz_min is not None:
        set_tz(tz_min)
    if set_rtc is not None:
        _cfg["set_rtc"] = set_rtc


# ---------- the NTP exchange ----------
def _socketpool():
    global _pool
    if _pool is None:
        import socketpool, wifi
        _pool = socketpool.SocketPool(wifi.radio)
    return _pool


def sync():
    """One NTP request. Returns True on success; never raises."""
    pool = _socketpool()
    _st["last_try"] = time.monotonic_ns()
    s = None
    try:
        if _st["ip"] is None:
            _st["ip"] = pool.getaddrinfo(_cfg["server"], 123)[0][4][0]
        pkt = bytearray(48)
        pkt[0] = 0x1B                        # LI 0, version 3, mode 3 (client)
        buf = bytearray(48)
        s = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        s.settimeout(_cfg["timeout"])
        t0 = time.monotonic_ns()
        s.sendto(pkt, (_st["ip"], 123))
        n, _ = s.recvfrom_into(buf)
        t1 = time.monotonic_ns()
        if n < 48 or (buf[0] & 7) != 4 or buf[1] == 0:
            raise ValueError("bad reply")
        secs = int.from_bytes(buf[40:44], "big")
        frac = int.from_bytes(buf[44:48], "big")
        if secs == 0:
            raise ValueError("no time in reply")
        rtt_ms = (t1 - t0) // 1000000
        new_ms = (secs - NTP_TO_UNIX) * 1000 + ((frac * 1000) >> 32) + rtt_ms // 2
        if _st["synced"]:
            _st["offset_ms"] = new_ms - now_ms()     # how far the free-running clock had drifted
        _st["base_ms"] = new_ms
        _st["base_mono"] = t1
        _st["synced"] = True
        _st["rtt_ms"] = rtt_ms
        _st["last_ok"] = t1
        _st["count"] += 1
        _st["fails"] = 0
        if _cfg["set_rtc"]:
            _set_rtc()
        return True
    except Exception as e:
        _st["errors"] += 1
        _st["fails"] += 1
        _st["last_err"] = "%s: %s" % (type(e).__name__, e)
        if _st["fails"] >= 3:
            _st["ip"] = None                 # DNS may have changed or failed
        return False
    finally:
        if s:
            s.close()


def poll():
    """Call as often as you like from your main loop. Syncs only when the interval is due.
    Returns True when a sync happened and worked."""
    if time.monotonic_ns() - _st["last_try"] < _cfg["interval"] * 1000000000 and _st["last_try"]:
        return False
    return sync()


# ---------- reading the time ----------
def now_ms():
    """Unix time in UTC, integer milliseconds. None until the first sync."""
    if not _st["synced"]:
        return None
    return _st["base_ms"] + (time.monotonic_ns() - _st["base_mono"]) // 1000000


def now():
    """Unix time in UTC, integer seconds."""
    m = now_ms()
    return None if m is None else m // 1000


def local():
    """time.struct_time in local time (UTC + tz_min)."""
    s = now()
    return None if s is None else time.localtime(s + _cfg["tz_min"] * 60)


def text(ms=False):
    """'2026-10-26 14:05:09' (or with .mmm)."""
    m = now_ms()
    if m is None:
        return "not synced"
    t = time.localtime(m // 1000 + _cfg["tz_min"] * 60)
    out = "%04d-%02d-%02d %02d:%02d:%02d" % t[:6]
    return out + (".%03d" % (m % 1000)) if ms else out


def clock():
    """'14:05:09'"""
    t = local()
    return "not synced" if t is None else "%02d:%02d:%02d" % t[3:6]


def age_s():
    """Seconds since the last good sync (None if never)."""
    return (time.monotonic_ns() - _st["last_ok"]) // 1000000000 if _st["synced"] else None


def status():
    return {"synced": _st["synced"], "server": _cfg["server"], "ip": _st["ip"],
            "interval": _cfg["interval"], "tz_min": _cfg["tz_min"], "time": text(True),
            "age_s": age_s(), "offset_ms": _st["offset_ms"], "rtt_ms": _st["rtt_ms"],
            "syncs": _st["count"], "errors": _st["errors"], "last_err": _st["last_err"]}


def _set_rtc():
    try:
        import rtc
        rtc.RTC().datetime = time.localtime(now() + _cfg["tz_min"] * 60)
    except Exception:
        pass


# ---------- standalone demo ----------
def run(seconds=None):
    """Prints the time every second. Stop with Ctrl-C, or pass a number of seconds."""
    import os, wifi
    if not wifi.radio.connected:
        wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
    end = None if seconds is None else time.monotonic() + seconds
    last = 0
    while end is None or time.monotonic() < end:
        poll()
        if time.monotonic() - last >= 1:
            last = time.monotonic()
            s = status()
            print(text(True), "| %s | rtt %d ms | drift fix %d ms | errors %d" % (
                s["server"], s["rtt_ms"], s["offset_ms"], s["errors"]))
