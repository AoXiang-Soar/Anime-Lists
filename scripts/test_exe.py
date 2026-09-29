"""对打包好的 exe 跑一遍完整前端交互测试（exe 内部服务 + 全部功能）。"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "AnimeLists.exe"
KEEP = re.compile(
    r'"errors"|totalTitles|saverMode|bindButtonVisible|freshAfter"|starCountAfterUnstar|'
    r'bulkWatched|posterOrderDescending|posterBulkBytes|fallbackVisible|coversLoaded|保存'
)


def main() -> int:
    if not EXE.exists():
        print("exe 不存在，先运行 python scripts/build_exe.py")
        return 1
    tmp = pathlib.Path(tempfile.gettempdir()) / f"anime-exe-{os.getpid()}"
    env = dict(
        os.environ,
        LOCALAPPDATA=str(tmp / "site"),
        ANIME_LISTS_DATA_DIR=str(tmp / "data"),
        ANIME_LISTS_NO_BROWSER="1",
        ANIME_LISTS_TEST_SECONDS="420",
    )
    proc = subprocess.Popen(
        [str(EXE)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        url = proc.stdout.readline().strip()
        print("exe server:", url, flush=True)
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_test.py"), url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in run.stdout.splitlines():
            if KEEP.search(line):
                print(line)
        if run.stderr.strip():
            print("stderr:", run.stderr.strip()[-500:])
        return run.returncode
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
