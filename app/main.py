#!/usr/bin/env python3
"""OpenList + ME-Frp(mefrpc) + Firefox-VNC 一体化管理面板.

对外仅监听 PANEL_PORT(7860):
  /                    管理面板
  /_ctrl/...           面板控制 API
  /firefox/...         noVNC 反代(含 WebSocket)
  /openlist/...        OpenList 反代(去前缀)
  其余路径              OpenList 反代(原样透传, 保证 SPA 绝对路径可用)
"""
import asyncio
import json
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"


def _find_bin(name):
    for p in (BASE / name, BASE.parent / "bin" / name, Path("/app") / name):
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return str(BASE / name)


MENFRPC_BIN = _find_bin("mefrpc")
OPENLIST_BIN = _find_bin("openlist")

PANEL_PORT = int(os.environ.get("PANEL_PORT", "7860"))
OPENLIST_DATA = os.environ.get("OPENLIST_DATA", "/www/1/data")
OPENLIST_PORT = int(os.environ.get("OPENLIST_PORT", "5244"))
NOVNC_PORT = 6080
VNC_PORT = 5900
FIREFOX_URL_DEFAULT = os.environ.get("FIREFOX_URL", "about:blank")
ADMIN_PASSWORD = os.environ.get("OPENLIST_ADMIN_PASSWORD", "admin123")

def pick_data_dir():
    # 官方推荐持久化路径 /mnt/workspace（运行时挂载，重启可保留）
    candidates = [
        os.environ.get("DATA_DIR"),
        "/mnt/workspace/oplist-data",
        "/root/Desktop/oplist-data",
        str(BASE / "data" / "oplist-data"),
    ]
    for base in candidates:
        if not base:
            continue
        p = Path(base)
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".writetest"
            probe.write_text("1")
            probe.unlink()
            (p / "openlist").mkdir(exist_ok=True)
            (p / "logs").mkdir(exist_ok=True)
            return p
        except Exception:
            continue
    return Path("/app/data/oplist-data")


DATA_DIR = pick_data_dir()

MEFRPC_BIN = _find_bin("mefrpc")
FRPC_BIN = _find_bin("frpc")
MEFRPC_CFG = DATA_DIR / "mefrpc.json"
FRPC_CFG = DATA_DIR / "frpc.json"
UI_CFG = DATA_DIR / "ui.json"

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
}


def ts():
    return datetime.now().strftime("%m-%d %H:%M:%S")


def which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


HAVE_GUI = (
    os.environ.get("DISABLE_GUI", "0") != "1"
    and all(which(x) for x in ("Xvfb", "x11vnc", "websockify", "firefox-esr"))
)


class Proc:
    """带环形日志的子进程包装."""

    def __init__(self, name, supervised=False):
        self.name = name
        self.supervised = supervised  # 崩溃/退出后由守护协程拉起
        self.popen = None
        self.logs = deque(maxlen=1000)
        self.started_at = None
        self.stopping = False
        self.lock = threading.Lock()

    def log(self, line):
        for l in str(line).rstrip().splitlines() or [""]:
            self.logs.append(f"[{ts()}] {l}")

    def build_argv(self):
        raise NotImplementedError

    def start(self):
        with self.lock:
            if self.popen and self.popen.poll() is None:
                return True
            try:
                argv = self.build_argv()
                self.log(f"$ {shlex.join(argv)}")
                self.popen = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    errors="replace",
                    cwd=str(BASE),
                    start_new_session=True,
                    env={**os.environ, **self.extra_env()},
                )
                self.started_at = time.time()
                self.stopping = False
                threading.Thread(target=self._pump, daemon=True).start()
                return True
            except Exception as e:
                self.log(f"启动失败: {e}")
                return False

    def extra_env(self):
        return {}

    def _pump(self):
        p = self.popen
        try:
            for line in p.stdout:
                self.log(line.rstrip())
        except Exception:
            pass
        rc = p.wait()
        if not self.stopping:
            self.log(f"进程退出 code={rc}")

    def stop(self, timeout=8):
        with self.lock:
            p, self.popen = self.popen, None
        if not p or p.poll() is not None:
            return
        self.stopping = True
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass
        try:
            p.wait(timeout=timeout)
        except Exception:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def status(self):
        p = self.popen
        running = bool(p and p.poll() is None)
        d = {"running": running, "pid": p.pid if running else None}
        if running and self.started_at:
            d["uptime"] = int(time.time() - self.started_at)
        return d


class CmdProc(Proc):
    def __init__(self, name, argv, env=None, supervised=False):
        super().__init__(name, supervised)
        self.argv = argv
        self.env_extra = env or {}

    def build_argv(self):
        return self.argv

    def extra_env(self):
        return self.env_extra


# ---------------------------------------------------------------- services
PROCS = {}
if HAVE_GUI:
    PROCS["xvfb"] = CmdProc("xvfb", ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"], supervised=True)
    PROCS["x11vnc"] = CmdProc(
        "x11vnc",
        ["x11vnc", "-display", ":99", "-forever", "-nopw", "-quiet", "-noxdamage",
         "-repeat", "-rfbport", str(VNC_PORT), "-listen", "127.0.0.1"],
        supervised=True,
    )
    PROCS["novnc"] = CmdProc(
        "novnc",
        ["websockify", "--web", "/usr/share/novnc", f"127.0.0.1:{NOVNC_PORT}", f"127.0.0.1:{VNC_PORT}"],
        supervised=True,
    )
    PROCS["firefox"] = CmdProc(
        "firefox",
        ["firefox-esr", "--no-remote", "--kiosk", FIREFOX_URL_DEFAULT],
        env={"DISPLAY": ":99", "MOZ_ALLOW_RUN_AS_ROOT": "1", "MOZ_DISABLE_CONTENT_SANDBOX": "1"},
        supervised=True,
    )
PROCS["openlist"] = CmdProc(
    "openlist",
    [OPENLIST_BIN, "server", "--data", OPENLIST_DATA],
    supervised=True,
)

SYSTEM_LOG = Proc("system")


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))


def mefrpc_state():
    return load_json(MEFRPC_CFG, {"cmd": "", "autostart": False})


def parse_mefrpc_cmd(cmd):
    parts = shlex.split(cmd.strip())
    if not parts:
        raise ValueError("命令不能为空")
    if os.path.basename(parts[0]) != "mefrpc":
        raise ValueError("仅允许运行 mefrpc 程序")
    return [MENFRPC_BIN] + parts[1:]


def start_mefrpc(cmd=None, autostart=None):
    st = mefrpc_state()
    if cmd is not None:
        st["cmd"] = cmd.strip()
    if autostart is not None:
        st["autostart"] = bool(autostart)
    argv = parse_mefrpc_cmd(st["cmd"])  # raises ValueError
    save_json(MEFRPC_CFG, st)
    old = PROCS.pop("mefrpc", None)
    if old:
        old.stop()
    PROCS["mefrpc"] = CmdProc("mefrpc", argv, supervised=st["autostart"])
    SYSTEM_LOG.log(f"启动 mefrpc: {st['cmd']}")
    PROCS["mefrpc"].start()
    return st


def start_frpc(config=None, autostart=None):
    st = load_json(FRPC_CFG, {"config": "", "autostart": False})
    if config is not None:
        st["config"] = config
    if autostart is not None:
        st["autostart"] = bool(autostart)
    if not st["config"].strip():
        raise ValueError("请先填写 frp 的 TOML 配置")
    if not FRPC_BIN or not os.path.exists(FRPC_BIN):
        raise ValueError("frpc 二进制缺失，请确认已下载")
    cfg_path = DATA_DIR / "frpc.toml"
    cfg_path.write_text(st["config"])
    save_json(FRPC_CFG, st)
    argv = [FRPC_BIN, "-c", str(cfg_path)]
    old = PROCS.pop("frpc", None)
    if old:
        old.stop()
    PROCS["frpc"] = CmdProc("frpc", argv, supervised=st["autostart"])
    SYSTEM_LOG.log("启动 frpc (原版)")
    PROCS["frpc"].start()
    return st


def firefox_url():
    return load_json(UI_CFG, {}).get("firefox_url") or FIREFOX_URL_DEFAULT


def set_firefox_url(url):
    cfg = load_json(UI_CFG, {})
    cfg["firefox_url"] = url
    save_json(UI_CFG, cfg)
    if "firefox" in PROCS:
        PROCS["firefox"].argv = ["firefox-esr", "--no-remote", "--kiosk", url]


VERSION_CACHE = {}


def get_version(key, argv):
    if key not in VERSION_CACHE:
        try:
            VERSION_CACHE[key] = subprocess.run(
                argv, capture_output=True, text=True, timeout=10
            ).stdout.strip().splitlines()[0]
        except Exception as e:
            VERSION_CACHE[key] = f"unknown ({e})"
    return VERSION_CACHE[key]


CLIENT = None


async def check_openlist_http():
    if CLIENT is None:
        return False
    try:
        async with CLIENT.get(
            f"http://127.0.0.1:{OPENLIST_PORT}/ping", timeout=ClientTimeout(total=2)
        ) as r:
            return r.status == 200
    except Exception:
        return False


async def supervisor():
    """守护核心服务; openlist 就绪后设置管理员密码."""
    admin_done = False
    while True:
        for p in list(PROCS.values()):
            if p.supervised and (not p.popen or p.popen.poll() is not None):
                SYSTEM_LOG.log(f"[supervisor] 重启 {p.name}")
                p.start()
        if not admin_done:
            ok = await check_openlist_http()
            if ok:
                try:
                    r = subprocess.run(
                        [OPENLIST_BIN, "admin", "set", ADMIN_PASSWORD,
                         "--data", OPENLIST_DATA],
                        capture_output=True, text=True, timeout=30,
                    )
                    SYSTEM_LOG.log(
                        f"已设置 OpenList 管理员密码 -> 账号 admin 密码 {ADMIN_PASSWORD} "
                        f"{(r.stdout + r.stderr).strip()[:120]}"
                    )
                except Exception as e:
                    SYSTEM_LOG.log(f"设置管理员密码失败: {e}")
                admin_done = True
        await asyncio.sleep(5)


# ---------------------------------------------------------------- proxy
def fwd_headers(req):
    h = {}
    for k, v in req.headers.items():
        lk = k.lower()
        if lk in HOP_HEADERS or lk.startswith("sec-websocket"):
            continue
        h[k] = v
    h["X-Forwarded-For"] = req.remote or ""
    h["X-Forwarded-Proto"] = req.scheme
    h["X-Forwarded-Host"] = req.host
    return h


async def relay(req, base, path):
    qs = req.rel_url.query_string
    url = base + path + (f"?{qs}" if qs else "")
    hdrs = fwd_headers(req)
    data = None if req.method in ("GET", "HEAD") else req.content
    try:
        async with CLIENT.request(
            req.method, url, headers=hdrs, data=data, allow_redirects=False
        ) as r:
            resp = web.StreamResponse(status=r.status)
            for k, v in r.headers.items():
                lk = k.lower()
                if lk in ("transfer-encoding", "connection", "keep-alive"):
                    continue
                if lk == "set-cookie":
                    resp.headers.add(k, v)
                else:
                    resp.headers[k] = v
            await resp.prepare(req)
            if req.method != "HEAD":
                async for chunk in r.content.iter_any():
                    await resp.write(chunk)
            await resp.write_eof()
            return resp
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return web.HTTPBadGateway(text=f"上游服务不可达: {e}")


async def ws_relay(req, base_ws, path):
    qs = req.rel_url.query_string
    url = base_ws + path + (f"?{qs}" if qs else "")
    protos = [
        p.strip() for p in req.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()
    ]
    try:
        up = await CLIENT.ws_connect(url, protocols=protos or None)
    except Exception as e:
        return web.HTTPBadGateway(text=f"WS 上游连接失败: {e}")

    down = web.WebSocketResponse(protocols=tuple(protos))
    await down.prepare(req)

    async def pump(src, dst, bytes_dir):
        try:
            async for msg in src:
                if msg.type == WSMsgType.BINARY:
                    await dst.send_bytes(msg.data)
                elif msg.type == WSMsgType.TEXT:
                    await dst.send_str(msg.data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        except Exception:
            pass
        finally:
            try:
                await dst.close()
            except Exception:
                pass

    try:
        await asyncio.gather(pump(up, down, "up"), pump(down, up, "down"))
    except Exception:
        pass
    finally:
        for c in (up, down):
            try:
                await c.close()
            except Exception:
                pass
    return down


def make_proxy(base_http, base_ws, strip_prefix):
    async def handler(request):
        tail = request.match_info.get("tail", "")
        path = "/" + tail
        if strip_prefix and request.path == "/" + strip_prefix:
            path = "/"
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await ws_relay(request, base_ws, path)
        return await relay(request, base_http, path)
    return handler


# ---------------------------------------------------------------- api routes
async def index(_):
    return web.FileResponse(STATIC / "index.html")


async def firefox_console(_):
    return web.FileResponse(STATIC / "firefox.html")


async def favicon(_):
    return web.Response(status=204)


async def api_status(request):
    svcs = {name: p.status() for name, p in PROCS.items()}
    ol_ok = await check_openlist_http()
    return web.json_response({
        "services": svcs,
        "have_gui": HAVE_GUI,
        "openlist_http": ol_ok,
        "openlist_addr": f"/openlist/",
        "firefox_console": "/_ctrl/firefox_console",
        "mefrpc": {**mefrpc_state(), **PROCS.get("mefrpc", Proc("mefrpc")).status()},
        "frpc": {**load_json(FRPC_CFG, {"config": "", "autostart": False}),
                 **PROCS.get("frpc", Proc("frpc")).status()},
        "versions": {
            "openlist": get_version("openlist", [OPENLIST_BIN, "version"]),
            "mefrpc": get_version("mefrpc", [MENFRPC_BIN, "-v"]),
            "frpc": get_version("frpc", [FRPC_BIN, "-v"]) if FRPC_BIN else "缺失",
        },
        "data_dir": str(DATA_DIR),
        "panel_port": PANEL_PORT,
        "ff_url": firefox_url(),
    })


async def api_log(request):
    name = request.match_info["name"]
    n = int(request.rel_url.query.get("tail", "300"))
    p = PROCS.get(name) if name != "system" else SYSTEM_LOG
    if p is None:
        return web.Response(status=404, text="no such service")
    lines = list(p.logs)[-max(1, min(n, 1000)):]
    return web.Response(text="\n".join(lines), content_type="text/plain", charset="utf-8")


async def api_service(request):
    name = request.match_info["name"]
    action = request.rel_url.query.get("action", "restart")
    if name == "mefrpc":
        return web.HTTPBadRequest(text="use /_ctrl/mefrpc/*")
    p = PROCS.get(name)
    if p is None:
        return web.Response(status=404, text="no such service")
    if action == "start":
        p.start()
    elif action == "stop":
        p.supervised = False
        p.stop()
    elif action == "restart":
        p.stop()
        p.start()
    else:
        return web.HTTPBadRequest(text="bad action")
    return web.json_response({name: p.status()})


async def api_mefrpc_start(request):
    body = await request.json()
    try:
        st = start_mefrpc(body.get("cmd"), body.get("autostart"))
    except ValueError as e:
        return web.HTTPBadRequest(text=str(e))
    except json.JSONDecodeError:
        return web.HTTPBadRequest(text="invalid json")
    return web.json_response({**st, **PROCS["mefrpc"].status()})


async def api_mefrpc_stop(_):
    p = PROCS.get("mefrpc")
    if p:
        p.supervised = False
        p.stop()
    return web.json_response({"ok": True})


async def api_mefrpc_autostart(request):
    body = await request.json()
    st = mefrpc_state()
    st["autostart"] = bool(body.get("enabled"))
    save_json(MEFRPC_CFG, st)
    if "mefrpc" in PROCS:
        PROCS["mefrpc"].supervised = st["autostart"]
    return web.json_response(st)


async def api_firefox(request):
    body = await request.json()
    url = (body.get("url") or "").strip()
    action = body.get("action", "restart")
    if url:
        if not url.startswith(("http://", "https://", "about:", "file://")):
            return web.HTTPBadRequest(text="URL 必须以 http(s):// 或 about: 开头")
        set_firefox_url(url)
    p = PROCS.get("firefox")
    if p is None:
        return web.json_response({"firefox": "disabled (无 GUI 环境)"})
    if action in ("restart", "reload"):
        p.stop()
        p.start()
    elif action == "stop":
        p.supervised = False
        p.stop()
    elif action == "start":
        p.start()
    return web.json_response({"firefox": p.status(), "url": firefox_url()})


async def api_frpc_start(request):
    body = await request.json()
    try:
        st = start_frpc(body.get("config"), body.get("autostart"))
    except ValueError as e:
        return web.HTTPBadRequest(text=str(e))
    except json.JSONDecodeError:
        return web.HTTPBadRequest(text="invalid json")
    return web.json_response({**st, **PROCS["frpc"].status()})


async def api_frpc_stop(_):
    p = PROCS.get("frpc")
    if p:
        p.supervised = False
        p.stop()
    return web.json_response({"ok": True})


async def api_frpc_autostart(request):
    body = await request.json()
    st = load_json(FRPC_CFG, {"config": "", "autostart": False})
    st["autostart"] = bool(body.get("enabled"))
    save_json(FRPC_CFG, st)
    if "frpc" in PROCS:
        PROCS["frpc"].supervised = st["autostart"]
    return web.json_response(st)


# ---------------------------------------------------------------- app setup
async def on_startup(app):
    global CLIENT
    CLIENT = ClientSession()
    if HAVE_GUI:
        PROCS["xvfb"].start()
        await asyncio.sleep(1.2)
        PROCS["x11vnc"].start()
        PROCS["novnc"].start()
        await asyncio.sleep(0.5)
        PROCS["firefox"].start()
    PROCS["openlist"].start()
    st = mefrpc_state()
    if st.get("cmd") and st.get("autostart"):
        SYSTEM_LOG.log("[boot] autostart mefrpc")
        try:
            start_mefrpc(st["cmd"], st["autostart"])
        except ValueError as e:
            SYSTEM_LOG.log(f"mefrpc 自启失败: {e}")
    fst = load_json(FRPC_CFG, {})
    if fst.get("config", "").strip() and fst.get("autostart"):
        SYSTEM_LOG.log("[boot] autostart frpc")
        try:
            start_frpc(fst["config"], fst["autostart"])
        except ValueError as e:
            SYSTEM_LOG.log(f"frpc 自启失败: {e}")
    app["supervisor"] = asyncio.create_task(supervisor())


async def on_cleanup(app):
    app["supervisor"].cancel()
    for p in PROCS.values():
        p.stop()
    try:
        await CLIENT.close()
    except Exception:
        pass


def build_app():
    app = web.Application(client_max_size=1024 ** 3)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    ol_http = f"http://127.0.0.1:{OPENLIST_PORT}"
    nv_http = f"http://127.0.0.1:{NOVNC_PORT}"
    ol_ws = f"ws://127.0.0.1:{OPENLIST_PORT}"
    nv_ws = f"ws://127.0.0.1:{NOVNC_PORT}"

    app.router.add_get("/", index)
    app.router.add_get("/favicon.ico", favicon)
    app.router.add_get("/_ctrl/firefox_console", firefox_console)

    app.router.add_get("/_ctrl/status", api_status)
    app.router.add_get("/_ctrl/log/{name}", api_log)
    app.router.add_post("/_ctrl/service/{name}", api_service)
    app.router.add_post("/_ctrl/mefrpc/start", api_mefrpc_start)
    app.router.add_post("/_ctrl/mefrpc/stop", api_mefrpc_stop)
    app.router.add_post("/_ctrl/mefrpc/autostart", api_mefrpc_autostart)
    app.router.add_post("/_ctrl/frpc/start", api_frpc_start)
    app.router.add_post("/_ctrl/frpc/stop", api_frpc_stop)
    app.router.add_post("/_ctrl/frpc/autostart", api_frpc_autostart)
    app.router.add_post("/_ctrl/firefox", api_firefox)

    # noVNC 反代 (含 WebSocket)
    app.router.add_route("*", "/firefox", make_proxy(nv_http, nv_ws, "firefox"))
    app.router.add_route("*", "/firefox/{tail:.*}", make_proxy(nv_http, nv_ws, "firefox"))

    # OpenList 反代 (去前缀)
    app.router.add_route("*", "/openlist", make_proxy(ol_http, ol_ws, "openlist"))
    app.router.add_route("*", "/openlist/{tail:.*}", make_proxy(ol_http, ol_ws, "openlist"))

    # 其余全部透传给 OpenList (SPA 的 /assets /api /d 等绝对路径由此兜底)
    app.router.add_route("*", "/{tail:.*}", make_proxy(ol_http, ol_ws, None))
    return app


if __name__ == "__main__":
    SYSTEM_LOG.log(f"面板启动 port={PANEL_PORT} data={DATA_DIR} gui={'on' if HAVE_GUI else 'off'}")
    web.run_app(build_app(), host="0.0.0.0", port=PANEL_PORT, print=None)
