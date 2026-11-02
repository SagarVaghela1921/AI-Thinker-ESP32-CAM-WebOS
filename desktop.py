# SPDX-License-Identifier: GPL-3.0-or-later
# BosW-V1.2 - Copyright (C) 2026 the BosW authors. See LICENSE.
"""boswv12.desktop - the BosW desktop server: time/NTP, web-app packages, links to the built-in
CircuitPython file manager and terminal. Used by boswv12.run(); also usable on its own:
    from boswv12 import desktop; desktop.start(8082); ... desktop.poll()
APP PACKAGE (.zip): manifest.json {"name": "hello", "title": "Hello", "version": "1.0",
  "main": "index.html", "requires": ["adafruit_requests"]} plus any files (.html .css .js .json .py ...).
  Installed into /apps/<name>/. An optional app.py with  def api(params): return "text"  is reachable at
  /app/api?name=<name>&... (params = the query values). If "requires" lists libraries that are not on the
  board, the App manager lists them and starts the app once they are installed.
WARNING: no password. An app's app.py runs on the board with full access. Install only apps you trust.
"""
import os, sys, time, json
from boswv12 import ntp_time, storage_mgr as sm, apps

_cfg = {"ntp_server": "pool.ntp.org", "ntp_interval": 2, "tz_min": 0, "custom": [], "hour12": False}
_saved = None
_srv = None


def _www():
    for d in ("/lib/boswv12/www", "/www"):
        try:
            os.stat(d + "/desktop.html")
            return d
        except OSError:
            pass
    return "/lib/boswv12/www"


# ---------- settings (only written when something changed) ----------
def load():
    global _saved
    for p in ("/sd/desktop.json", "/desktop.json"):
        try:
            with open(p) as f:
                _cfg.update(json.load(f))
            break
        except (OSError, ValueError):
            pass
    _saved = json.dumps(_cfg)
    apply()


def save():
    global _saved
    if json.dumps(_cfg) == _saved:
        return
    try:
        with open("/sd/desktop.json" if sm.is_mounted() else "/desktop.json", "w") as f:
            json.dump(_cfg, f)
        _saved = json.dumps(_cfg)
    except OSError as e:
        print("desktop save:", e)


def apply():
    ntp_time.configure(server=_cfg["ntp_server"], interval=_cfg["ntp_interval"], tz_min=_cfg["tz_min"])


def clock():
    """Board time: NTP when synced, otherwise the internal RTC (ntp_time also sets the RTC)."""
    ms, src = ntp_time.now_ms(), "ntp"
    if ms is None:
        t = time.time()
        ms, src = t * 1000, ("rtc" if t > 1700000000 else "none")
    return {"ms": ms, "tz": _cfg["tz_min"], "src": src, "h12": 1 if _cfg["hour12"] else 0}


# ---------- web routes ----------
def routes(srv):
    from adafruit_httpserver import Response, JSONResponse, FileResponse, POST
    bad = lambda q: Response(q, "Bad request", status=(400, "Bad Request"))

    @srv.route("/")
    def home(q):
        return FileResponse(q, "desktop.html", _www())

    @srv.route("/api/desk/links")
    def links(q):
        return JSONResponse(q, sm.workflow_info())

    @srv.route("/api/desk/time")
    def api_time(q):
        return JSONResponse(q, clock())

    @srv.route("/api/desk/ntp")
    def ntp_get(q):
        s = ntp_time.status()
        s.update({"servers": ntp_time.servers(), "custom": _cfg["custom"], "hour12": _cfg["hour12"]})
        return JSONResponse(q, s)

    @srv.route("/api/desk/ntp", methods=[POST])
    def ntp_set(q):
        p = q.query_params
        h = (p.get("server") or "").strip()
        if h and all(c.isalpha() or c.isdigit() or c in ".-" for c in h) and len(h) < 64:
            _cfg["ntp_server"] = h
            if h not in ntp_time.servers() and h not in _cfg["custom"]:
                _cfg["custom"].append(h)
        try:
            _cfg["ntp_interval"] = max(1, int(p.get("interval")))
            _cfg["tz_min"] = int(p.get("tz"))
        except (TypeError, ValueError):
            pass
        apply()
        save()
        return Response(q, "Time synced" if ntp_time.sync() else "Sync failed: " + ntp_time.status()["last_err"])

    @srv.route("/api/desk/h12", methods=[POST])
    def set_h12(q):
        _cfg["hour12"] = q.query_params.get("v") == "1"
        save()
        return Response(q, "OK")

    @srv.route("/api/desk/apps")
    def api_apps(q):
        return JSONResponse(q, apps.app_list())

    @srv.route("/api/desk/app_begin", methods=[POST])
    def a_begin(q):
        return Response(q, apps.app_begin(q.query_params.get("name") or ""))

    @srv.route("/api/desk/app_file", methods=[POST])
    def a_file(q):
        return Response(q, apps.app_file(q.query_params.get("name") or "", q.query_params.get("path") or "", q.body))

    @srv.route("/api/desk/app_remove", methods=[POST])
    def a_rm(q):
        return Response(q, apps.app_remove(q.query_params.get("name") or ""))

    @srv.route("/api/desk/app_done", methods=[POST])
    def a_done(q):
        return Response(q, apps.after_install(q.query_params.get("name") or ""))

    @srv.route("/api/desk/app_start", methods=[POST])
    def a_start(q):
        return Response(q, apps.start(q.query_params.get("name") or ""))

    @srv.route("/api/desk/app_stop", methods=[POST])
    def a_stop(q):
        return Response(q, apps.stop(q.query_params.get("name") or ""))

    @srv.route("/api/desk/app_fg", methods=[POST])
    def a_fg(q):
        return Response(q, apps.fg(q.query_params.get("name") or "", q.query_params.get("open") == "1"))

    @srv.route("/app/file")
    def app_fileget(q):
        name, f = q.query_params.get("name") or "", q.query_params.get("f") or "index.html"
        if not apps._ok(name) or not apps._safe(f):
            return bad(q)
        full = "%s/%s/%s" % (apps.APPS, name, f)
        try:
            if f.endswith(".html"):
                with open(full) as fh:
                    return Response(q, apps._rewrite(fh.read(), name), content_type="text/html")
            root, fn = full.rsplit("/", 1)
            return FileResponse(q, fn, root)
        except OSError as e:
            return Response(q, "Not found: %s" % e, status=(404, "Not Found"))

    @srv.route("/app/api")
    def app_api(q):
        name = q.query_params.get("name") or ""
        if not apps._ok(name):
            return bad(q)
        try:
            return Response(q, str(apps.call_api(name, dict(q.query_params.items()))))
        except Exception as e:
            return Response(q, "App error: %s: %s" % (type(e).__name__, e))


def start(port=8082):
    global _srv
    import socketpool, wifi
    from adafruit_httpserver import Server
    load()
    _srv = Server(socketpool.SocketPool(wifi.radio), debug=False)
    routes(_srv)
    _srv.start(str(wifi.radio.ipv4_address), port)
    print("BosW desktop: http://%s:%d" % (wifi.radio.ipv4_address, port))
    return _srv


def stop():
    global _srv
    try:
        if _srv:
            _srv.stop()
    except Exception:
        pass
    _srv = None


def poll():
    if _srv:
        try:
            _srv.poll()
        except Exception as e:
            print("desktop poll:", e)
