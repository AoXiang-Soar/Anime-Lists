"""番剧年表 exe 启动器。

双击 exe 后：
  1. 把内置的静态站点释放到 %LOCALAPPDATA%\\AnimeLists\\<版本>\\；
  2. 在本机回环地址起一个只服务该站点的微型 http 服务（浏览器不允许
     file:// 页面写文件，所以自动保存需要一个本地端点）；
  3. 用默认浏览器打开 http://127.0.0.1:<port>/。

数据文件（自动保存 + 导出）一律写到 **exe 所在目录**：
    <exe 同目录>/anime-lists-data.json

页面关掉后 10 分钟内没有请求，进程会自己退出。打包脚本会把 VERSION
替换成数据生成日期。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "AnimeLists"
VERSION = "dev"
SITE_FILES = ("index.html", "styles.css", "app.js", "README.md")
PORT_CANDIDATES = (17877, 17878, 17879, 17880)
IDLE_TIMEOUT = 600  # 秒：页面关闭后多久自动退出
DATA_FILE = "anime-lists-data.json"
SAVE_EXTS = {".json", ".png", ".txt"}


def bundle_root() -> Path:
    """PyInstaller 解包目录（开发时就是仓库根目录）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def target_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    return Path(base) / APP_NAME / VERSION


def fail(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "番剧年表", 0x10)
    except Exception:  # pragma: no cover - 非 Windows 或没有桌面
        print(message, file=sys.stderr)


def ensure_site(src: Path, dst: Path) -> Path:
    index = dst / "index.html"
    if index.exists() and (dst / ".ready").exists():
        return index
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    for name in SITE_FILES:
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    data_src = src / "data"
    if not data_src.exists():
        raise FileNotFoundError("没找到 data 目录，exe 可能被破坏或不完整")
    shutil.copytree(data_src, dst / "data", ignore=shutil.ignore_patterns("raw"))
    (dst / ".ready").write_text(VERSION, encoding="utf-8")
    return index


def root_dir() -> Path:
    """存档目录 = exe 所在目录（可用 ANIME_LISTS_DATA_DIR 覆盖，自测用）。"""
    override = os.environ.get("ANIME_LISTS_DATA_DIR")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    """静态站点 + 两个本地端点：__save（写文件）、__ping（保活）。"""

    site_dir: Path = Path(".")
    data_dir: Path = Path(".")
    last_seen = time.time()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.site_dir), **kwargs)

    # ---- helpers ---------------------------------------------------------
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safe_name(self, name: str, directory: Path | None = None) -> Path:
        clean = Path(str(name or DATA_FILE)).name
        if Path(clean).suffix.lower() not in SAVE_EXTS:
            raise ValueError("不支持的文件类型")
        return (directory or self.data_dir) / clean

    def _write(self, target: Path, payload: dict) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if payload.get("base64") is not None:
            target.write_bytes(base64.b64decode(payload["base64"]))
        else:
            target.write_text(str(payload.get("text", "")), encoding="utf-8")

    # ---- routes ----------------------------------------------------------
    def do_GET(self):  # noqa: N802 - 标准库命名
        Handler.last_seen = time.time()
        path = self.path.split("?", 1)[0]
        if path == "/__ping":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/__meta":
            self._json(
                200,
                {
                    "mode": "exe",
                    "version": VERSION,
                    "savePath": str(self.data_dir / DATA_FILE),
                    "root": str(self.data_dir),
                },
            )
            return
        if path == "/__listing":
            files = []
            for item in sorted(self.data_dir.glob("anime-lists*.json")):
                try:
                    files.append({"name": item.name, "mtime": item.stat().st_mtime})
                except OSError:
                    continue
            files.sort(key=lambda x: -x["mtime"])
            self._json(200, {"files": files})
            return
        # 让页面能读到 exe 同目录下的存档（anime-lists-data.json 或用户导出的
        # anime-lists-2026-09-29.json 等）
        name = path.lstrip("/")
        if "/" not in name and name.startswith("anime-lists") and name.endswith(".json"):
            target = self.data_dir / name
            if not target.exists():
                self.send_response(404)
                self.end_headers()
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # 首页注入服务端信息，避免页面在 file:// 下做无谓探测
        if path in ("/", "/index.html"):
            index = self.site_dir / "index.html"
            if index.exists():
                html = index.read_text(encoding="utf-8")
                meta = {
                    "mode": "exe",
                    "version": VERSION,
                    "savePath": str(self.data_dir / DATA_FILE),
                }
                inject = f"<script>window.ANIME_LISTS_SERVER={json.dumps(meta, ensure_ascii=False)};</script>\n"
                html = html.replace("</head>", inject + "</head>", 1)
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        Handler.last_seen = time.time()
        if self.path.split("?", 1)[0] != "/__save":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            target = self._safe_name(payload.get("name", DATA_FILE))
            self._write(target, payload)
        except PermissionError:
            # exe 所在目录不可写（例如放在只读盘 / 压缩包里），退回到解压目录
            try:
                target = self._safe_name(payload.get("name", DATA_FILE), self.site_dir)
                self._write(target, payload)
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                return
        except Exception as exc:  # noqa: BLE001 - 把原因回给页面
            self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._json(200, {"ok": True, "path": str(target)})

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):  # 静音
        return


class Server(ThreadingHTTPServer):
    """Windows 上 allow_reuse_address 会让两个进程绑同一个端口（请求随机打到
    其中一个），必须关掉，端口冲突时就换下一个。"""

    allow_reuse_address = False
    daemon_threads = True
    request_queue_size = 32


def start_server(site: Path, data: Path):
    Handler.site_dir = site
    Handler.data_dir = data
    Handler.last_seen = time.time()
    for port in PORT_CANDIDATES + (0,):
        try:
            httpd = Server(("127.0.0.1", port), Handler)
        except OSError:
            continue
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, httpd.server_address[1]
    raise RuntimeError("端口都被占用，起不了本地服务")


def find_running() -> str | None:
    """已经有一个实例在跑就复用它，别开第二个。"""
    for port in PORT_CANDIDATES:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/__meta", timeout=1.2) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
            if meta.get("mode") == "exe":
                return f"http://127.0.0.1:{port}/"
        except Exception:  # noqa: BLE001 - 端口没人监听就是这种情况
            continue
    return None


def stop_when_idle(httpd) -> None:
    while True:
        time.sleep(20)
        if time.time() - Handler.last_seen > IDLE_TIMEOUT:
            httpd.shutdown()
            return


def main() -> int:
    if os.environ.get("ANIME_LISTS_NO_BROWSER") != "1":
        running = find_running()
        if running:
            webbrowser.open(running)
            return 0
    try:
        site = target_root()
        ensure_site(bundle_root(), site)
        data = root_dir()
        httpd, port = start_server(site, data)
    except Exception as exc:  # noqa: BLE001 - 任何异常都要给用户一个提示
        fail(f"启动失败：{exc}")
        return 1

    url = f"http://127.0.0.1:{port}/"
    if os.environ.get("ANIME_LISTS_NO_BROWSER") == "1":
        print(url, flush=True)
        # 自测用：ANIME_LISTS_TEST_SECONDS=20 会让服务多活 20 秒再退出
        stay = int(os.environ.get("ANIME_LISTS_TEST_SECONDS", "0"))
        if stay > 0:
            time.sleep(stay)
            httpd.shutdown()
        return 0
    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001
        opened = False
    if not opened:
        fail("页面已准备好，但没能自动打开浏览器。\n请手动在浏览器里打开：\n" + url)
        return 1
    print(f"番剧年表已启动：{url}\n数据文件：{data / DATA_FILE}\n（关掉页面约 10 分钟后本进程会自动退出）")
    stop_when_idle(httpd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
