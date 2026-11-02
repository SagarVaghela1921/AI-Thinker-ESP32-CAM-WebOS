# SPDX-License-Identifier: GPL-3.0-or-later
# BosW-V1.2 - Copyright (C) 2026 the BosW authors. See LICENSE.
"""storage_mgr.py - shared SD card and flash storage helper (not code.py).

Other programs:   import storage_mgr as sm
                  sm.mount_sd()
                  lg = sm.Logger("/sd/power.csv")      # buffered: few writes, less SD wear
                  lg.log("12.3,1.5")                   # call as often as you like
                  sm.start_web(); then call sm.poll() in your loop
Serial terminal:  import storage_mgr as sm; sm.test(); sm.info(); sm.ls("/sd")
Standalone:       import storage_mgr; storage_mgr.run()    (Wi-Fi from settings.toml)
Named storage_mgr because CircuitPython already has a built-in module called storage.
"""
import os, time, gc
import board, sdioio, storage

SD = "/sd"
ROOTS = {"sd": SD, "flash": ""}
PROTECT_EXT = (".py", ".mpy", ".toml", ".cfg", ".ini")       # never deletable
PROTECT_PREFIX = ("config", "settings")                      # config / settings files
_sd = None
_loggers = []
_srv = None


# ---------- mounting ----------
def is_mounted():
    try:
        a, b = os.statvfs(SD), os.statvfs("/")
        return (a[0], a[2]) != (b[0], b[2])
    except OSError:
        return False


def mount_sd(freq=20_000_000):
    """1-bit SDIO (GPIO14 CLK, 15 CMD, 2 D0). Keeps GPIO12/13 free."""
    global _sd
    if is_mounted():
        return True
    try:
        try:
            os.mkdir(SD)
        except OSError:
            pass
        _sd = sdioio.SDCard(clock=board.SDIO_CLK, command=board.SDIO_CMD,
                            data=[board.SDIO_D0], frequency=freq)
        storage.mount(storage.VfsFat(_sd), SD)
        return True
    except Exception as e:
        print("SD mount failed:", e)
        _sd = None
        return False


def unmount_sd():
    """Flushes every logger first, then it is safe to remove the card."""
    global _sd
    flush_all()
    if not is_mounted():
        return True
    try:
        storage.umount(SD)
        if _sd:
            _sd.deinit()
        _sd = None
        return True
    except Exception as e:
        print("unmount failed:", e)
        return False


# ---------- info and files ----------
def space(path):
    try:
        v = os.statvfs(path)
        return {"total": v[0] * v[2], "free": v[0] * v[3]}
    except OSError:
        return None


def info():
    sd = space(SD) if is_mounted() else None
    return {"sd": dict(sd or {}, mounted=sd is not None),
            "flash": dict(space("/") or {}, mounted=True)}


def protected(path):
    p = path.rstrip("/")
    try:
        if os.stat(p)[0] & 0x4000:
            return True                                  # folders are never deletable
    except OSError:
        return True
    name = p.split("/")[-1].lower()
    return (name.endswith(PROTECT_EXT) or name.startswith(PROTECT_PREFIX)
            or p == "/lib" or p.startswith("/lib/"))


def ls(path="/"):
    out = []
    base = path.rstrip("/")
    for n in sorted(os.listdir(path)):
        s = os.stat(base + "/" + n)
        out.append((n, bool(s[0] & 0x4000), s[6]))
    return out


def delete(path):
    if ".." in path or protected(path):
        return False, "Protected: folders, .py, .toml, config files and /lib cannot be deleted"
    try:
        os.remove(path)
        return True, "Deleted " + path
    except OSError as e:
        return False, "Error: %s" % e


def read_text(path, limit=4000):
    with open(path) as f:
        return f.read(limit)


# ---------- buffered logging (this is what saves SD wear) ----------
class Logger:
    """Collects lines in RAM and appends them in one write every flush_s seconds or
    flush_bytes bytes. Use longer intervals for internal flash (default 300 s)."""
    def __init__(self, path, flush_s=None, flush_bytes=2048):
        self.path = path
        self.flush_s = flush_s if flush_s is not None else (30 if path.startswith(SD) else 300)
        self.flush_bytes = flush_bytes
        self.buf = []
        self.size = 0
        self.t = time.monotonic()
        _loggers.append(self)

    def log(self, line):
        s = line if line.endswith("\n") else line + "\n"
        self.buf.append(s)
        self.size += len(s)
        if self.size >= self.flush_bytes or time.monotonic() - self.t >= self.flush_s:
            self.flush()

    def tick(self):
        if self.buf and time.monotonic() - self.t >= self.flush_s:
            self.flush()

    def flush(self):
        if not self.buf:
            return True
        try:
            with open(self.path, "a") as f:        # open, one write, close = consistent FAT
                f.write("".join(self.buf))
            self.buf, self.size = [], 0
            self.t = time.monotonic()
            return True
        except OSError as e:
            print("log flush failed:", e)
            self.t = time.monotonic()
            return False


def flush_all():
    for lg in _loggers:
        lg.flush()


def tick():
    for lg in _loggers:
        lg.tick()


# ---------- web page ----------
PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<style>*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0 auto;padding:12px;max-width:760px}
.c{border:1px solid #8886;border-radius:10px;padding:10px;margin-bottom:12px}
.bar{height:10px;background:#8883;border-radius:5px;overflow:hidden;margin:6px 0}.bar i{display:block;height:100%;background:#378ADD}
.r{display:flex;justify-content:space-between;gap:8px;padding:7px 0;border-bottom:1px solid #8884;flex-wrap:wrap}
a{color:#0a7cd8;cursor:pointer}small{opacity:.7}button{padding:8px 10px;font-size:14px}
@media(prefers-color-scheme:dark){body{background:#111;color:#eee}}</style>
<h3>Storage</h3><div id=m></div>
<div class=c><b>SD card</b> <span id=ss></span><div class=bar><i id=sb></i></div>
<div id=sbt></div><button id=um onclick="act('unmount')">Unmount SD</button> <button onclick="act('mount')">Mount SD</button>
<div id=sl></div></div>
<div class=c><b>Internal flash</b> <span id=fs></span><div class=bar><i id=fb></i></div><div id=fl></div></div>
<script>const $=i=>document.getElementById(i),dirs={sd:'',flash:''};
const mb=b=>(b/1048576).toFixed(1)+' MB';
const q=(r,p)=>'root='+r+'&path='+encodeURIComponent(p);
async function act(a){$('m').textContent=await (await fetch('/api/'+a,{method:'POST'})).text();load()}
async function del(r,p){if(confirm('Delete '+p+'?')){$('m').textContent=await (await fetch('/api/del?'+q(r,p),{method:'POST'})).text();load()}}
function cd(r,d){dirs[r]=d;load()}
async function lst(r,id){const d=dirs[r];const x=await (await fetch('/api/ls?'+q(r,d))).json();
if(x.err){$(id).innerHTML='<small>'+x.err+'</small>';return}
let h=d?'<div class=r><a onclick="cd(\\''+r+'\\',\\''+d.split('/').slice(0,-1).join('/')+'\\')">.. up</a></div>':'';
for(const [n,isd,s,p] of x.items){const f=d?d+'/'+n:n;
h+='<div class=r><span>'+(isd?'<a onclick="cd(\\''+r+'\\',\\''+f+'\\')">&#128193; '+n+'</a>':n+' <small>'+(s/1024).toFixed(1)+' kB</small>')+'</span><span>'+
(isd?'':'<a href="/api/get?'+q(r,f)+'" download>download</a> ')+(p?'<small>protected</small>':'<a onclick="del(\\''+r+'\\',\\''+f+'\\')">delete</a>')+'</span></div>'}
$(id).innerHTML=h||'<small>Empty</small>'}
async function load(){const i=await (await fetch('/api/info')).json();
const set=(k,bid,tid,x)=>{if(!x.mounted){$(tid).textContent='not mounted';$(bid).style.width='0';return}
const u=x.total-x.free;$(bid).style.width=(100*u/x.total)+'%';$(tid).textContent=mb(x.free)+' free of '+mb(x.total)};
set('sd','sb','ss',i.sd);set('flash','fb','fs',i.flash);$('sbt').textContent='';
$('um').disabled=!i.sd.mounted;
if(i.sd.mounted)lst('sd','sl');else $('sl').innerHTML='';lst('flash','fl')}
load();setInterval(()=>{if(!document.hidden)load()},15000)</script>"""


def _path(request):
    from adafruit_httpserver import Response
    root = ROOTS.get(request.query_params.get("root") or "flash")
    rel = (request.query_params.get("path") or "").strip("/")
    if root is None or ".." in rel or (root == SD and not is_mounted()):
        return None
    return (root + "/" + rel) if rel else (root or "/")


def start_web(port=8081):
    global _srv
    import socketpool, wifi
    from adafruit_httpserver import Server, Response, JSONResponse, FileResponse, POST
    _srv = srv = Server(socketpool.SocketPool(wifi.radio), debug=False)

    @srv.route("/")
    def index(r):
        return Response(r, PAGE, content_type="text/html")

    @srv.route("/api/info")
    def api_info(r):
        return JSONResponse(r, info())

    @srv.route("/api/ls")
    def api_ls(r):
        p = _path(r)
        if p is None:
            return JSONResponse(r, {"err": "not available"})
        try:
            items = [(n, d, s, protected(p.rstrip("/") + "/" + n)) for n, d, s in ls(p)]
            return JSONResponse(r, {"items": items})
        except OSError as e:
            return JSONResponse(r, {"err": str(e)})

    @srv.route("/api/get")
    def api_get(r):
        p = _path(r)
        if p is None or "/" not in p.strip("/") and p == "/":
            return Response(r, "Bad path", status=(400, "Bad Request"))
        return FileResponse(r, p.split("/")[-1], p.rsplit("/", 1)[0] or "/")

    @srv.route("/api/del", methods=[POST])
    def api_del(r):
        p = _path(r)
        if p is None:
            return Response(r, "Bad path", status=(400, "Bad Request"))
        return Response(r, delete(p)[1])

    @srv.route("/api/unmount", methods=[POST])
    def api_um(r):
        return Response(r, "SD unmounted, safe to remove" if unmount_sd() else "Unmount failed")

    @srv.route("/api/mount", methods=[POST])
    def api_m(r):
        return Response(r, "SD mounted" if mount_sd() else "SD mount failed")

    srv.start(str(wifi.radio.ipv4_address), port)
    print("Storage page: http://%s:%d" % (wifi.radio.ipv4_address, port))
    return srv


def poll():
    """Call from your main loop: serves the web page and flushes timed-out log buffers."""
    if _srv:
        _srv.poll()
    tick()


# ---------- test and standalone ----------
def test():
    """Reads SD and flash, then does a small buffered write test."""
    print("SD mounted:", mount_sd())
    print("info:", info())
    for p in (SD, "/"):
        try:
            print(p, ls(p))
        except OSError as e:
            print(p, "error:", e)
    lg = Logger(SD + "/test_log.txt", flush_s=5, flush_bytes=64)
    for i in range(6):
        lg.log("test line %d" % i)
    lg.flush()
    try:
        print("test_log.txt tail:", read_text(SD + "/test_log.txt")[-40:])
    except OSError as e:
        print("read back failed:", e)


def run(port=8081):
    import wifi
    mount_sd()
    if not wifi.radio.connected:
        wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
    start_web(port)
    while True:
        poll()


# ---------- BosW-V1.2 additions (everything above is unchanged) ----------
# Links to CircuitPython's built-in web workflow, so the desktop can open its file manager
# (view, edit, upload, download, rename) and its terminal in a window on the web workflow's own port.
# Needs CIRCUITPY_WEB_API_PASSWORD in settings.toml. Nothing here starts a server of its own.
def workflow_port():
    try:
        return int(os.getenv("CIRCUITPY_WEB_API_PORT") or 80)
    except ValueError:
        return 80


def workflow_enabled():
    """True when settings.toml has a web workflow password (needed for /fs/ and /code/)."""
    return os.getenv("CIRCUITPY_WEB_API_PASSWORD") is not None


def _wf(path):
    import wifi
    p = workflow_port()
    return "http://%s%s%s" % (wifi.radio.ipv4_address, "" if p == 80 else ":%d" % p, path)


def fs_url(path="/"):
    """Built-in file manager (view / edit / upload / download) at a folder or file."""
    return _wf("/fs" + (path if path.startswith("/") else "/" + path))


def terminal_url():
    """Built-in serial terminal."""
    return _wf("/code/")


def workflow_info():
    return {"enabled": workflow_enabled(), "port": workflow_port(),
            "files": fs_url("/"), "terminal": terminal_url()}
