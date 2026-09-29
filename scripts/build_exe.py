"""把整个静态站点打包成一个单文件 exe（PyInstaller）。

产物：dist/AnimeLists.exe —— 双击即可，无需 Python、无需服务器。

用法：
    python scripts/build_exe.py            # 需要先跑过 build_data.py
    python scripts/build_exe.py --keep     # 保留 build/ 中间目录
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
STAGE = BUILD / "site"
DIST = ROOT / "dist"
STAGE_FILES = ("index.html", "styles.css", "app.js", "README.md")


def data_version() -> str:
    """用数据的生成日期当版本号，数据一变就会重新解压。"""
    index = ROOT / "data" / "index.js"
    if index.exists():
        payload = index.read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";")
        stamp = json.loads(payload).get("generatedAt")
        if stamp:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone().strftime("%Y.%m.%d")
    return datetime.now().strftime("%Y.%m.%d")


def stage_site() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for name in STAGE_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, STAGE / name)
    # 只带站点真正用到的 data/*.js，跳过 16MB 的原始抓取缓存
    data_dst = STAGE / "data"
    data_dst.mkdir()
    count = 0
    for path in sorted((ROOT / "data").glob("*.js")):
        shutil.copy2(path, data_dst / path.name)
        count += 1
    if not count:
        raise SystemExit("data/ 里没有 .js 数据，请先运行 python scripts/build_data.py")
    print(f"staged {count} data files -> {STAGE}")


def stage_launcher(version: str) -> Path:
    src = (ROOT / "packaging" / "launcher.py").read_text(encoding="utf-8")
    out = BUILD / "launcher.py"
    out.write_text(re.sub(r'^VERSION = ".*"$', f'VERSION = "{version}"', src, flags=re.M), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="保留 build/ 中间产物")
    parser.add_argument("--name", default="AnimeLists", help="exe 文件名（不含扩展名）")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 pyinstaller，正在安装…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    version = data_version()
    print(f"site version: {version}")
    stage_site()
    launcher = stage_launcher(version)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        args.name,
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / "work"),
        "--specpath",
        str(BUILD),
        "--add-data",
        f"{STAGE}{';' if sys.platform == 'win32' else ':'}.",
        str(launcher),
    ]
    print("$", " ".join(cmd))
    subprocess.check_call(cmd)

    exe = DIST / (args.name + (".exe" if sys.platform == "win32" else ""))
    print(f"\n✅ 打包完成：{exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    if not args.keep:
        shutil.rmtree(BUILD, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
