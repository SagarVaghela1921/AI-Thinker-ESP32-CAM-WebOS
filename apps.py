# SPDX-License-Identifier: GPL-3.0-or-later
# BosW-V1.2 - Copyright (C) 2026 the BosW authors. See LICENSE.
"""boswv12.apps - app packages (.zip) and how they run: foreground / background / both, startup,
and the roles standalone / master / slave / companion. See app_development.md.
"""
import os, sys, json, time

APPS = "/apps"
MAX_FILE = 100000
RUNS = ("foreground", "background", "both")
ROLES = ("standalone", "master", "slave", "companion")
shared = {}                      # values apps can share with each other through bw.shared
_run = {}                        # name -> {"mod", "bw", "i", "fg", "last"}
_errs = {}                       # name -> last error text


# ---------- app packages ----------
def _ok(name):
    return bool(name) and len(name) <= 24 and all(c.islower() or c.isdigit() or c == "_" for c in name)


def _safe(rel):
    return bool(rel) and rel[0] != "/" and ".." not in rel and "\\" not in rel and len(rel) < 100


def _isdir(p):
    try:
        return bool(os.stat(p)[0] & 0x4000)
    except OSError:
        return False


def _mkdirs(path):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        if not _isdir(cur):
            os.mkdir(cur)


def _rmtree(p):
    for n in os.listdir(p):
        q = p + "/" + n
        _rmtree(q) if _isdir(q) else os.remove(q)
    os.rmdir(p)


def have_lib(name):
    for p in ("/lib/%s.mpy", "/lib/%s.py", "/lib/%s", "/%s.py"):
        try:
            os.stat(p % name)
            return True
        except OSError:
            pass
    try:
        __import__(name)                       # built-in modules
        return True
    except Exception:
        return False


def manifest(name):
    try:
        with open("%s/%s/manifest.json" % (APPS, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def app_begin(name):
    if not _ok(name):
        return "Name: 1-24 characters, lowercase letters, digits and _"
    try:
        if _isdir(APPS + "/" + name):
            _rmtree(APPS + "/" + name)         # a re-install replaces the old copy
        _mkdirs(APPS + "/" + name)
    except OSError as e:
        return "Error: %s" % e
    return "Installing " + name


def app_file(name, rel, data):
    if not _ok(name) or not _safe(rel):
        return "Bad name or path"
    if len(data) > MAX_FILE:
        return "%s is over %d kB" % (rel, MAX_FILE // 1000)
    try:
        if "/" in rel:
            _mkdirs("%s/%s/%s" % (APPS, name, rel.rsplit("/", 1)[0]))
        with open("%s/%s/%s" % (APPS, name, rel), "wb") as f:
            f.write(data)
    except OSError as e:
        return "Error: %s" % e
    return "OK"


def app_remove(name):
    if not _ok(name) or not _isdir(APPS + "/" + name):
        return "No such app"
    stop(name)
    _errs.pop(name, None)
    try:
        _rmtree(APPS + "/" + name)
    except OSError as e:
        return "Error: %s" % e
    return "Removed " + name


def _rewrite(html, name):
    """Make relative src/href links in an app page point at /app/file so they load from the zip."""
    for attr in ('src="', 'href="'):
        out, i = "", 0
        while True:
            j = html.find(attr, i)
            if j < 0:
                break
            j += len(attr)
            k = html.find('"', j)
            ref = html[j:k]
            out += html[i:j]
            if ref and ref[0] not in "/#" and ":" not in ref:
                ref = "/app/file?name=%s&f=%s" % (name, ref)
            out += ref
            i = k
        html = out + html[i:]
    return html


def _mod(name):
    d = "%s/%s" % (APPS, name)
    sys.path.insert(0, d)
    sys.modules.pop("app", None)
    try:
        return __import__("app")
    finally:
        sys.path.remove(d)
        sys.modules.pop("app", None)



def info(name):
    """Manifest with defaults filled in."""
    m = manifest(name)
    run = m.get("run") if m.get("run") in RUNS else "foreground"
    role = m.get("role") if m.get("role") in ROLES else "standalone"
    return {"name": name, "title": m.get("title", name), "version": m.get("version", ""),
            "main": m.get("main", "" if run == "background" else "index.html"),
            "run": run, "role": role, "master": m.get("master", ""),
            "startup": bool(m.get("startup")) and run != "foreground" and role != "slave",
            "tick_ms": int(m.get("tick_ms", 0)), "requires": m.get("requires", [])}


def _names():
    try:
        return [n for n in sorted(os.listdir(APPS)) if _isdir(APPS + "/" + n)]
    except OSError:
        return []


def app_list():
    out = []
    for n in _names():
        i = info(n)
        i["missing"] = [l for l in i.pop("requires") if not have_lib(l)]
        i["state"] = "running" if n in _run else ("error" if n in _errs else "stopped")
        i["error"] = _errs.get(n, "")
        out.append(i)
    return out


def _ms():
    return time.monotonic_ns() // 1000000


class Bw:
    """The object every app hook receives. See app_development.md."""
    def __init__(self, name, i):
        from boswv12 import storage_mgr, ntp_time
        self.name, self.role, self.master, self.shared = name, i["role"], i["master"], shared
        self.sm, self.ntp = storage_mgr, ntp_time      # the library's own modules, ready to use
        self._logs = {}

    def send(self, to, text):
        """Deliver text to the message() hook of another running app. Returns True if it was delivered."""
        r = _run.get(to)
        f = getattr(r["mod"], "message", None) if r and r["mod"] else None
        if f is None:
            return False
        try:
            f(r["bw"], self.name, str(text))
        except Exception as e:
            _fail(to, e)
            return False
        return True

    def running(self):
        return list(_run)

    def now_ms(self):
        return self.ntp.now_ms()

    def time_text(self):
        return self.ntp.text()

    def log(self, file, line):
        """Buffered line to /sd/<app>_<file> (few writes, gentle on the card). False if no SD card."""
        if not self.sm.is_mounted():
            return False
        lg = self._logs.get(file)
        if lg is None:
            lg = self._logs[file] = self.sm.Logger("/sd/%s_%s" % (self.name, file))
        lg.log(line)
        return True

    def load(self, default=None):
        try:
            with open("%s/%s/settings.json" % (APPS, self.name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {} if default is None else default

    def save(self, data):
        try:
            with open("%s/%s/settings.json" % (APPS, self.name), "w") as f:
                json.dump(data, f)
            return True
        except OSError:
            return False

    def _close(self):
        for lg in self._logs.values():
            lg.flush()
            try:
                self.sm._loggers.remove(lg)
            except ValueError:
                pass


def _fail(name, e):
    _errs[name] = "%s: %s" % (type(e).__name__, e)
    print("app %s: %s" % (name, _errs[name]))
    stop(name)


def start(name):
    """Start an app's background side. Returns a message."""
    if name in _run:
        return "Already running"
    if not _ok(name) or not _isdir(APPS + "/" + name):
        return "No such app"
    i = info(name)
    miss = [l for l in i["requires"] if not have_lib(l)]
    if miss:
        return "Missing libraries: " + ", ".join(miss)
    if i["role"] == "slave":                              # a slave runs under its master
        if not i["master"] or not _isdir(APPS + "/" + i["master"]):
            return "Slave app: its master (%s) is not installed" % i["master"]
        if i["master"] not in _run:
            m = start(i["master"])                        # starting the master also starts its slaves
            if i["master"] not in _run:
                return m
        if name in _run:
            return "Started " + name
    mod = None
    try:
        if os.stat("%s/%s/app.py" % (APPS, name)):
            mod = _mod(name)
    except OSError:
        pass
    except Exception as e:
        _errs[name] = "%s: %s" % (type(e).__name__, e)
        return "App error: " + _errs[name]
    _errs.pop(name, None)
    r = _run[name] = {"mod": mod, "bw": Bw(name, i), "i": i, "fg": _ms(), "last": 0}
    f = getattr(mod, "start", None) if mod else None
    if f:
        try:
            f(r["bw"])
        except Exception as e:
            _fail(name, e)
            return "App error: " + _errs[name]
    if i["role"] == "master":                             # bring up its slaves and companions
        for j in _names():
            k = info(j)
            if k["master"] == name and k["role"] in ("slave", "companion"):
                start(j)
    return "Started " + name


def stop(name, _cascade=True):
    r = _run.pop(name, None)
    if r is None:
        return "Not running"
    f = getattr(r["mod"], "stop", None) if r["mod"] else None
    if f:
        try:
            f(r["bw"])
        except Exception as e:
            print("app %s stop: %s" % (name, e))
    r["bw"]._close()
    if _cascade and r["i"]["role"] == "master":           # slaves stop with their master, companions keep going
        for j in list(_run):
            if _run[j]["i"]["master"] == name and _run[j]["i"]["role"] == "slave":
                stop(j)
    return "Stopped " + name


def stop_all():
    for n in list(_run):
        stop(n, False)


def fg(name, is_open):
    """The desktop reports a window opening (and every 5 s while it stays open) or closing."""
    r = _run.get(name)
    if is_open:
        if r is None:
            msg = start(name)
            r = _run.get(name)
            if r is None:
                return msg
        r["fg"] = _ms()
        return "OK"
    if r and r["i"]["run"] == "foreground":
        stop(name)
    return "OK"


def after_install(name):
    i = info(name)
    miss = [l for l in i["requires"] if not have_lib(l)]
    if miss:
        return "Installed. Missing libraries: " + ", ".join(miss)
    return start(name) if i["startup"] else "Installed " + name


def boot():
    """Start every installed app marked startup (called once by boswv12.run)."""
    for n in _names():
        if info(n)["startup"]:
            start(n)


def poll():
    """Call every loop: runs the tick() hook of running apps."""
    now = _ms()
    for n in list(_run):
        r = _run.get(n)
        if r is None:
            continue
        if r["i"]["run"] == "foreground" and now - r["fg"] > 15000:
            stop(n)                                       # its window is gone
            continue
        f = getattr(r["mod"], "tick", None) if r["mod"] else None
        if f and now - r["last"] >= r["i"]["tick_ms"]:
            r["last"] = now
            try:
                f(r["bw"])
            except Exception as e:
                _fail(n, e)


def call_api(name, params):
    r = _run.get(name)
    return (r["mod"] if r and r["mod"] else _mod(name)).api(params)
