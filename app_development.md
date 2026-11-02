# BosW-V1.2 app development guide (for people and for AI assistants)

An app is a **.zip file** that a user installs from the desktop's *App manager*. Nothing else is needed:
install the zip and the app starts. This guide lists everything an app can use. Write apps only from this
guide: use the manifest keys, hooks and `bw` functions below and nothing else.

Target: CircuitPython 10.3.1 on an ESP32-CAM, library `boswv12`. Apps are plain `.py`, `.html`, `.css`,
`.js`, `.json` and any other files (a `.mpy` also works for the Python parts).

## 1. Package layout
```
myapp.zip
  manifest.json      required, at the top level of the zip
  index.html         the window page (omit for a background-only app)
  style.css, main.js, data/...   any other files, in any sub-folders
  app.py             optional: the code that runs on the board
```
Build it with `zip -r myapp.zip .` from inside the app's folder. Each file must be 100 kB or smaller.
The desktop unpacks the zip into `/apps/<name>/`. Re-installing the same name replaces the old copy.

## 2. manifest.json
| key | values | meaning |
|---|---|---|
| `name` | lowercase letters, digits, `_`, up to 24 characters | app id, used in URLs and by `bw.send` |
| `title` | text | shown in the Start menu and App manager |
| `version` | text | shown in the App manager |
| `run` | `foreground`, `background`, `both` | how it runs (section 3). Default `foreground` |
| `startup` | `true` / `false` | start at boot (only for `background` and `both`; ignored for slaves) |
| `role` | `standalone`, `master`, `slave`, `companion` | relationship to other apps (section 4). Default `standalone` |
| `master` | app name | required for `slave` and `companion`: the master they belong to |
| `main` | file name | the window page. Default `index.html` (none for `background`) |
| `tick_ms` | number | minimum milliseconds between `tick` calls. Default 0 (every loop) |
| `requires` | list of library names | libraries that must be in `/lib`. The App manager lists missing ones and starts the app once they are installed |

Example:
```json
{"name": "mylogger", "title": "My Logger", "version": "1.0",
 "run": "background", "startup": true, "tick_ms": 1000, "requires": []}
```

## 3. Run modes
| `run` | window | `tick` runs | typical use |
|---|---|---|---|
| `foreground` | yes | only while its window is open | tools and viewers |
| `background` | none (unless `main` is given) | from start until stopped | loggers, controllers, services |
| `both` | yes | from start until stopped, also with the window closed | dashboards that keep working |

* Opening a `foreground` window starts the app. Closing the window (or 15 seconds without the page
  being alive) stops it.
* `background` and `both` apps are started by `startup`, by the *Start* button in the App manager, or by
  their master. *Stop* stops them.
* If an app's code raises an exception, the app is stopped and the error text is shown in the App manager.
  Other apps keep running.

## 4. Roles
| role | starts | stops |
|---|---|---|
| `standalone` | on its own | on its own |
| `master` | on its own. Starting it also starts its slaves and companions | stopping it stops its slaves; companions keep running |
| `slave` | only under its master. Starting a slave starts the master first | when the master stops |
| `companion` | on its own, and together with its master | on its own |

Apps in a group share values through `bw.shared` and talk with `bw.send` (section 6).

## 5. app.py hooks (all optional)
```python
def start(bw):                  # once, when the app starts
def tick(bw):                   # repeatedly while running (see tick_ms)
def stop(bw):                   # once, when the app stops
def message(bw, sender, text):  # another app called bw.send(thisapp, text)
def api(params):                # the page (or anything on the network) called /app/api?name=<name>&k=v
    return "text"               # params is a dict of the query values; the return value is sent as text
```
`api` has no `bw`: keep a module-level `_bw` that `start` sets if `api` needs it.

## 6. The `bw` object
| member | what it does |
|---|---|
| `bw.name`, `bw.role`, `bw.master` | this app's identity |
| `bw.shared` | a dict shared by all running apps (store small values: numbers, short text) |
| `bw.send(to, text)` | calls `message()` of the running app `to`. Returns `True` if delivered |
| `bw.running()` | list of running app names |
| `bw.now_ms()` | real time, Unix milliseconds in UTC (integer). `None` until the clock has synced |
| `bw.time_text()` | local time as `YYYY-MM-DD HH:MM:SS`, or `not synced` |
| `bw.log(file, line)` | adds a line to `/sd/<app>_<file>`. Buffered, so the SD card is written rarely. `False` if there is no SD card |
| `bw.load(default)` | reads this app's `settings.json` (returns `default` or `{}` if none) |
| `bw.save(dict)` | writes this app's `settings.json`. Save only when a value really changed |
| `bw.sm` | the library module `storage_mgr` (section 7) |
| `bw.ntp` | the library module `ntp_time` (section 7) |

## 7. Library modules an app may call
`storage_mgr` (as `bw.sm`): `is_mounted()`, `mount_sd()`, `unmount_sd()`, `space(path)`, `info()`,
`ls(path)`, `read_text(path)`, `protected(path)`, `delete(path)`, `Logger(path)`, `flush_all()`,
`fs_url(path)`, `terminal_url()`, `workflow_info()`.
`ntp_time` (as `bw.ntp`): `now()`, `now_ms()`, `text()`, `clock()`, `local()`, `age_s()`, `status()`,
`servers()`. Do not change the NTP server or interval from an app; the user does that in Time settings.
Never call `watchdog_guard.start()` or `.stop()`. Any other CircuitPython module that is on the board
can be imported; list non-built-in ones in `requires`.

## 8. The window page
* The page is shown in an iframe. Relative links (`style.css`, `main.js`) are rewritten to load from the
  zip, so use plain relative paths. Do not load anything from the internet.
* To talk to `app.py`: `fetch('/app/api?name=<name>&cmd=x')` and read the text of the answer.
* Make it touch friendly: buttons at least 44 px high, `<meta name="viewport" content="width=device-width,initial-scale=1">`,
  and a layout that works from 240 px wide.
* Refresh live values with `setInterval` (1 second or slower).

## 9. Rules that keep the board stable
* `tick` and `message` must return quickly (well under 100 ms). Never use `while True`, long
  `time.sleep`, or blocking network calls. The whole system shares one loop and a watchdog resets the
  board if the loop stalls for 15 seconds.
* Keep memory small: no big lists or strings, call `gc.collect()` after building large text.
* Write files rarely (use `bw.log`). Never write to the flash in a loop.
* A pin, UART or I2C bus can have only one owner. Open it in `start()` and call `deinit()` in `stop()`, otherwise the app cannot restart.
* Do not touch `/lib`, `code.py`, `settings.toml` or other apps' folders.
* Catch your own errors if you want the app to keep running; an uncaught exception stops it.

## 10. Templates for the five app types
### A. Foreground tool (window only)
`manifest.json`: `{"name":"clockface","title":"Clock Face","run":"foreground"}`
`app.py` (optional, only if the page needs data from the board):
```python
def api(params):
    return "hello"
```
`index.html` shows a button; its script calls `fetch('/app/api?name=clockface')` and prints the answer.

### B. Background logger (starts at boot, no window)
`manifest.json`: `{"name":"minutelog","title":"Minute Log","run":"background","startup":true,"tick_ms":60000}`
```python
def tick(bw):
    bw.log("log.csv", "%s,%s" % (bw.time_text(), bw.shared.get("value", "")))
```

### C. Master with a slave
Master `manifest.json`: `{"name":"boss","title":"Boss","run":"both","role":"master","startup":true}`
```python
_bw = None
def start(bw):
    global _bw
    _bw = bw
    bw.shared["count"] = 0
def message(bw, sender, text):
    bw.shared["last"] = sender + ": " + text
def api(params):
    return "count=%s last=%s" % (_bw.shared.get("count"), _bw.shared.get("last")) if _bw else "not running"
```
Slave `manifest.json`: `{"name":"helper","title":"Helper","run":"background","role":"slave","master":"boss","tick_ms":1000}`
```python
def tick(bw):
    n = bw.shared.get("count", 0) + 1
    bw.shared["count"] = n
    bw.send("boss", "count is now %d" % n)
```

### D. Companion (starts with the master, keeps running without it)
`manifest.json`: `{"name":"sidekick","title":"Sidekick","run":"background","role":"companion","master":"boss","tick_ms":5000}`
```python
def tick(bw):
    bw.shared["sidekick_time"] = bw.time_text()
```

### E. Service with an API (no window)
`manifest.json`: `{"name":"counter","title":"Counter","run":"background","startup":true}`
```python
_n = 0
def tick(bw):
    global _n
    _n += 1
def api(params):
    return str(_n)
```
Other apps and pages read it with `fetch('/app/api?name=counter')`.

## 11. Hardware on the ESP32-CAM (AI-Thinker)
`boswv12.run()` mounts the SD card in **1-bit mode** (GPIO14 clock, GPIO15 command, GPIO2 data 0). That keeps
GPIO12 and GPIO13 free for apps. BosW itself uses no other header pin.

| header pin | CircuitPython name | use in an app |
|---|---|---|
| IO12 | `board.IO12` | free in 1-bit SD mode. It is a boot strapping pin and must read low at boot: use it as a UART TX with a 4.7k resistor to GND, and never put an I2C pull-up on it |
| IO13 | `board.IO13` | free in 1-bit SD mode (good UART RX) |
| IO14, IO15, IO2 | `board.IO14`, `board.IO15`, `board.IO2` | SD card clock, command, data 0. Free only if no SD card is used |
| IO4 | `board.IO4` | flash LED and SD data 1. Leave it alone |
| IO16 | `board.IO16` | PSRAM chip select. Do not use |
| IO0 | `board.IO0` | boot mode and camera clock. Avoid |
| U0R, U0T | `board.IO3`, `board.IO1` | console serial. Avoid |
| 5V, 3V3, GND | | power. The ESP32 logic is **3.3 V and not 5 V tolerant** |

Camera pins (`board.CAMERA_*`) and the red LED (GPIO33, active low) are not on the header.
With only one or two free pins, add pins through a serial link or I2C (section 12).

```python
import board, busio
uart = busio.UART(tx=board.IO12, rx=board.IO13, baudrate=115200, timeout=0.03)   # co-processor link
# I2C: any two output-capable pins work. Modules need 4.7k pull-ups to 3.3 V (many have them).
# The camera's own bus, board.CAMERA_SIOC / board.CAMERA_SIOD, already has 3.3 V pull-ups (not tested here).
```
Level shifting: a 5 V device's TX into the ESP32 RX needs a divider (1k in series, 2k from the RX pin to GND).
The ESP32's 3.3 V TX into a 5 V board's RX worked in the tested design.

## 12. Projects with co-processors and pin extenders
Plug and play means: one zip per app, the user installs it, connects the wires shown on the app's own page, and
it works. Extend the ESP32-CAM's few pins in one of two ways:
* **Co-processor** (any microcontroller with a serial port, for example an ATmega328P board): it provides many
  inputs, outputs, ADC channels and PWM, and can do time-critical sampling that the ESP32 should not.
* **I2C expander or converter** (PCF8574: 8 I/O, MCP23017: 16 I/O, ADS1115: 16-bit ADC).

How to split a project into apps (each its own zip):
| app | role | job |
|---|---|---|
| the device driver, one per co-processor or expander | `slave` of the project master | owns the UART or I2C bus, does one short exchange per `tick`, publishes values in `bw.shared`, accepts commands in `message()` |
| the project | `master` | logic, maths and the window page. Reads `bw.shared`, sends commands with `bw.send` |
| helpers (logging, alarms) | `companion` | read `bw.shared`; keep working if the master stops |

Rules:
1. Only the driver app touches the bus. Everything else uses `bw.shared` and `bw.send`.
2. Name shared values `"<driver>.<key>"`, for example `coproc.values`. Keep them small.
3. The driver publishes its health (`coproc.ok`, bad and timeout counts). The master page shows
   "not connected: check the wiring" when it is not ok, with a small table of the wires to connect.
4. The driver opens the bus in `start()` and calls `deinit()` in `stop()`.
5. One exchange per `tick` with a timeout of 30 ms or less. Use `tick_ms` of 20 or more.
6. Ship the co-processor's source code (for example a `firmware/` folder) and a `README.txt` in the master's zip.
   The desktop does not flash anything: the user programs the co-processor once.

**Recommended serial protocol** (tested in the worked example, section 13): the ESP32 asks, the co-processor
answers, and the co-processor never talks unasked.
* Request: `?<optional text>` ending with a newline.
* Reply: `$<fields separated by commas>*HH` ending with a newline, `HH` = XOR of the characters between `$` and `*`, in hex.
* The co-processor averages its samples between polls, so no data is lost at any poll rate.
* The reply carries a sequence number and a running error count. The ESP32 ignores a reply with a bad checksum.
* Use 115200 baud. On a 16 MHz AVR the error is about 2%; if checksums fail, 57600 or 250000 are safer.
* On a Pro Mini the serial pins (0 and 1) are shared with the USB-serial adapter: unplug them while uploading.

**Driver app for a UART co-processor** (`manifest.json`: `{"name":"coproc","title":"Co-processor link","run":"background","role":"slave","master":"project","tick_ms":50}`):
```python
import board, busio

_uart = None
_text = ""

def start(bw):
    global _uart
    _uart = busio.UART(tx=board.IO12, rx=board.IO13, baudrate=115200, timeout=0.03)
    bw.shared["coproc.ok"] = False
    bw.shared["coproc.bad"] = 0

def stop(bw):
    global _uart
    if _uart:
        _uart.deinit()
        _uart = None

def message(bw, sender, text):          # the master sends text to show on the co-processor's display
    global _text
    _text = text

def _parse(line):
    try:
        s = line.decode().strip()
        body, cs = s[1:].split("*")
        x = 0
        for ch in body:
            x ^= ord(ch)
        if s[0] != "$" or x != int(cs, 16):
            return None
        return [float(v) for v in body.split(",")]
    except (ValueError, IndexError, UnicodeError):
        return None

def tick(bw):
    _uart.reset_input_buffer()
    _uart.write(("?" + _text + "\n").encode())
    vals = _parse(_uart.readline() or b"")
    if vals is None:
        bw.shared["coproc.ok"] = False
        bw.shared["coproc.bad"] += 1
    else:
        bw.shared["coproc.ok"] = True
        bw.shared["coproc.values"] = vals
```
**Master app** (`"role":"master","run":"both","startup":true`) reads the driver's values:
```python
_bw = None

def start(bw):
    global _bw
    _bw = bw

def tick(bw):
    v = bw.shared.get("coproc.values")
    if v:
        bw.shared["project.first"] = v[0]
        bw.send("coproc", "first=%.1f" % v[0])

def api(params):
    if not _bw or not _bw.shared.get("coproc.ok"):
        return "not connected: check the wiring"
    return str(_bw.shared.get("coproc.values"))
```
**Co-processor sketch skeleton** (Arduino, 5 V board, hardware `Serial`, answers with two analog readings):
```cpp
#include <avr/wdt.h>
uint16_t seq;
char rx[24];
uint8_t rl;

void reply() {
  char b[40];
  snprintf(b, sizeof b, "%d,%d,%u", analogRead(A0), analogRead(A1), seq++);
  uint8_t x = 0;
  for (char *p = b; *p; p++) x ^= *p;
  Serial.print('$'); Serial.print(b); Serial.print('*');
  if (x < 16) Serial.print('0');
  Serial.println(x, HEX);
}

void setup() { Serial.begin(115200); wdt_enable(WDTO_2S); }

void loop() {
  wdt_reset();
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { rx[rl] = 0; if (rx[0] == '?') reply(); rl = 0; }
    else if (c != '\r') { if (rl < sizeof rx - 1) rx[rl++] = c; else rl = 0; }
  }
}
```
Keep co-processor code free of `String`, blocking delays and `SoftwareSerial`, and keep the watchdog on.

**Driver app for an I2C expander** (PCF8574 at address 0x20; not tested here):
```python
import board, busio

ADDR = 0x20
_i2c = None
_out = 0xFF

def start(bw):
    global _i2c
    _i2c = busio.I2C(scl=board.CAMERA_SIOC, sda=board.CAMERA_SIOD)

def stop(bw):
    global _i2c
    if _i2c:
        _i2c.deinit()
        _i2c = None

def message(bw, sender, text):          # "set 240" writes the 8 output pins
    global _out
    if text.startswith("set "):
        _out = int(text[4:]) & 0xFF

def tick(bw):
    while not _i2c.try_lock():
        pass
    try:
        _i2c.writeto(ADDR, bytes([_out]))
        buf = bytearray(1)
        _i2c.readfrom_into(ADDR, buf)
        bw.shared["expander.inputs"] = buf[0]
    finally:
        _i2c.unlock()
```
Two devices on one I2C bus must have different addresses (an LCD backpack is often 0x27 or 0x3F).

## 13. Worked example: DC power meter (tested design)
Parts: an Arduino Pro Mini 5 V 16 MHz as co-processor, an ADS1115 (address 0x48, range +/-4.096 V, 0.125 mV per count),
an ACS712-30A current sensor on A0 (used up to 10 A), a voltage divider R1 10k / R2 1k on A2 (up to 25 V), and a
16x2 LCD with a PCF8574 backpack (0x27, or 0x3F). Wires: Pro Mini TX to ESP IO13 through 1k with 2k from IO13 to GND;
ESP IO12 to Pro Mini RX with 4.7k from IO12 to GND.
* The Pro Mini samples both ADS1115 channels continuously and answers each poll with
  `$n,avg0,avg2,min0,max0,min2,max2,seq,err*HH` (averages are over every sample since the last poll;
  `n = 0` means no new data; `err` counts I2C failures). The poll is `?V,A,W,Wh` and the four numbers go on the LCD.
* Maths in the master app: `volts = avg2 * 0.000125 * 11`, `amps = (avg0 * 0.000125 - zero) / 0.066`, with `zero`
  (about 2.5 V) measured with no load and a multimeter calibration applied afterwards.
* Energy: add up in integers (milli-joules), because CircuitPython floats keep only about 7 digits.
* Smoothing: a time-based moving average on the readings, and a slower one plus small steps for the LCD text.
* Mapping to apps: a `slave` driver owns the UART (section 12), a `master` does the maths and shows the window,
  a `companion` records rows with `bw.log`.

## 14. Checklist before handing over a zip
1. `manifest.json` is at the top level and is valid JSON with a lowercase `name`.
2. `run`, `role` and `master` follow sections 2 to 4; a `slave` or `companion` names an existing master.
3. Every file is under 100 kB and every page link is relative.
4. `tick` is short and never blocks; every exception that must not stop the app is caught.
5. Libraries that are not built in are listed in `requires`.
6. Hardware apps: only one app owns each bus or pin, it calls `deinit()` in `stop()`, the page shows the wiring and a clear "not connected" message, and the zip contains the co-processor's source and a `README.txt`.

License: the library is GPL-3.0-or-later. An app zip is a separate work and carries its own license.
