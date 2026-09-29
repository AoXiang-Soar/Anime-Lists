"""Force the online-update path and report what it actually did.

Usage: python scripts/test_update.py [url]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import Page  # noqa: E402

SCRIPT = r"""
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const api = window.__animeLists;
  const out = {};
  if (!api) return { error: 'debug hook missing' };

  out.before = {
    watched: document.querySelector('#watchedCount').textContent,
    total: api.state.catalog.ids.length,
    date: document.querySelector('#dataDate').textContent,
    ageDays: Math.round(api.dataAgeDays()),
  };

  // 假装本地缓存已经很旧，触发自动更新逻辑
  api.state.manifest.generatedAt -= 70 * 86400;
  out.ageAfterFake = Math.round(api.dataAgeDays());
  out.seasonsToRefresh = api.state ? undefined : undefined;

  const t0 = Date.now();
  await api.updateOnline(false);
  out.elapsedSec = Math.round((Date.now() - t0) / 1000);
  out.note = document.querySelector('#btnUpdate').title;
  out.refreshedSeasons = Array.from(api.state.seasonUpdates.keys());
  out.after = {
    total: api.state.catalog.ids.length,
    buttonText: document.querySelector('#btnUpdate').textContent,
  };

  // 受刷新影响的那一年，条目数量对不对
  const key = out.refreshedSeasons[out.refreshedSeasons.length - 1];
  if (key) {
    const [year] = key.split('-');
    out.sampleSeason = { key, entries: api.state.seasonUpdates.get(key).length };
    const el = document.querySelector(`.year-item[data-year="${year}"]`);
    out.yearRowText = el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
  }
  out.freshEntries = Array.from(api.state.seasonUpdates.values())
    .flat()
    .slice(0, 3)
    .map((e) => ({ zh: e.t.zh, romaji: e.t.romaji, y: e.y, s: e.s, ep: e.ep, cov: !!e.cov }));
  return out;
})()
"""


def main() -> int:
    default = (Path(__file__).resolve().parents[1] / "index.html").as_uri()
    url = sys.argv[1] if len(sys.argv) > 1 else default
    page = Page(url)
    page.ws.settimeout(300)
    try:
        page.goto(url)
        # 等首屏与后台预取安稳
        page.eval("new Promise(r=>setTimeout(()=>r(1),1500))", await_promise=True)
        result = page.eval(SCRIPT, await_promise=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\n--- browser logs ---")
        for line in page.logs:
            print(line)
    finally:
        page.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
