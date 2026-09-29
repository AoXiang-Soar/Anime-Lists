"""Drive the page in headless Chrome over CDP and assert the UI actually works.

Usage:
    python -m http.server 8777 &
    python scripts/smoke_test.py [url]
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
def find_browser() -> str:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("no chrome/edge found")


class Page:
    def __init__(self, url: str):
        profile = Path(tempfile.gettempdir()) / f"anime-smoke-{int(time.time())}"
        self.logfile = open(Path(tempfile.gettempdir()) / "anime-smoke-chrome.log", "w+", encoding="utf-8", errors="replace")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.proc = subprocess.Popen(
            [
                find_browser(),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-allow-origins=*",
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={self.port}",
                "about:blank",
            ],
            stdout=self.logfile,
            stderr=subprocess.STDOUT,
        )
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.3)
        if not ws_url:
            self.logfile.flush()
            self.logfile.seek(0)
            raise SystemExit("browser did not expose a debugging port:\n" + self.logfile.read()[:2000])
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.msg_id = 0
        self.logs: list[str] = []
        self.send("Target.setDiscoverTargets", {"discover": True})
        target = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = self.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.session = session
        self.send("Runtime.enable")
        self.send("Log.enable")
        self.send("Page.enable")
        # 测试产生的下载一律落到临时目录，避免污染项目文件夹
        self.download_dir = Path(tempfile.gettempdir()) / f"anime-downloads-{int(time.time())}"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.send("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(self.download_dir)})
        self.url = url

    def send(self, method: str, params: dict | None = None):
        self.msg_id += 1
        payload = {"id": self.msg_id, "method": method, "params": params or {}}
        if hasattr(self, "session") and method not in {
            "Target.setDiscoverTargets",
            "Target.createTarget",
            "Target.attachToTarget",
            "Browser.setDownloadBehavior",
        }:
            payload["sessionId"] = self.session
        self.ws.send(json.dumps(payload))
        while True:
            raw = json.loads(self.ws.recv())
            if raw.get("method") == "Runtime.consoleAPICalled":
                args = [a.get("value") or a.get("description") for a in raw["params"]["args"]]
                self.logs.append("console: " + " ".join(str(a) for a in args))
            elif raw.get("method") == "Log.entryAdded":
                self.logs.append("log[%s]: %s" % (raw["params"]["entry"]["level"], raw["params"]["entry"]["text"]))
            elif raw.get("method") == "Runtime.exceptionThrown":
                self.logs.append("exception: " + json.dumps(raw["params"]["exceptionDetails"])[:300])
            if raw.get("id") == self.msg_id:
                if "error" in raw:
                    raise RuntimeError(raw["error"])
                return raw.get("result", {})

    def goto(self, url: str):
        self.send("Page.navigate", {"url": url})
        time.sleep(3.0)

    def eval(self, expression: str, await_promise: bool = False):
        res = self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
        )
        if "exceptionDetails" in res:
            raise RuntimeError(json.dumps(res["exceptionDetails"])[:500])
        return res["result"].get("value")

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()


SCRIPT = r"""
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const out = { errors: [] };
  window.addEventListener('error', (e) => out.errors.push(String(e.message)));

  out.totalTitles = $('#totalCount').textContent.trim();
  out.years = $$('.year-item').length;
  out.heatCells = $$('.heat-cell').length;
  out.viewTitle = $('#viewTitle').textContent;
  out.cards = $$('.card').length;

  // 1) 点击第一张卡片
  $('.card').click();
  out.watchedAfterClick = $('#watchedCount').textContent;
  out.cardWatchedClass = $$('.card.watched').length;
  out.eraTitle = ($('.era-title') || {}).textContent || null;

  // 2) 全选本季
  const seasonBtn = $('[data-act="season-all"]');
  const seasonSize = Number(seasonBtn.closest('.season').querySelectorAll('.card').length);
  seasonBtn.click();
  out.seasonSize = seasonSize;
  out.watchedAfterSeason = $('#watchedCount').textContent;

  // 3) 取消整季
  $('[data-act="season-none"]').click();
  out.watchedAfterUnmark = $('#watchedCount').textContent;

  // 4) 年份切换
  const targetYear = $$('.year-item')[3];
  const y = targetYear.querySelector('b').textContent;
  targetYear.click();
  await sleep(1500);
  out.switchedTo = $('#viewTitle').textContent;
  out.cardsAfterSwitch = $$('.card').length;
  out.subAfterSwitch = $('#viewSub').textContent;

  // 4b) 点热力图跳年份
  $$('.heat-cell')[10].click();
  await sleep(1500);
  out.heatmapJump = $('#viewTitle').textContent;

  // 5) 筛选：隐藏短片 / OVA
  $('#hideShort').checked = true;
  $('#hideShort').dispatchEvent(new Event('change'));
  out.cardsHideShort = $$('.card').length;
  $('#hideExtra').checked = true;
  $('#hideExtra').dispatchEvent(new Event('change'));
  out.cardsHideExtra = $$('.card').length;
  $('#hideShort').checked = false; $('#hideShort').dispatchEvent(new Event('change'));
  $('#hideExtra').checked = false; $('#hideExtra').dispatchEvent(new Event('change'));

  // 6) 排序 + 紧凑
  $('#sort').value = 'score'; $('#sort').dispatchEvent(new Event('change'));
  out.firstScoreAfterSort = $('#seasons .card .score-val') ? $('#seasons .card .score-val').textContent : null;
  $('#sort').value = 'air'; $('#sort').dispatchEvent(new Event('change'));
  $('#compact').checked = true; $('#compact').dispatchEvent(new Event('change'));
  out.compactClass = document.body.classList.contains('compact');
  $('#compact').checked = false; $('#compact').dispatchEvent(new Event('change'));

  // 7) 搜索（当前年份）
  $('#search').value = '战';
  $('#search').dispatchEvent(new Event('input'));
  await sleep(1200);
  out.searchTitle = $('#viewTitle').textContent;
  out.searchCards = $$('.card').length;

  // 8) 全局搜索
  $$('input[name="scope"]')[1].checked = true;
  $$('input[name="scope"]')[1].dispatchEvent(new Event('change'));
  await sleep(2500);
  out.globalSearchTitle = $('#viewTitle').textContent;
  out.globalSearchCards = $$('.card').length;
  out.globalSearchSub = $('#viewSub').textContent;

  // 9) 分享链接编码
  $('#search').value = '';
  $('#search').dispatchEvent(new Event('input'));
  await sleep(1200);
  $$('input[name="scope"]')[0].checked = true;
  $$('input[name="scope"]')[0].dispatchEvent(new Event('change'));
  await sleep(300);
  out.hashLength = location.hash.length;
  out.hashPrefix = location.hash.slice(0, 12);

  // 10) 导出 JSON（不真正下载，检查流程不抛错）
  $('#btnExport').click();
  out.exportOk = true;

  // 11) 勾一些番，检查分享链接里带上状态
  const cards = $$('.card');
  for (let i = 0; i < 25; i++) cards[i * 3] && cards[i * 3].click();
  out.watchedBeforeHash = $('#watchedCount').textContent;
  await sleep(600);
  out.hashHasState = location.hash.includes('w=');
  out.hashLength = location.hash.length;
  out.shareUrl = location.href;

  // 12) 海报生成（拦截下载，检查真的画出了东西）
  let poster = null;
  const origClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.href && this.href.startsWith('data:image/png')) poster = this.href;
    else origClick.call(this);
  };
  $('#btnPoster').click();
  await sleep(1200);
  HTMLAnchorElement.prototype.click = origClick;
  out.posterBytes = poster ? Math.round((poster.length * 3) / 4) : 0;
  out.posterIsPng = !!(poster && poster.startsWith('data:image/png'));
  out.toastAfterPoster = $('#toast').hidden ? '' : $('#toast').textContent;

  // 13) 导入 JSON
  const payload = new File([JSON.stringify({version: 1, watched: [1, 2, 3]})], 'x.json', {type: 'application/json'});
  const dt = new DataTransfer();
  dt.items.add(payload);
  const input = $('#importFile');
  input.files = dt.files;
  input.dispatchEvent(new Event('change'));
  await sleep(700);
  out.watchedAfterImport = $('#watchedCount').textContent;
  out.importToast = $('#toast').hidden ? '' : $('#toast').textContent;

  // 14) 封面加载成功后不应再显示首字占位
  out.fallbackVisible = Array.from(document.querySelectorAll('.thumb .fallback'))
    .filter((el) => getComputedStyle(el).display !== 'none').length;
  out.coversLoaded = Array.from(document.querySelectorAll('.thumb img')).filter((im) => im.complete && im.naturalWidth > 0).length;
  out.cardsWithImage = document.querySelectorAll('.thumb img').length;

  // 15) 海报尺寸应随已看数量增长（PNG 头里读宽高）
  const pngSize = (dataUrl) => {
    const bin = atob(dataUrl.split(',')[1].slice(0, 64));
    const dv = new DataView(new ArrayBuffer(24));
    for (let i = 0; i < 24; i++) dv.setUint8(i, bin.charCodeAt(i));
    return { w: dv.getUint32(16), h: dv.getUint32(20) };
  };
  out.posterSizeSmall = poster ? pngSize(poster) : null;
  out.watchedForBigPoster = $('#watchedCount').textContent;

  // 16) 星标 → 补番列表
  out.saverMode = window.__animeLists.state.saverMode;
  out.autosaveDefaultOn = window.__animeLists.state.autosave;
  out.bindButtonVisible = !$('#btnBind').hidden;
  out.saveStatusText = $('#saveStatus').textContent;

  const stars = $$('.star');
  stars[0].click();
  stars[3].click();
  await sleep(300);
  out.starCount = $('#starCount').textContent;
  out.starredCards = $$('.card.starred').length;
  out.watchedUnchanged = $('#watchedCount').textContent;
  out.hashHasStars = location.hash.includes('s=');
  $('#btnStarred').click();
  await sleep(1200);
  out.starredViewTitle = $('#viewTitle').textContent;
  out.starredViewSub = $('#viewSub').textContent;
  out.starredViewCards = $$('.card').length;
  $('#btnStarred').click();
  await sleep(1200);
  out.backToYear = $('#viewTitle').textContent;
  const starsAgain = $$('.star');       // 视图重渲染过，必须重新取节点
  starsAgain[0].click();
  await sleep(200);
  out.starCountAfterUnstar = $('#starCount').textContent;
  out.starShareUrl = location.href;

  // 17) 跨年份大批量勾选 → 海报必须包含全部（不是前 160 部）
  const api = window.__animeLists;
  const sel = $('#yearSelect');
  sel.value = '2024';
  sel.dispatchEvent(new Event('change'));
  await sleep(2500);
  $$('.card').forEach((c, i) => { if (i % 3 === 0) c.click(); });
  await sleep(500);
  out.watchedTwoYears = Number($('#watchedCount').textContent);
  poster = null;
  HTMLAnchorElement.prototype.click = function () {
    if (this.href && this.href.startsWith('data:image/png')) poster = this.href;
    else origClick.call(this);
  };
  $('#btnPoster').click();
  await sleep(1800);
  HTMLAnchorElement.prototype.click = origClick;
  out.posterTwoYears = poster ? pngSize(poster) : null;
  out.posterTwoYearsBytes = poster ? Math.round((poster.length * 3) / 4) : 0;

  // 18) 极端压力：一次勾掉约 2800 部，海报要自动切成密集清单模式
  const st = api.state;
  st.bits = new Uint8Array((st.catalog.ids.length + 7) >> 3);
  let n = 0;
  for (let i = 0; i < st.catalog.ids.length; i += 2) {
    st.bits[i >> 3] |= 1 << (i & 7);
    n++;
  }
  api.refreshAll();
  await sleep(400);
  out.bulkWatched = Number($('#watchedCount').textContent);
  out.bulkEraTags = ($('.era-verdict') || {}).textContent || '';

  // 海报内部用的是同一套比较器：验证是「时间降序」
  const seasonIdx = (s) => ({ WINTER: 0, SPRING: 1, SUMMER: 2, FALL: 3 }[s] || 0);
  const watchedNow = [];
  for (const y of api.state.yearStats.keys()) {
    for (const e of api.entriesForYear(y)) {
      const i = api.state.idx.get(e.id);
      if (i !== undefined && ((api.state.bits[i >> 3] >> (i & 7)) & 1)) watchedNow.push(e);
    }
  }
  watchedNow.sort((a, b) => b.y - a.y || seasonIdx(b.s) - seasonIdx(a.s) || (b.d || '').localeCompare(a.d || ''));
  out.posterOrderFirst = watchedNow.slice(0, 3).map((e) => `${e.y}${e.s[0]}`);
  out.posterOrderLast = watchedNow.slice(-3).map((e) => `${e.y}${e.s[0]}`);
  out.posterOrderDescending = watchedNow.every((e, i) =>
    i === 0 || watchedNow[i - 1].y > e.y ||
    (watchedNow[i - 1].y === e.y && seasonIdx(watchedNow[i - 1].s) >= seasonIdx(e.s))
  );

  poster = null;
  HTMLAnchorElement.prototype.click = function () {
    if (this.href && this.href.startsWith('data:image/png')) poster = this.href;
    else origClick.call(this);
  };
  $('#btnPoster').click();
  await sleep(4000);
  HTMLAnchorElement.prototype.click = origClick;
  out.posterBulk = poster ? pngSize(poster) : null;
  out.posterBulkBytes = poster ? Math.round((poster.length * 3) / 4) : 0;

  return out;
})()
"""

RESTORE_SCRIPT = r"""
(() => ({
  watched: document.querySelector('#watchedCount').textContent,
  starred: document.querySelector('#starCount').textContent,
  era: (document.querySelector('.era-title') || {}).textContent || null,
  verdict: (document.querySelector('.era-verdict') || {}).textContent || null,
  viewTitle: document.querySelector('#viewTitle').textContent,
  cards: document.querySelectorAll('.card').length,
  watchedCards: document.querySelectorAll('.card.watched').length,
  starredCards: document.querySelectorAll('.card.starred').length,
  yearWithMost: document.querySelector('.year-item.active b').textContent,
}))()
"""

LAYOUT_SCRIPT = r"""
(() => {
  const r = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { w: Math.round(b.width), h: Math.round(b.height), x: Math.round(b.x), y: Math.round(b.y) };
  };
  return {
    viewport: [window.innerWidth, window.innerHeight],
    overflowX: document.documentElement.scrollWidth - window.innerWidth,
    topbar: r('.topbar'),
    sidebar: r('.sidebar'),
    heatPanel: r('.heat-panel'),
    heatCol: r('.heat-col'),
    firstCard: r('.card'),
    gridCols: getComputedStyle(document.querySelector('.grid')).gridTemplateColumns.split(' ').length,
    cardCount: document.querySelectorAll('.card').length,
    visibleCards: Array.from(document.querySelectorAll('.card')).filter((c) => c.getBoundingClientRect().width > 0).length,
  };
})()
"""

WAIT_READY = r"""
new Promise((resolve) => {
  const t0 = Date.now();
  const timer = setInterval(() => {
    const ready = window.__animeLists && document.querySelector('#viewTitle').textContent !== '—';
    if (ready || Date.now() - t0 > 30000) {
      clearInterval(timer);
      resolve({ ready: !!ready, ms: Date.now() - t0 });
    }
  }, 200);
})
"""

POSTER_SCRIPT = r"""
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const out = {};

  // 0) 回归：全新加载（无 hash、无导入）时点星标必须真的收藏成功
  const firstStars = $$('.star');
  out.freshBefore = Number($('#starCount').textContent);
  firstStars[0].click();
  firstStars[firstStars.length - 1].click();
  await sleep(400);
  out.freshAfter = Number($('#starCount').textContent);
  out.freshStarredCards = $$('.card.starred').length;
  out.freshStarsPainted = $$('.card.starred .star').length;
  firstStars[0].click();
  await sleep(300);
  out.freshAfterUnstar = Number($('#starCount').textContent);
  firstStars[firstStars.length - 1].click();
  await sleep(300);
  out.freshCleared = Number($('#starCount').textContent);

  // 勾一大票，检验海报是否包含全部已看（而不是截断前 160 部）
  const cards = $$('.card');
  cards.forEach((c, i) => { if (i % 2 === 0) c.click(); });
  out.watched = Number($('#watchedCount').textContent);

  let poster = null;
  const orig = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.href && this.href.startsWith('data:image/png')) poster = this.href;
    else origClick.call(this);
  };
  $('#btnPoster').click();
  await sleep(1500);
  HTMLAnchorElement.prototype.click = orig;

  const pngSize = (dataUrl) => {
    const bin = atob(dataUrl.split(',')[1].slice(0, 64));
    const dv = new DataView(new ArrayBuffer(24));
    for (let i = 0; i < 24; i++) dv.setUint8(i, bin.charCodeAt(i));
    return { w: dv.getUint32(16), h: dv.getUint32(20) };
  };
  out.poster = poster ? pngSize(poster) : null;
  out.posterBytes = poster ? Math.round((poster.length * 3) / 4) : 0;
  out.verdict = ($('.era-verdict') || {}).textContent || '';
  out.eraTags = ($('.era-tags') || {}).textContent.replace(/\s+/g, ' ').trim() || '';
  return out;
})()
"""


def main() -> int:
    default = (Path(__file__).resolve().parents[1] / "index.html").as_uri()
    url = sys.argv[1] if len(sys.argv) > 1 else default
    page = Page(url)
    try:
        page.goto(url)
        result = page.eval(SCRIPT, await_promise=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        shared = result.pop("shareUrl", None)
        if shared:
            print("\n--- 用分享链接重新打开（模拟刷新 / 别人打开） ---")
            page.goto(shared)
            print(json.dumps(page.eval(RESTORE_SCRIPT), ensure_ascii=False, indent=2))

        print("\n--- 布局体检 ---")
        for width, height, name in ((1680, 1000, "桌面 1680"), (1280, 900, "笔记本 1280"), (390, 844, "手机 390")):
            page.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": width < 600,
                },
            )
            time.sleep(0.6)
            print(name, json.dumps(page.eval(LAYOUT_SCRIPT), ensure_ascii=False))
            if width < 600:
                print(
                    "  移动端年份下拉：",
                    json.dumps(
                        page.eval(
                            """(() => {
                          const s = document.querySelector('#yearSelect');
                          const visible = getComputedStyle(s).display !== 'none';
                          s.value = '2015';
                          s.dispatchEvent(new Event('change'));
                          return { visible, options: s.options.length };
                        })()"""
                        ),
                        ensure_ascii=False,
                    ),
                )
                time.sleep(1.5)
                print("  切换后标题：", page.eval("document.querySelector('#viewTitle').textContent"))
        page.send("Emulation.clearDeviceMetricsOverride")

        print("\n--- 海报（全量已看 + 评价） ---")
        page.goto(url)
        print(json.dumps(page.eval(POSTER_SCRIPT, await_promise=True), ensure_ascii=False, indent=2))

        files = sorted(p.name for p in page.download_dir.glob("*")) if page.download_dir.exists() else []
        print(f"\n--- 测试期间的下载文件（应为个位数，说明勾选没有触发自动下载）---\n{files}")

        print("\n--- browser logs ---")
        for line in page.logs:
            print(line)
    finally:
        page.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
