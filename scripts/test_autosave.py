"""在 exe 内置服务下验证「自动保存 + 自动恢复」。"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from smoke_test import WAIT_READY, Page  # noqa: E402

CHECK = r"""
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const api = window.__animeLists;
  const out = {
    saverMode: api.state.saverMode,
    autosaveOn: api.state.autosave,
    toggleChecked: document.querySelector('#autosaveToggle').checked,
    statusText: document.querySelector('#saveStatus').textContent,
    note: api.state.saveNote,
    bindHidden: document.querySelector('#btnBind').hidden,
    watchedBefore: document.querySelector('#watchedCount').textContent,
  };
  // 勾 3 部 + 收藏 2 部，等自动保存落盘
  const cards = Array.from(document.querySelectorAll('.card'));
  cards.slice(0, 3).forEach((c) => c.click());
  Array.from(document.querySelectorAll('.star')).slice(0, 2).forEach((s) => s.click());
  await sleep(1600);
  out.watchedAfter = document.querySelector('#watchedCount').textContent;
  out.starAfter = document.querySelector('#starCount').textContent;
  out.statusAfter = document.querySelector('#saveStatus').textContent;
  return out;
})()
"""

AFTER_RELOAD = r"""
(() => ({
  watched: document.querySelector('#watchedCount').textContent,
  starred: document.querySelector('#starCount').textContent,
  saverMode: window.__animeLists.state.saverMode,
}))()
"""


def main() -> int:
    use_exe = "--exe" in sys.argv
    target = ROOT / "dist" / "AnimeLists.exe" if use_exe else ROOT / "packaging" / "launcher.py"
    data_dir = pathlib.Path(tempfile.gettempdir()) / f"anime-autosave-{int(time.time())}"
    site_dir = data_dir / "site"
    # 预置一份「用户之前导出的」带日期文件，验证会自动挑最新的一份恢复
    data_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "scripts"))
    from anime_data import load_year  # noqa: E402

    seeded = [e["id"] for e in load_year(2024)[:2]]
    (data_dir / "anime-lists-2026-01-01.json").write_text(
        json.dumps({"version": 2, "watched": seeded, "starred": []}), encoding="utf-8"
    )
    print("预置存档 anime-lists-2026-01-01.json，含", len(seeded), "部已看")
    env = dict(
        os.environ,
        ANIME_LISTS_DATA_DIR=str(data_dir),
        ANIME_LISTS_NO_BROWSER="1",
        ANIME_LISTS_TEST_SECONDS="180",
        LOCALAPPDATA=str(site_dir),
    )
    proc = subprocess.Popen(
        [str(target)] if use_exe else [sys.executable, str(target)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    page = None
    try:
        url = proc.stdout.readline().strip()
        print("target:", target.name, "->", url)
        page = Page(url)
        page.ws.settimeout(120)
        page.goto(url)
        print("ready:", page.eval(WAIT_READY, await_promise=True))
        result = page.eval(CHECK, await_promise=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("预置数据是否被自动恢复:", result.get("watchedBefore") != "0")

        saved = data_dir / "anime-lists-data.json"
        payload = json.loads(saved.read_text(encoding="utf-8"))
        print(f"\n落盘文件: {saved}")
        print("  已看", len(payload["watched"]), "部 / 补番", len(payload["starred"]), "部")
        print("  已看 id 举例:", payload["watched"][:3])

        print("\n--- 重新打开页面（无 hash），应当自动恢复 ---")
        page.goto(url)
        print(json.dumps(page.eval(AFTER_RELOAD), ensure_ascii=False))

        with urllib.request.urlopen(url.rstrip("/") + "/anime-lists-data.json", timeout=10) as r:
            print("服务端回读存档:", r.read().decode("utf-8")[:80])
        return 0
    finally:
        if page:
            page.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
