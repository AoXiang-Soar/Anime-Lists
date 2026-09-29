"""自测 exe 内置的本地服务：静态站点 + 存档端点。"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "packaging" / "launcher.py"


def main() -> int:
    data_dir = pathlib.Path(tempfile.gettempdir()) / f"anime-save-test-{int(time.time())}"
    site_dir = data_dir / "site"
    env = dict(
        os.environ,
        ANIME_LISTS_DATA_DIR=str(data_dir),
        ANIME_LISTS_NO_BROWSER="1",
        ANIME_LISTS_TEST_SECONDS="30",  # 让服务活着，测试自己会提前结束它
        LOCALAPPDATA=str(site_dir),
    )
    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        url = proc.stdout.readline().strip()
        if not url.startswith("http://127.0.0.1:"):
            print("no url:", url)
            return 1
        print("server:", url)

        def get(path: str):
            with urllib.request.urlopen(url.rstrip("/") + path, timeout=10) as r:
                return r.status, r.read()

        def post(path: str, payload: dict):
            req = urllib.request.Request(
                url.rstrip("/") + path,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8", "replace")

        status, html = get("/")
        has_inject = b"ANIME_LISTS_SERVER" in html
        print(f"GET /            -> {status}, 注入服务端信息: {has_inject}, {len(html)} bytes")

        status, meta = get("/__meta")
        print("GET /__meta      ->", status, meta)

        status, res = post("/__save", {"name": "anime-lists-data.json", "text": json.dumps({"version": 2, "watched": [1, 2, 3], "starred": []})})
        print("POST /__save     ->", status, res)
        saved = data_dir / "anime-lists-data.json"
        print("  文件落盘      ->", saved.exists(), saved.read_text(encoding="utf-8")[:60] if saved.exists() else "")

        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
        status, res = post("/__save", {"name": "anime-lists-poster-2026-09-29.png", "base64": png})
        print("POST /__save png ->", status, res)
        print("  海报落盘      ->", (data_dir / "anime-lists-poster-2026-09-29.png").exists())

        status, body = get("/anime-lists-data.json")
        print("GET 存档回读     ->", status, body.decode("utf-8")[:60])

        status, res = post("/__save", {"name": "../evil.json", "text": "x"})
        print("路径穿越防护     ->", status, res, "| 上级目录是否被写:", (data_dir.parent / "evil.json").exists())

        status, res = post("/__save", {"name": "bad.exe", "text": "x"})
        print("扩展名白名单     ->", status, res)

        # 站点静态文件确实可访问
        status, js = get("/app.js")
        print("GET /app.js      ->", status, len(js), "bytes")
        status, data = get("/data/2024.js")
        print("GET /data/2024.js->", status, len(data), "bytes")

        # ---- 健康检查与自愈：把解压目录里的首页删掉，服务应当自己修回来
        status, health = get("/__health")
        print("GET /__health    ->", status, health)
        site_index = pathlib.Path(json.loads(health)["site"]) / "index.html"
        site_index.unlink()
        status, health2 = get("/__health")
        print("  删掉 index.html 后 ok =", json.loads(health2)["ok"])
        status, html = get("/")
        print("  再次访问首页   ->", status, len(html), "bytes（自愈）")
        status, health3 = get("/__health")
        print("  自愈后 ok =", json.loads(health3)["ok"])
        self_check = site_index.exists()
        print("  文件已恢复 =", self_check)

        # ---- 复用判断：坏实例不该被复用
        sys.path.insert(0, str(ROOT / "packaging"))
        import launcher as launcher_mod  # noqa: E402

        site_index.unlink()
        found = launcher_mod.find_running()
        print("坏实例被复用 =", found is not None)

        # ---- /__quit 能让进程退出
        try:
            get("/__quit")
        except Exception:
            pass
        for _ in range(30):
            time.sleep(0.3)
            if proc.poll() is not None:
                break
        print("__quit 后进程已退出 =", proc.poll() is not None)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
