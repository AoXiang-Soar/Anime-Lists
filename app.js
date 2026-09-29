/* 番剧年表 — 纯静态、无本地存储的追番勾选表。
 * 勾选状态全部编码在 URL hash 里（可分享/可收藏），不用 localStorage。 */
(() => {
  "use strict";

  const SEASONS = ["WINTER", "SPRING", "SUMMER", "FALL"];
  const SEASON_LABEL = ["冬番", "春番", "夏番", "秋番"];
  const SEASON_MONTHS = ["1-3 月", "4-6 月", "7-9 月", "10-12 月"];
  const SEASON_FIRST_MONTH = { WINTER: 1, SPRING: 4, SUMMER: 7, FALL: 10 };
  const FORMAT_LABEL = { TV: "TV", TV_SHORT: "短片", ONA: "网络", OVA: "OVA", SPECIAL: "SP" };
  const KIND_ORDER = ["e", "a", "s", "x", "l"]; // ecchi / adult / short / extra / long_run
  const CACHE_TTL_DAYS = 30;                   // 缓存不到一个月就直接用，不联网
  const MIN_EPISODES = 9;                      // 只收 > 8 集
  const AIRING_STATUSES = ["RELEASING", "NOT_YET_RELEASED"];
  const BANGUMI_URL = "https://cdn.jsdelivr.net/npm/bangumi-data@0.3.228/dist/data.json";

  const ERAS = [
    { from: 1990, to: 1994, name: "OVA 黄金黎明", desc: "录像带时代的浪漫，作画豪放、题材狂野。" },
    { from: 1995, to: 1999, name: "EVA 冲击世代", desc: "世纪末的青春期，赛博与宗教意象齐飞。" },
    { from: 2000, to: 2004, name: "深夜档黎明", desc: "深夜动画成形，实验性与萌系同时发芽。" },
    { from: 2005, to: 2009, name: "萌系爆发世代", desc: "轻改前夜，四格与日常系开始统治档期。" },
    { from: 2010, to: 2014, name: "轻改盛世", desc: "每季都能扒出一堆现象级作品的黄金期。" },
    { from: 2015, to: 2019, name: "异世界元年", desc: "穿越与异世界井喷，配信平台改写了追番节奏。" },
    { from: 2020, to: 2024, name: "流媒体世代", desc: "全球同步配信，作画与企划规模全面升级。" },
    { from: 2025, to: 2030, name: "最新世代", desc: "正在进行的这一季，就是你当下的青春。" },
  ];

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // 与 scripts/build_data.py 里的 SEARCH_DROP 保持一致
  const SEARCH_DROP = " \u3000·・,，、.。:：;；!！?？'\"“”‘’`-–—_/\\|()（）[]【】「」『』<>《》&×～~+＋*#^";
  const DROP_RE = new RegExp("[" + SEARCH_DROP.replace(/[\\\]^\-]/g, (c) => "\\" + c) + "]", "g");
  const norm = (s) => String(s || "").toLowerCase().replace(DROP_RE, "");

  const state = {
    manifest: null,
    catalog: null,
    idx: new Map(),
    bits: new Uint8Array(1),
    starBits: new Uint8Array(1),
    yearStats: new Map(),
    seasonStats: new Map(),
    watched: 0,
    starred: 0,
    year: null,
    view: "year",
    searchQuery: "",
    scope: "year",
    formats: new Set([0, 1, 2, 3, 4]),
    searchIndex: null,
    hideShort: false,
    hideExtra: false,
    hideLong: false,
    hideEcchi: false,
    sort: "air",
    onlyWatched: false,
    onlyStarred: false,
    cache: new Map(),
    seasonUpdates: new Map(), // "2026-WINTER" -> 在线拉到的最新整季列表（覆盖本地）
    searchMatches: null,
    updating: false,
    updateNote: "",
    autosave: true,
    saverMode: "download", // server | handle | prompt | download
    saveNote: "",
    saveHandle: null,
    savedAt: 0,
  };

  const seasonKey = (year, season) => `${year}-${season}`;

  /* ------------------------------------------------------------------ state */

  const watchedAt = (i) => (state.bits[i >> 3] >> (i & 7)) & 1;
  const starredAt = (i) => (state.starBits[i >> 3] >> (i & 7)) & 1;

  /** 位图必须覆盖整个 catalog；在线更新会追加条目，所以每次写之前都要确认容量。 */
  function ensureBitCapacity() {
    const need = (state.catalog.ids.length + 7) >> 3;
    if (state.bits.length >= need && state.starBits.length >= need) return;
    if (state.bits.length < need) {
      const next = new Uint8Array(need);
      next.set(state.bits);
      state.bits = next;
    }
    if (state.starBits.length < need) {
      const next = new Uint8Array(need);
      next.set(state.starBits);
      state.starBits = next;
    }
  }

  function setWatched(i, on) {
    if (i >> 3 >= state.bits.length) ensureBitCapacity();
    const byte = i >> 3;
    const mask = 1 << (i & 7);
    if (on) state.bits[byte] |= mask;
    else state.bits[byte] &= ~mask;
  }
  function setStarred(i, on) {
    if (i >> 3 >= state.starBits.length) ensureBitCapacity();
    const byte = i >> 3;
    const mask = 1 << (i & 7);
    if (on) state.starBits[byte] |= mask;
    else state.starBits[byte] &= ~mask;
  }
  const bitCount = (bytes, n) => {
    let n0 = 0;
    for (let i = 0; i < n; i++) if ((bytes[i >> 3] >> (i & 7)) & 1) n0++;
    return n0;
  };

  const b64url = (bytes) => {
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };
  const fromB64url = (str) => {
    const pad = str.replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(pad + "===".slice((pad.length + 3) % 4));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  };

  function readHash() {
    const raw = location.hash.replace(/^#/, "");
    if (!raw) return {};
    const params = new URLSearchParams(raw);
    const out = {};
    const y = parseInt(params.get("y") || "", 10);
    if (y) out.year = y;
    const w = params.get("w");
    if (w) {
      try {
        const bytes = fromB64url(w);
        const need = (state.catalog.ids.length + 7) >> 3;
        state.bits = new Uint8Array(need);
        state.bits.set(bytes.subarray(0, need));
      } catch (err) {
        console.warn("分享链接解析失败", err);
      }
    }
    const star = params.get("s");
    if (star) {
      try {
        const bytes = fromB64url(star);
        const need = (state.catalog.ids.length + 7) >> 3;
        state.starBits = new Uint8Array(need);
        state.starBits.set(bytes.subarray(0, need));
      } catch (err) {
        console.warn("补番列表解析失败", err);
      }
    }
    ensureBitCapacity();
    return out;
  }

  let hashTimer = 0;
  function writeHash() {
    clearTimeout(hashTimer);
    hashTimer = setTimeout(() => {
      const params = new URLSearchParams();
      if (state.year) params.set("y", String(state.year));
      if (state.watched > 0) params.set("w", b64url(state.bits));
      if (state.starred > 0) params.set("s", b64url(state.starBits));
      const next = params.toString();
      try {
        history.replaceState(null, "", next ? "#" + next : location.pathname + location.search);
      } catch (err) {
        // file:// 下 Chrome 不允许 replaceState，退回直接改 hash（页面不会重载）
        if (location.hash !== (next ? "#" + next : "")) location.hash = next;
      }
    }, 260);
  }

  function recomputeStats() {
    state.watched = 0;
    state.starred = 0;
    state.yearStats = new Map();
    state.seasonStats = new Map();
    const { years, seasons } = state.catalog;
    for (let i = 0; i < years.length; i++) {
      if (starredAt(i)) state.starred++;
      if (!watchedAt(i)) continue;
      state.watched++;
      const y = years[i];
      state.yearStats.set(y, (state.yearStats.get(y) || 0) + 1);
      const key = y * 4 + Number(seasons[i]);
      state.seasonStats.set(key, (state.seasonStats.get(key) || 0) + 1);
    }
  }

  /* ------------------------------------------------------------- data access */

  // 数据全部通过 <script> 注入（而不是 fetch），这样 file:// 直接双击打开也能用。
  const inflight = new Map();
  function injectScript(src) {
    if (inflight.has(src)) return inflight.get(src);
    const promise = new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = src;
      el.async = true;
      el.onload = () => resolve();
      el.onerror = () => reject(new Error(`无法加载 ${src}`));
      document.head.appendChild(el);
    });
    inflight.set(src, promise);
    return promise;
  }

  async function loadYear(year) {
    if (state.cache.has(year)) return state.cache.get(year);
    await injectScript(`data/${year}.js`);
    const data = (window.ANIME_DATA && window.ANIME_DATA[year]) || [];
    state.cache.set(year, data);
    return data;
  }

  let searchPromise = null;
  function ensureSearchIndex() {
    if (!searchPromise) {
      searchPromise = injectScript("data/search.js")
        .then(() => {
          state.searchIndex = window.ANIME_SEARCH || [];
          return state.searchIndex;
        })
        .catch((err) => {
          console.warn("搜索索引载入失败", err);
          state.searchIndex = [];
          return [];
        });
    }
    return searchPromise;
  }

  /* --------------------------------------------------- 在线更新（可选功能） */

  /* ----------------------------------------------- 本地自动保存（默认开启） */

  const AUTOSAVE_FILE = "anime-lists-data.json";
  const AUTOSAVE_KEY = "animeLists.autosave";
  const HANDLE_DB = "animeLists";
  const HANDLE_STORE = "kv";

  function readSetting(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : v;
    } catch (err) {
      return fallback;
    }
  }
  function writeSetting(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (err) {
      /* file:// 或隐私模式下可能不可用，忽略即可 */
    }
  }

  function idb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(HANDLE_DB, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(HANDLE_STORE)) req.result.createObjectStore(HANDLE_STORE);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function idbGet(key) {
    try {
      const db = await idb();
      return await new Promise((resolve, reject) => {
        const req = db.transaction(HANDLE_STORE, "readonly").objectStore(HANDLE_STORE).get(key);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    } catch (err) {
      return null;
    }
  }
  async function idbSet(key, value) {
    try {
      const db = await idb();
      await new Promise((resolve, reject) => {
        const tx = db.transaction(HANDLE_STORE, "readwrite");
        tx.objectStore(HANDLE_STORE).put(value, key);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
      });
    } catch (err) {
      /* 存不下句柄就算了，下次再让用户绑一次 */
    }
  }

  function payload() {
    const watched = [];
    const starred = [];
    for (let i = 0; i < state.catalog.ids.length; i++) {
      if (watchedAt(i)) watched.push(state.catalog.ids[i]);
      if (starredAt(i)) starred.push(state.catalog.ids[i]);
    }
    return { version: 2, exportedAt: new Date().toISOString(), watched, starred };
  }

  /** 探测可用的保存方式：exe 内置服务 > 已授权的本地文件 > 让用户挑一个文件 > 浏览器下载 */
  async function detectSaver() {
    state.autosave = readSetting(AUTOSAVE_KEY, "1") !== "0";
    if (window.ANIME_LISTS_SERVER && window.ANIME_LISTS_SERVER.savePath) {
      state.saverMode = "server";
      state.saveNote = `自动保存到 ${window.ANIME_LISTS_SERVER.savePath}`;
      return;
    }
    const handle = await idbGet("saveHandle");
    if (handle) {
      state.saveHandle = handle;
      let perm = "prompt";
      try {
        perm = await handle.queryPermission({ mode: "readwrite" });
      } catch (err) {
        perm = "prompt";
      }
      state.saverMode = perm === "granted" ? "handle" : "prompt";
      state.saveNote = perm === "granted" ? `自动保存到 ${handle.name}` : `点一下恢复自动保存（${handle.name}）`;
      return;
    }
    if (typeof window.showSaveFilePicker === "function") {
      state.saverMode = "prompt";
      state.saveNote = "点一下选择保存文件";
      return;
    }
    state.saverMode = "download";
    state.saveNote = "当前浏览器不支持静默保存，将改为下载";
  }

  async function bindSaveFile() {
    try {
      if (state.saveHandle && state.saverMode === "prompt") {
        const perm = await state.saveHandle.requestPermission({ mode: "readwrite" });
        if (perm === "granted") {
          state.saverMode = "handle";
          state.saveNote = `自动保存到 ${state.saveHandle.name}`;
          renderSaveStatus();
          await saveNow({ silent: false });
          return;
        }
      }
      const handle = await window.showSaveFilePicker({
        suggestedName: AUTOSAVE_FILE,
        types: [{ description: "番剧年表数据", accept: { "application/json": [".json"] } }],
      });
      state.saveHandle = handle;
      state.saverMode = "handle";
      state.saveNote = `自动保存到 ${handle.name}`;
      await idbSet("saveHandle", handle);
      renderSaveStatus();
      await saveNow({ silent: false });
    } catch (err) {
      if (err && err.name === "AbortError") return;
      toast("绑定保存文件失败：" + (err.message || err.name));
    }
  }

  async function saveNow({ silent = true, name = AUTOSAVE_FILE, text = null } = {}) {
    const body = text === null ? JSON.stringify(payload(), null, 1) : text;
    try {
      if (state.saverMode === "server") {
        const res = await fetch("__save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, text: body }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const info = await res.json();
        state.savedAt = Date.now();
        state.saveNote = `已保存到 ${info.path}`;
        renderSaveStatus();
        if (!silent) toast("已保存到 " + info.path);
        return true;
      }
      if (state.saverMode === "handle" && state.saveHandle) {
        const writable = await state.saveHandle.createWritable();
        await writable.write(body);
        await writable.close();
        state.savedAt = Date.now();
        state.saveNote = `已保存到 ${state.saveHandle.name}`;
        renderSaveStatus();
        if (!silent) toast("已保存到 " + state.saveHandle.name);
        return true;
      }
    } catch (err) {
      console.warn("保存失败", err);
      state.saveNote = "保存失败：" + (err.message || err.name);
      renderSaveStatus();
      if (!silent) toast("保存失败：" + (err.message || err.name));
      return false;
    }
    downloadText(name, body);
    state.saveNote = "已通过浏览器下载保存（可在下载文件夹找到）";
    renderSaveStatus();
    if (!silent) toast("已下载：" + name);
    return true;
  }

  function downloadText(name, text) {
    const blob = new Blob([text], { type: "application/json" });
    downloadBlob(name, blob);
  }

  function downloadBlob(name, blob) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  let autosaveTimer = 0;
  function scheduleAutosave() {
    if (!state.autosave) return;
    // 没绑定真实目标（既不是 exe 服务端，也没有文件句柄）时不偷偷下载文件，
    // 只提示用户去点「选择保存文件」。
    if (state.saverMode !== "server" && state.saverMode !== "handle") {
      state.saveNote = state.saverMode === "prompt" ? "点一下「选择保存文件」才会开始自动保存" : state.saveNote;
      renderSaveStatus();
      return;
    }
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => saveNow({ silent: true }), 800);
  }

  async function loadSavedState() {
    if (location.hash.includes("w=") || location.hash.includes("s=")) return false; // 分享链接优先
    let text = null;
    try {
      if (state.saverMode === "server") {
        // 同目录下可能有用户导出的 anime-lists-2026-09-29.json 之类，取最新的那份
        let name = AUTOSAVE_FILE;
        try {
          const listing = await fetchJSON("__listing", null, 8000);
          const newest = listing && listing.files && listing.files[0];
          if (newest && newest.name) name = newest.name;
        } catch (err) {
          /* 没有列表接口就用默认文件名 */
        }
        let res = await fetch(name, { cache: "no-store" });
        if (!res.ok && name !== AUTOSAVE_FILE) res = await fetch(AUTOSAVE_FILE, { cache: "no-store" });
        if (res.ok) text = await res.text();
      } else if (state.saverMode === "handle" && state.saveHandle) {
        const file = await state.saveHandle.getFile();
        text = await file.text();
      }
    } catch (err) {
      console.warn("读取本地存档失败", err);
    }
    if (!text) return false;
    try {
      const data = JSON.parse(text);
      const ids = data.watched || [];
      const stars = data.starred || [];
      state.bits = new Uint8Array((state.catalog.ids.length + 7) >> 3);
      state.starBits = new Uint8Array((state.catalog.ids.length + 7) >> 3);
      for (const id of ids) {
        const i = state.idx.get(Number(id));
        if (i !== undefined) setWatched(i, true);
      }
      for (const id of stars) {
        const i = state.idx.get(Number(id));
        if (i !== undefined) setStarred(i, true);
      }
      return true;
    } catch (err) {
      console.warn("本地存档解析失败", err);
      return false;
    }
  }

  const ADULT_KEEP = new Set([1060]); // 与 scripts/build_data.py 保持一致
  const UPDATE_QUERY = `query ($year: Int, $season: MediaSeason, $page: Int, $perPage: Int) {
    Page(page: $page, perPage: $perPage) {
      pageInfo { hasNextPage }
      media(type: ANIME, seasonYear: $year, season: $season,
            format_in: [TV, TV_SHORT, ONA, OVA, SPECIAL], genre_not_in: ["Hentai"]) {
        id idMal title { romaji english native } format status episodes duration
        season seasonYear startDate { year month day } endDate { year month day }
        genres isAdult averageScore popularity favourites source countryOfOrigin
        coverImage { large extraLarge color } studios(isMain: true) { nodes { name } }
      }
    }
  }`;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function dataAgeDays() {
    const stamp = state.manifest && state.manifest.generatedAt;
    if (!stamp) return Infinity;
    return (Date.now() / 1000 - stamp) / 86400;
  }

  const seasonFromMonth = (month) =>
    month >= 1 && month <= 3 ? "WINTER" : month <= 6 ? "SPRING" : month <= 9 ? "SUMMER" : month <= 12 ? "FALL" : "";

  function seasonsToRefresh() {
    const buildTs = (state.manifest.generatedAt || Date.now() / 1000) * 1000;
    const fromTs = Math.min(buildTs, Date.now()) - 45 * 864e5;
    const now = new Date();
    const out = [];
    for (let y = new Date(fromTs).getFullYear(); y <= now.getFullYear(); y++) {
      for (const s of SEASONS) {
        const start = new Date(y, SEASON_FIRST_MONTH[s] - 1, 1);
        const end = new Date(y, SEASON_FIRST_MONTH[s] + 2, 1);
        if (end <= fromTs || start > now) continue;
        out.push({ year: y, season: s });
      }
    }
    return out.slice(-8);
  }

  async function fetchJSON(url, body, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        method: body ? "POST" : "GET",
        headers: body ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
        body: body ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function fetchSeason(year, season) {
    const out = [];
    let page = 1;
    for (;;) {
      const json = await fetchJSON(
        "https://graphql.anilist.co",
        { query: UPDATE_QUERY, variables: { year, season, page, perPage: 50 } },
        20000
      );
      if (json.errors) throw new Error(json.errors[0].message);
      const data = json.data.Page;
      out.push(...data.media);
      if (!data.pageInfo.hasNextPage) break;
      page += 1;
      await sleep(1100); // 尊重 AniList 的限流
    }
    return out;
  }

  // 和 build_data.py 的过滤规则保持一致
  function eligibleOnline(m) {
    if (!m) return false;
    if (m.countryOfOrigin && m.countryOfOrigin !== "JP") return false;
    if (AIRING_STATUSES.includes(m.status)) return false;
    if ((m.episodes || 0) < MIN_EPISODES) return false;
    const genres = m.genres || [];
    if (genres.includes("Hentai")) return false;
    if (m.isAdult && !ADULT_KEEP.has(m.id)) {
      if (m.format !== "TV" || (m.duration || 0) < 20 || (m.episodes || 0) < 9) return false;
    }
    return true;
  }

  const isoOf = (d) => (d && d.year ? `${d.year}-${String(d.month || 1).padStart(2, "0")}-${String(d.day || 1).padStart(2, "0")}` : "");

  function toEntry(m, zhMap) {
    const t = m.title || {};
    const start = m.startDate || {};
    const genres = m.genres || [];
    const nodes = (m.studios && m.studios.nodes) || [];
    const cover = m.coverImage || {};
    const zh = (zhMap && zhMap.get(m.id)) || [];
    const flags = [];
    if (genres.includes("Ecchi")) flags.push("ecchi");
    if (m.isAdult) flags.push("adult");
    if (m.format === "TV_SHORT" || (m.duration && m.duration < 15)) flags.push("short");
    if (m.format === "OVA" || m.format === "SPECIAL") flags.push("extra");
    if ((m.episodes || 0) >= 45) flags.push("long_run");
    return {
      id: m.id,
      t: {
        zh: zh[0] || "",
        zhAlt: zh.slice(1),
        romaji: t.romaji || t.english || t.native || "",
        en: t.english || "",
        native: t.native || "",
      },
      f: m.format || "TV",
      ep: m.episodes || 0,
      du: m.duration || 0,
      y: m.seasonYear || start.year,
      s: m.season || seasonFromMonth(start.month) || "WINTER",
      d: isoOf(start),
      e: isoOf(m.endDate),
      g: genres,
      k: flags,
      sc: m.averageScore || 0,
      po: m.popularity || 0,
      fa: m.favourites || 0,
      cov: cover.large || cover.extraLarge || "",
      col: cover.color || "",
      stu: nodes[0] ? nodes[0].name : "",
      src: (m.source || "").replace(/_/g, " "),
      mal: m.idMal || 0,
      bgm: 0,
    };
  }

  async function tryBangumiMap() {
    try {
      const data = await fetchJSON(BANGUMI_URL, null, 15000);
      const map = new Map();
      for (const item of data.items || []) {
        const site = (item.sites || []).find((s) => s.site === "aniList" && s.id);
        if (!site) continue;
        const zh = (item.titleTranslate && item.titleTranslate["zh-Hans"]) || [];
        if (zh.length) map.set(Number(site.id), zh);
      }
      return map;
    } catch (err) {
      console.warn("bangumi 中文名拉取失败，本次更新不含中文名", err);
      return null;
    }
  }

  function catalogAppend(entry) {
    const c = state.catalog;
    const i = c.ids.length;
    c.ids.push(entry.id);
    c.years.push(entry.y);
    c.seasons += String(SEASONS.indexOf(entry.s));
    c.fmts += String(Math.max(0, c.formats.indexOf(entry.f)));
    c.eps.push(entry.ep);
    c.dur.push(entry.du);
    c.gmask.push(genreMaskFor(entry.g));
    c.kinds += [["e", "ecchi"], ["a", "adult"], ["s", "short"], ["x", "extra"], ["l", "long_run"]]
      .map(([ch, name]) => (entry.k.indexOf(name) >= 0 ? ch : "-"))
      .join("");
    if (Array.isArray(state.searchIndex)) state.searchIndex.push(searchKeyOf(entry));
    state.idx.set(entry.id, i);
    ensureBitCapacity(); // 新增条目后位图要跟着长
    return i;
  }

  function catalogUpdate(i, entry) {
    const c = state.catalog;
    c.eps[i] = entry.ep;
    c.dur[i] = entry.du;
    c.gmask[i] = genreMaskFor(entry.g);
  }

  function genreMaskFor(genres) {
    let mask = 0;
    for (const g of genres || []) {
      let bit = state.catalog.genres.indexOf(g);
      if (bit < 0) {
        state.catalog.genres.push(g);
        bit = state.catalog.genres.length - 1;
      }
      mask |= 1 << bit;
    }
    return mask;
  }

  function searchKeyOf(entry) {
    return [entry.t.zh, ...(entry.t.zhAlt || []), entry.t.romaji, entry.t.en, entry.t.native]
      .filter(Boolean)
      .join("")
      .toLowerCase()
      .replace(DROP_RE, "");
  }

  function mergeSeasonUpdate(year, season, entries) {
    let added = 0;
    for (const e of entries) {
      const i = state.idx.get(e.id);
      if (i === undefined) {
        catalogAppend(e);
        added += 1;
      } else {
        catalogUpdate(i, e);
      }
    }
    state.seasonUpdates.set(seasonKey(year, season), entries);
    return added;
  }

  function ensureYearInManifest(year) {
    if (state.manifest.years.some((m) => m.year === year)) return;
    state.manifest.years.push({ year, count: 0, seasons: {}, withZh: 0 });
    state.manifest.years.sort((a, b) => a.year - b.year);
  }

  function seasonCountOf(year, season) {
    const key = seasonKey(year, season);
    if (state.seasonUpdates.has(key)) return state.seasonUpdates.get(key).length;
    const info = state.manifest.years.find((m) => m.year === year);
    return info && info.seasons ? info.seasons[season] || 0 : 0;
  }

  const yearCountOf = (year) => SEASONS.reduce((n, s) => n + seasonCountOf(year, s), 0);

  function entriesForYear(year) {
    const base = state.cache.get(year) || [];
    const out = [];
    for (const e of base) if (!state.seasonUpdates.has(seasonKey(year, e.s))) out.push(e);
    for (const s of SEASONS) {
      const list = state.seasonUpdates.get(seasonKey(year, s));
      if (list) out.push(...list);
    }
    return out;
  }

  function renderDataStatus() {
    const stamp = state.manifest && state.manifest.generatedAt;
    const date = stamp ? new Date(stamp * 1000).toLocaleDateString("zh-CN") : "未知";
    const el = $("#dataDate");
    if (el) el.textContent = `数据 ${date}`;
    const btn = $("#btnUpdate");
    if (btn) {
      btn.disabled = state.updating;
      btn.textContent = state.updating ? "更新中…" : "检查更新";
      btn.title = state.updateNote || `本地数据生成于 ${date}`;
    }
  }

  function renderSaveStatus() {
    const toggle = $("#autosaveToggle");
    if (toggle) toggle.checked = !!state.autosave;
    const btn = $("#btnBind");
    const status = $("#saveStatus");
    const tip = $("#saveTip");
    if (!status) return;
    const mode = state.saverMode;
    status.classList.toggle("ok", mode === "server" || mode === "handle");
    status.classList.toggle("warn", mode === "prompt" || mode === "download");
    status.textContent = state.saveNote || "…";
    if (btn) {
      const needBind = mode === "prompt";
      btn.hidden = !(needBind && state.autosave);
      btn.textContent = state.saveHandle ? "恢复自动保存" : "选择保存文件";
    }
    if (tip) {
      if (!state.autosave) {
        tip.textContent = "自动保存已关闭：勾选状态只留在当前链接里，关闭页面后需要靠链接恢复。";
      } else if (mode === "server") {
        tip.textContent = "保存文件与 exe 放在同一目录，每次勾选、取消、收藏都会即时更新。";
      } else if (mode === "handle") {
        tip.textContent = "每次勾选、取消、收藏都会静默写入这个文件（建议选在 index.html 同一目录）。";
      } else if (mode === "prompt") {
        tip.textContent = "选一次保存文件，之后所有改动都会自动写进去（浏览器不允许网页静默新建文件，所以需要你点一下）。";
      } else {
        tip.textContent = "这个浏览器不支持静默写文件，改动会以“导出 JSON”的方式下载。";
      }
    }
  }

  async function updateOnline(manual) {
    if (state.updating) return;
    const age = dataAgeDays();
    if (!manual && age < CACHE_TTL_DAYS) {
      state.updateNote = `本地缓存 ${Math.floor(age)} 天前生成，未满一个月，直接使用缓存`;
      renderDataStatus();
      return;
    }
    state.updating = true;
    state.updateNote = "正在在线更新…";
    renderDataStatus();
    if (manual) toast("正在从 AniList 拉取最新数据…");
    try {
      const targets = seasonsToRefresh();
      if (!targets.length) throw new Error("没有需要刷新的季度");
      const zhMap = await tryBangumiMap();
      let added = 0;
      let total = 0;
      for (const t of targets) {
        const list = await fetchSeason(t.year, t.season);
        const entries = [];
        for (const m of list) {
          if (!eligibleOnline(m)) continue;
          const entry = toEntry(m, zhMap);
          if (entry.cov) entries.push(entry);
        }
        added += mergeSeasonUpdate(t.year, t.season, entries);
        ensureYearInManifest(t.year);
        total += entries.length;
        await sleep(400);
      }
      state.updateNote = `最近刷新：${targets.length} 个季度 / ${total} 部，其中新增 ${added} 部`;
      if (manual) toast(`更新完成：刷新 ${targets.length} 个季度，新增 ${added} 部`);
      refreshAll();
    } catch (err) {
      state.updateNote = `在线更新失败（${err.message || "网络不可用"}），继续使用本地数据`;
      if (manual) toast("在线更新失败，继续使用本地缓存");
      console.warn("在线更新失败", err);
    } finally {
      state.updating = false;
      renderDataStatus();
    }
  }

  function kindOf(i) {
    const k = state.catalog.kinds.substr(i * 5, 5);
    return { ecchi: k[0] === "e", adult: k[1] === "a", short: k[2] === "s", extra: k[3] === "x", long: k[4] === "l" };
  }

  function passesFilters(i) {
    const c = state.catalog;
    if (!state.formats.has(Number(c.fmts[i]))) return false;
    const k = kindOf(i);
    if (state.hideShort && k.short) return false;
    if (state.hideExtra && k.extra) return false;
    if (state.hideLong && k.long) return false;
    if (state.hideEcchi && (k.ecchi || k.adult)) return false;
    return true;
  }

  function passesViewFilters(i) {
    if (state.onlyWatched && !watchedAt(i)) return false;
    if (state.onlyStarred && !starredAt(i)) return false;
    return true;
  }

  const sortEntries = (list) => {
    const by = state.sort;
    return list.slice().sort((a, b) => {
      if (by === "pop") return b.po - a.po;
      if (by === "score") return b.sc - a.sc || b.po - a.po;
      if (by === "fav") return b.fa - a.fa;
      if (by === "title") return (a.t.zh || a.t.romaji).localeCompare(b.t.zh || b.t.romaji, "zh-Hans-CN");
      return (a.d || "9999").localeCompare(b.d || "9999") || b.po - a.po;
    });
  };

  /* ---------------------------------------------------------------- rendering */

  function cardHTML(entry, index) {
    const c = state.catalog;
    const watched = watchedAt(index);
    const starred = starredAt(index);
    const k = kindOf(index);
    const fmt = c.formats[Number(c.fmts[index])];
    const title = entry.t.zh || entry.t.romaji || entry.t.native;
    let alt = entry.t.zh ? entry.t.native || entry.t.romaji : entry.t.romaji;
    if (alt === title) alt = "";
    const badges = [];
    if (fmt !== "TV") badges.push(`<span class="badge ${fmt === "OVA" || fmt === "SPECIAL" ? "extra" : ""}">${FORMAT_LABEL[fmt] || fmt}</span>`);
    if (k.short) badges.push('<span class="badge short">泡面</span>');
    if (k.ecchi || k.adult) badges.push('<span class="badge ecchi">肉番</span>');
    if (k.long) badges.push('<span class="badge extra">年番</span>');
    const eps = entry.ep ? `${entry.ep} 话` : "—";
    const score = entry.sc ? `<span class="score-val">★ ${(entry.sc / 10).toFixed(1)}</span>` : `<span>${entry.d ? entry.d.slice(0, 7) : ""}</span>`;
    const meta2 = c.formats[Number(c.fmts[index])];
    const img = entry.cov
      ? `<img src="${esc(entry.cov)}" alt="${esc(title)}" loading="lazy" decoding="async" referrerpolicy="no-referrer">`
      : "";
    const tooltip = [title, entry.t.romaji, `${fmt} · ${eps}`, entry.stu, entry.t.zhAlt && entry.t.zhAlt.length ? "豆瓣/BGM 别名：" + entry.t.zhAlt.join(" / ") : ""]
      .filter(Boolean)
      .join("\n");
    return `<div class="card${watched ? " watched" : ""}${starred ? " starred" : ""}" data-i="${index}" role="button" tabindex="0" title="${esc(tooltip)}">
      <div class="thumb" style="${entry.col ? `background:${esc(entry.col)}22` : ""}">
        ${img}
        <div class="fallback" hidden>${esc(title.slice(0, 1))}</div>
        <div class="badges">${badges.join("")}</div>
        <div class="ep-badge">${eps}</div>
        <div class="check">✓</div>
        <button class="star" data-star="${index}" title="${starred ? "移出补番列表" : "加入补番列表"}" aria-label="收藏到补番列表">★</button>
      </div>
      <div class="meta">
        <div class="title">${esc(title)}</div>
        <div class="title-alt">${esc(alt)}</div>
        <div class="meta-foot"><span>${esc(meta2)}</span>${score}</div>
      </div>
    </div>`;
  }

  function seasonSectionHTML(year, seasonIdx, entries) {
    const c = state.catalog;
    const watchedInSeason = entries.filter((e) => watchedAt(state.idx.get(e.id))).length;
    const html = entries.map((e) => cardHTML(e, state.idx.get(e.id))).join("");
    return `<section class="season" data-year="${year}" data-season="${seasonIdx}">
      <div class="season-head">
        <h3>${SEASON_LABEL[seasonIdx]}</h3>
        <span class="s-count">${SEASON_MONTHS[seasonIdx]} · 显示 ${entries.length} 部 · 已看 ${watchedInSeason}</span>
        <span class="s-actions">
          <button class="btn small" data-act="season-all">全选本季</button>
          <button class="btn small" data-act="season-none">清空本季</button>
        </span>
      </div>
      <div class="grid">${html}</div>
    </section>`;
  }

  function renderYearView(year) {
    const container = $("#seasons");
    const entries = entriesForYear(year);
    const total = entries.length;
    const bySeason = [[], [], [], []];
    for (const e of sortEntries(entries)) {
      const i = state.idx.get(e.id);
      if (i === undefined || !passesFilters(i)) continue;
      if (!passesViewFilters(i)) continue;
      bySeason[SEASON_ORDER_INDEX(e.s)].push(e);
    }
    let totalShown = 0;
    let totalWatched = 0;
    for (let s = 0; s < 4; s++) {
      totalShown += bySeason[s].length;
      totalWatched += bySeason[s].filter((e) => watchedAt(state.idx.get(e.id))).length;
    }
    container.innerHTML = bySeason.map((list, s) => seasonSectionHTML(year, s, list)).join("");
    $("#emptyState").hidden = totalShown > 0;
    const watchedYear = state.yearStats.get(year) || 0;
    $("#viewTitle").textContent = `${year} 年`;
    $("#viewSub").textContent = `收录 ${total} 部 · 当前显示 ${totalShown} 部 · 已看 ${watchedYear} 部（${total ? ((watchedYear / total) * 100).toFixed(1) : 0}%）`;
  }

  function SEASON_ORDER_INDEX(s) {
    const i = SEASONS.indexOf(s);
    return i < 0 ? 0 : i;
  }

  function renderSearchView() {
    const container = $("#seasons");
    const matches = state.searchMatches || [];
    if (!matches.length) {
      container.innerHTML = "";
      $("#emptyState").hidden = false;
      $("#emptyState").textContent = "没有找到匹配的番剧。";
      $("#viewTitle").textContent = `搜索：${state.searchQuery}`;
      $("#viewSub").textContent = state.scope === "year" ? `${state.year} 年内没有匹配` : "全部年份内没有匹配";
      return;
    }
    const byYear = new Map();
    for (const i of matches) {
      const y = state.catalog.years[i];
      if (!byYear.has(y)) byYear.set(y, []);
      byYear.get(y).push(i);
    }
    const chunks = [];
    for (const y of Array.from(byYear.keys()).sort((a, b) => b - a)) {
      const entries = entriesForYear(y).filter((e) => {
        const i = state.idx.get(e.id);
        return byYear.get(y).includes(i) && passesFilters(i) && passesViewFilters(i);
      });
      if (!entries.length) continue;
      const watchedN = entries.filter((e) => watchedAt(state.idx.get(e.id))).length;
      chunks.push(`<section class="season" data-year="${y}">
        <div class="season-head"><h3>${y} 年</h3>
          <span class="s-count">匹配 ${entries.length} 部 · 已看 ${watchedN}</span>
          <span class="s-actions"><button class="btn small" data-act="season-all">全选</button><button class="btn small" data-act="season-none">清空</button></span>
        </div>
        <div class="grid">${sortEntries(entries).map((e) => cardHTML(e, state.idx.get(e.id))).join("")}</div>
      </section>`);
    }
    container.innerHTML = chunks.join("");
    $("#emptyState").hidden = chunks.length > 0;
    $("#viewTitle").textContent = `搜索：${state.searchQuery}`;
    $("#viewSub").textContent = `在全部 ${state.catalog.ids.length} 部里找到 ${matches.length} 部`;
  }

  function renderStarredView() {
    const container = $("#seasons");
    const byYear = new Map();
    for (let i = 0; i < state.catalog.ids.length; i++) {
      if (!starredAt(i)) continue;
      const y = state.catalog.years[i];
      if (!byYear.has(y)) byYear.set(y, []);
      byYear.get(y).push(i);
    }
    if (!byYear.size) {
      container.innerHTML = "";
      $("#emptyState").hidden = false;
      $("#emptyState").textContent = "补番列表还是空的：把鼠标移到封面左下角的 ★ 上点一下就能收藏。";
      $("#viewTitle").textContent = "补番列表";
      $("#viewSub").textContent = "0 部待补";
      return;
    }
    const chunks = [];
    for (const y of Array.from(byYear.keys()).sort((a, b) => b - a)) {
      const ids = new Set(byYear.get(y));
      const entries = sortEntries(entriesForYear(y).filter((e) => ids.has(state.idx.get(e.id))));
      const watchedN = entries.filter((e) => watchedAt(state.idx.get(e.id))).length;
      chunks.push(`<section class="season" data-year="${y}">
        <div class="season-head"><h3>${y} 年</h3>
          <span class="s-count">收藏 ${entries.length} 部 · 其中已看 ${watchedN}</span>
          <span class="s-actions">
            <button class="btn small" data-act="season-all">全部标记已看</button>
            <button class="btn small" data-act="star-none">清空本页收藏</button>
          </span>
        </div>
        <div class="grid">${entries.map((e) => cardHTML(e, state.idx.get(e.id))).join("")}</div>
      </section>`);
    }
    container.innerHTML = chunks.join("");
    $("#emptyState").hidden = true;
    $("#viewTitle").textContent = "补番列表";
    $("#viewSub").textContent = `${state.starred} 部待补 · 按年份分组`;
  }

  async function showStarred() {
    state.view = "starred";
    const years = new Set();
    for (let i = 0; i < state.catalog.ids.length; i++) if (starredAt(i)) years.add(state.catalog.years[i]);
    const need = Array.from(years).filter((y) => !state.cache.has(y));
    if (need.length) {
      $("#seasons").innerHTML = `<div class="empty">正在载入补番列表…</div>`;
      await Promise.all(need.map((y) => loadYear(y).catch(() => [])));
    }
    state.searchMatches = null;
    renderStarredView();
    renderYears();
    renderHeatmap();
  }

  async function runSearch(query) {
    state.searchQuery = query;
    const q = norm(query);
    if (!q) {
      state.searchMatches = null;
      state.view = "year";
      await showYear(state.year);
      return;
    }
    if (!state.searchIndex) {
      $("#seasons").innerHTML = `<div class="empty">正在载入搜索索引…</div>`;
      await ensureSearchIndex();
    }
    const hits = [];
    const text = state.searchIndex || [];
    for (let i = 0; i < text.length; i++) if (text[i].indexOf(q) >= 0) hits.push(i);
    state.view = "search";
    if (state.scope === "year") {
      const y = state.year;
      state.searchMatches = hits.filter((i) => state.catalog.years[i] === y);
      renderSearchView();
      return;
    }
    state.searchMatches = hits;
    const yearsNeeded = Array.from(new Set(hits.map((i) => state.catalog.years[i]))).filter((y) => !state.cache.has(y));
    $("#seasons").innerHTML = `<div class="empty">正在载入 ${yearsNeeded.length} 个年份的数据…</div>`;
    await Promise.all(yearsNeeded.map((y) => loadYear(y).catch(() => [])));
    renderSearchView();
  }

  /* ----------------------------------------------------------------- sidebar */

  function renderYears() {
    const box = $("#yearList");
    const years = state.manifest.years.map((y) => y.year).sort((a, b) => b - a);
    box.innerHTML = years
      .map((y) => {
        const count = yearCountOf(y);
        const w = state.yearStats.get(y) || 0;
        const pct = count ? (w / count) * 100 : 0;
        return `<button class="year-item${y === state.year ? " active" : ""}" data-year="${y}">
          <b>${y}</b>
          <span class="year-bar"><i style="width:${pct.toFixed(1)}%"></i></span>
          <span class="year-count">${w ? w + "/" : ""}${count}</span>
        </button>`;
      })
      .join("");
    const select = $("#yearSelect");
    if (select && select.options.length !== years.length) {
      select.innerHTML = years.map((y) => `<option value="${y}">${y} 年</option>`).join("");
    }
    if (select && select.value !== String(state.year)) select.value = String(state.year);
  }

  function renderHeatmap() {
    const box = $("#heatmap");
    const years = state.manifest.years.map((y) => y.year);
    const cols = years.map((y) => {
      const cells = [0, 1, 2, 3].map((s) => {
        const total = seasonCountOf(y, SEASONS[s]);
        const w = state.seasonStats.get(y * 4 + s) || 0;
        const ratio = total ? w / total : 0;
        const level = w === 0 ? 0 : ratio >= 0.5 ? 4 : ratio >= 0.28 ? 3 : ratio >= 0.12 ? 2 : 1;
        const active = state.year === y && state.view === "year";
        return `<button class="heat-cell heat-${level}${active ? " sel" : ""}" data-year="${y}" data-season="${s}"
          title="${y} 年${SEASON_LABEL[s]}：已看 ${w} / ${total} 部"></button>`;
      }).join("");
      const label = y % 5 === 0 || y === years[0] || y === years[years.length - 1];
      return `<div class="heat-col" data-year="${y}" title="${y}">${cells}<span class="heat-year${label ? " on" : ""}">${label ? y : ""}</span></div>`;
    });
    box.innerHTML = cols.join("");
  }

  function renderEra() {
    const box = $("#eraSummary");
    if (!state.watched) {
      box.innerHTML = `<p class="era-empty">勾选你看过的番，这里会分析出你属于哪个世代。</p>`;
      return;
    }
    const perYear = state.yearStats;
    let best = null;
    for (const era of ERAS) {
      let n = 0;
      for (let y = era.from; y <= era.to; y++) n += perYear.get(y) || 0;
      const span = era.to - era.from + 1;
      const score = n / span;
      if (!best || score > best.score) best = { era, n, score };
    }
    // 主要活动年份（含勾选最多的单年）
    let peakYear = null;
    for (const [y, n] of perYear) if (!peakYear || n > peakYear[1]) peakYear = [y, n];

    const genreCount = new Map();
    for (let i = 0; i < state.catalog.ids.length; i++) {
      if (!watchedAt(i)) continue;
      const mask = state.catalog.gmask[i];
      state.catalog.genres.forEach((g, bit) => {
        if (mask & (1 << bit)) genreCount.set(g, (genreCount.get(g) || 0) + 1);
      });
    }
    const topGenres = Array.from(genreCount.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5);

    let mins = 0;
    for (let i = 0; i < state.catalog.ids.length; i++) {
      if (!watchedAt(i)) continue;
      const ep = state.catalog.eps[i] || 0;
      const du = state.catalog.dur[i] || 24;
      mins += ep * du;
    }
    const fmtCount = [0, 0, 0, 0, 0];
    for (let i = 0; i < state.catalog.ids.length; i++) if (watchedAt(i)) fmtCount[Number(state.catalog.fmts[i])]++;

    const hours = Math.round(mins / 60);
    const verdict = evaluate(state.watched, hours);
    box.innerHTML = `<div class="era-title">你的动画世代：<em>${best.n >= 12 ? best.era.name : "散装补番党"}</em></div>
      <p class="era-desc">${best.n >= 12 ? esc(best.era.desc) : "勾选还不多，先随便点几部，世代分析会更有意思。"}
      最高产的年份是 <b>${peakYear[0]}</b> 年（${peakYear[1]} 部）。</p>
      <p class="era-verdict">追番评价：<b>${esc(verdict.rank)}</b> · 段位 ${esc(verdict.rating)}</p>
      <div class="era-tags">
        <span>共 ${state.watched} 部</span>
        <span>约 ${hours} 小时</span>
        <span>TV ${fmtCount[0]}</span>
        ${topGenres.map(([g, n]) => `<span>${esc(g)} ${n}</span>`).join("")}
      </div>`;
  }

  function renderSummary() {
    const total = state.catalog.ids.length;
    $("#watchedCount").textContent = state.watched;
    const starEl = $("#starCount");
    if (starEl) starEl.textContent = state.starred;
    const starBtn = $("#btnStarred");
    if (starBtn) starBtn.classList.toggle("on", state.view === "starred");
    $("#watchedPercent").textContent = total ? ((state.watched / total) * 100).toFixed(2) + "%" : "0%";
    let mins = 0;
    for (let i = 0; i < total; i++) {
      if (!watchedAt(i)) continue;
      mins += (state.catalog.eps[i] || 0) * (state.catalog.dur[i] || 24);
    }
    $("#watchedHours").textContent = Math.round(mins / 60).toLocaleString("zh-CN");
    $("#scoreBar").style.width = total ? ((state.watched / total) * 100).toFixed(2) + "%" : "0%";
  }

  function refreshAll({ keepScroll = true } = {}) {
    const y = window.scrollY;
    recomputeStats();
    renderSummary();
    renderEra();
    renderYears();
    renderHeatmap();
    if (state.view === "search") renderSearchView();
    else if (state.view === "starred") renderStarredView();
    else renderYearView(state.year);
    if (keepScroll) window.scrollTo(0, y);
    writeHash();
  }

  async function showYear(year) {
    state.view = "year";
    state.year = year;
    $("#seasons").innerHTML = `<div class="empty">载入 ${year} 年…</div>`;
    try {
      await loadYear(year);
    } catch (err) {
      // 在线更新可能带来了本地还没有的新年份（例如跨年），这种情况直接用它
      const hasOnline = Array.from(state.seasonUpdates.keys()).some((k) => k.startsWith(year + "-"));
      if (hasOnline) {
        if (!state.cache.has(year)) state.cache.set(year, []);
        refreshAll({ keepScroll: false });
        return;
      }
      $("#seasons").innerHTML = `<div class="empty">无法载入 data/${year}.js。<br>请确认 <code>data/</code> 目录和 index.html 放在一起，没有单独移动过。</div>`;
      console.error(err);
      return;
    }
    refreshAll({ keepScroll: false });
  }

  /* ------------------------------------------------------------------ events */

  function toast(msg, ms = 2200) {
    const el = $("#toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(() => (el.hidden = true), ms);
  }

  function toggleAt(i) {
    if (i === undefined || i === null || Number.isNaN(i)) return;
    setWatched(i, !watchedAt(i));
    const card = $(`.card[data-i="${i}"]`);
    if (card) card.classList.toggle("watched", !!watchedAt(i));
    recomputeStats();
    renderSummary();
    renderEra();
    renderYears();
    renderHeatmap();
    const year = state.catalog.years[i];
    if (state.view === "starred") renderStarredView();
    else if (year === state.year) updateYearSub();
    writeHash();
    scheduleAutosave();
  }

  function toggleStar(i) {
    if (i === undefined || i === null || Number.isNaN(i)) return;
    setStarred(i, !starredAt(i));
    const card = $(`.card[data-i="${i}"]`);
    if (card) {
      card.classList.toggle("starred", !!starredAt(i));
      const star = card.querySelector(".star");
      if (star) star.title = starredAt(i) ? "移出补番列表" : "加入补番列表";
    }
    recomputeStats();
    renderSummary();
    renderYears();
    if (state.view === "starred") renderStarredView();
    writeHash();
    toast(starredAt(i) ? "已加入补番列表 ★" : "已移出补番列表");
    scheduleAutosave();
  }

  function updateYearSub() {
    const total = yearCountOf(state.year);
    const watchedYear = state.yearStats.get(state.year) || 0;
    $("#viewSub").textContent = `收录 ${total} 部 · 已看 ${watchedYear} 部（${total ? ((watchedYear / total) * 100).toFixed(1) : 0}%）`;
  }

  function boundMark(year, season, on, mode) {
    const entries = entriesForYear(year);
    let n = 0;
    for (const e of entries) {
      const i = state.idx.get(e.id);
      if (i === undefined) continue;
      if (season !== null && SEASON_ORDER_INDEX(e.s) !== season) continue;
      if (state.view === "search" && state.searchMatches && !state.searchMatches.includes(i)) continue;
      if (state.view === "starred" && !starredAt(i)) continue;
      if (!passesFilters(i)) continue;
      if (mode === "star") {
        if (starredAt(i) !== (on ? 1 : 0)) n++;
        setStarred(i, on);
      } else {
        if (watchedAt(i) !== (on ? 1 : 0)) n++;
        setWatched(i, on);
      }
    }
    refreshAll();
    toast(mode === "star" ? `已移出补番列表 ${n} 部` : on ? `已标记 ${n} 部` : `已取消 ${n} 部`);
    scheduleAutosave();
  }

  function wire() {
    window.addEventListener("error", (ev) => {
      const t = ev.target;
      if (t && t.tagName === "IMG") {
        t.style.display = "none";
        const fb = t.parentElement && t.parentElement.querySelector(".fallback");
        if (fb) fb.hidden = false;
      }
    }, true);

    $("#seasons").addEventListener("click", (ev) => {
      const star = ev.target.closest(".star");
      if (star) {
        ev.preventDefault();
        ev.stopPropagation();
        toggleStar(Number(star.dataset.star));
        return;
      }
      const btn = ev.target.closest("button[data-act]");
      if (btn) {
        const section = btn.closest(".season");
        const year = Number(section.dataset.year);
        const season = section.dataset.season;
        if (btn.dataset.act === "star-none") {
          boundMark(year, null, false, "star");
        } else {
          boundMark(year, season === undefined ? null : Number(season), btn.dataset.act === "season-all");
        }
        return;
      }
      const card = ev.target.closest(".card");
      if (card) toggleAt(Number(card.dataset.i));
    });

    $("#seasons").addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const card = ev.target.closest(".card");
      if (card && ev.target === card) {
        ev.preventDefault();
        toggleAt(Number(card.dataset.i));
      }
    });

    $("#yearList").addEventListener("click", (ev) => {
      const item = ev.target.closest(".year-item");
      if (item) showYear(Number(item.dataset.year));
    });

    $("#yearSelect").addEventListener("change", (ev) => showYear(Number(ev.target.value)));

    $("#heatmap").addEventListener("click", (ev) => {
      const col = ev.target.closest(".heat-col");
      if (!col) return;
      showYear(Number(col.dataset.year));
    });

    $("#formatFilters").innerHTML = FORMAT_LABEL_HTML();
    $("#formatFilters").addEventListener("click", (ev) => {
      const chip = ev.target.closest(".chip");
      if (!chip) return;
      const i = Number(chip.dataset.fmt);
      if (state.formats.has(i)) state.formats.delete(i);
      else state.formats.add(i);
      chip.classList.toggle("on", state.formats.has(i));
      if (state.view === "search") renderSearchView();
      else renderYearView(state.year);
      renderHeatmap();
    });

    let searchTimer = 0;
    $("#search").addEventListener("input", (ev) => {
      const v = ev.target.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => runSearch(v), 180);
    });
    $$('input[name="scope"]').forEach((el) =>
      el.addEventListener("change", () => {
        state.scope = el.value;
        if ($("#search").value.trim()) runSearch($("#search").value);
      })
    );

    const bools = {
      hideShort: "hideShort",
      hideExtra: "hideExtra",
      hideLong: "hideLong",
      hideEcchi: "hideEcchi",
      onlyWatched: "onlyWatched",
      onlyStarred: "onlyStarred",
    };
    Object.keys(bools).forEach((id) => {
      $("#" + id).addEventListener("change", (ev) => {
        state[bools[id]] = ev.target.checked;
        if (state.view === "search") renderSearchView();
        else if (state.view === "starred") renderStarredView();
        else renderYearView(state.year);
      });
    });

    $("#compact").addEventListener("change", (ev) => document.body.classList.toggle("compact", ev.target.checked));
    $("#showCovers").addEventListener("change", (ev) => document.body.classList.toggle("no-covers", !ev.target.checked));
    $("#sort").addEventListener("change", (ev) => {
      state.sort = ev.target.value;
      if (state.view === "search") renderSearchView();
      else renderYearView(state.year);
    });

    $("#btnSelectSeason").addEventListener("click", () => boundMark(state.year, null, true));
    $("#btnClearSeason").addEventListener("click", () => boundMark(state.year, null, false));
    $("#btnStarred").addEventListener("click", () => {
      if (state.view === "starred") showYear(state.year);
      else showStarred();
    });

    $("#btnClear").addEventListener("click", () => {
      if (!state.watched) return;
      if (!confirm(`确定清空全部 ${state.watched} 部已看记录吗？（补番列表 ${state.starred} 部会保留）`)) return;
      state.bits = new Uint8Array((state.catalog.ids.length + 7) >> 3);
      refreshAll();
      scheduleAutosave();
      toast("已清空");
    });

    $("#btnShare").addEventListener("click", async () => {
      const url = location.href;
      const local = location.protocol === "file:";
      const done = () =>
        toast(local ? "链接已复制（本地文件路径，本机刷新 / 收藏可用）" : "分享链接已复制（勾选状态就在链接里）");
      try {
        if (!navigator.clipboard || !window.isSecureContext) throw new Error("clipboard unavailable");
        await navigator.clipboard.writeText(url);
        done();
        return;
      } catch (err) {
        /* 退回到 execCommand 复制 */
      }
      try {
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.setAttribute("readonly", "");
        ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(ta);
        if (ok) {
          done();
          return;
        }
      } catch (err) {
        /* ignore */
      }
      prompt("复制这个链接：", url);
    });

    $("#btnExport").addEventListener("click", () => {
      const name = `anime-lists-${new Date().toISOString().slice(0, 10)}.json`;
      if (state.saverMode === "server" || state.saverMode === "handle") {
        saveNow({ silent: false, name });
        return;
      }
      downloadText(name, JSON.stringify(payload(), null, 1));
      toast("已导出：" + name);
    });

    $("#btnImport").addEventListener("click", () => $("#importFile").click());
    $("#importFile").addEventListener("change", async (ev) => {
      const file = ev.target.files[0];
      if (!file) return;
      const text = await file.text();
      importPayload(text);
      ev.target.value = "";
    });

    $("#btnPoster").addEventListener("click", makePoster);
    $("#btnUpdate").addEventListener("click", () => updateOnline(true));
    $("#autosaveToggle").addEventListener("change", (ev) => {
      state.autosave = ev.target.checked;
      writeSetting(AUTOSAVE_KEY, state.autosave ? "1" : "0");
      if (state.autosave) scheduleAutosave();
      else clearTimeout(autosaveTimer);
      renderSaveStatus();
    });
    $("#btnBind").addEventListener("click", bindSaveFile);

    window.addEventListener("hashchange", () => {
      const parsed = readHash();
      if (parsed.year && parsed.year !== state.year) showYear(parsed.year);
      else refreshAll();
    });
  }

  function FORMAT_LABEL_HTML() {
    return state.catalog.formats
      .map((f, i) => `<button class="chip${state.formats.has(i) ? " on" : ""}" data-fmt="${i}">${FORMAT_LABEL[f] || f}</button>`)
      .join("");
  }

  function importPayload(text) {
    const trimmed = text.trim();
    let ids = [];
    let stars = [];
    try {
      const data = JSON.parse(trimmed);
      ids = Array.isArray(data) ? data : data.watched || [];
      stars = Array.isArray(data) ? [] : data.starred || data.plan || [];
    } catch (err) {
      const m = trimmed.match(/w=([A-Za-z0-9\-_]+)/);
      const ms = trimmed.match(/s=([A-Za-z0-9\-_]+)/);
      if (m || ms) {
        try {
          const need = (state.catalog.ids.length + 7) >> 3;
          if (m) {
            const bytes = fromB64url(m[1]);
            state.bits = new Uint8Array(need);
            state.bits.set(bytes.subarray(0, need));
          }
          if (ms) {
            const bytes = fromB64url(ms[1]);
            state.starBits = new Uint8Array(need);
            state.starBits.set(bytes.subarray(0, need));
          }
          refreshAll();
          toast("已从链接导入");
          return;
        } catch (e2) {
          toast("链接解析失败");
          return;
        }
      }
      toast("无法识别的内容");
      return;
    }
    let n = 0;
    state.bits = new Uint8Array((state.catalog.ids.length + 7) >> 3);
    state.starBits = new Uint8Array((state.catalog.ids.length + 7) >> 3);
    for (const id of ids) {
      const i = state.idx.get(Number(id));
      if (i === undefined) continue;
      if (!watchedAt(i)) n++;
      setWatched(i, true);
    }
    let s = 0;
    for (const id of stars) {
      const i = state.idx.get(Number(id));
      if (i === undefined) continue;
      if (!starredAt(i)) s++;
      setStarred(i, true);
    }
    refreshAll();
    toast(`已导入 ${n} 部已看${s ? ` / ${s} 部补番` : ""}`);
    scheduleAutosave();
  }

  /* ------------------------------------------------------------ 追番评价 */
  const RANKS = [
    { max: 10, name: "刚上路的旅人", comment: "番剧世界的大门刚刚打开，一切都还新鲜。" },
    { max: 30, name: "周末补番党", comment: "假期就是用来一口气看完一季的。" },
    { max: 80, name: "稳定追番人", comment: "每一季的新番表里都能看到你的身影。" },
    { max: 200, name: "资深宅", comment: "深夜档的作息已经刻进生物钟。" },
    { max: 400, name: "动画区老宅", comment: "和新番表交流，可能比和人交流更自然。" },
    { max: 700, name: "人形自走番剧库", comment: "别人问推荐，你能直接报出一整季片单。" },
    { max: 1200, name: "活体动画年鉴", comment: "你见证过太多作品的第一次。" },
    { max: Infinity, name: "传说级追番之神", comment: "这份清单本身，就是一部动画史。" },
  ];

  function hoursComment(hours) {
    if (hours < 100) return `折算下来才 ${hours} 小时左右，属于快乐先行的看法。`;
    if (hours < 500) return `${hours} 小时，够把一整个季度从头追到尾。`;
    if (hours < 2000) return `${hours} 小时，你的人生有相当一部分留在了屏幕里。`;
    if (hours < 5000) return `${hours} 小时，足够从零学一门手艺了——你选择了看番。`;
    return `${hours} 小时，这已经不是爱好，是刻进 DNA 的第二人生。`;
  }

  function ratingOf(watched, hours) {
    const score = watched + hours / 40;
    if (score < 15) return "C";
    if (score < 40) return "B";
    if (score < 100) return "A";
    if (score < 250) return "S";
    if (score < 500) return "SS";
    if (score < 1000) return "SSS";
    return "SSS+";
  }

  function evaluate(watched, hours) {
    const rank = RANKS.find((r) => watched < r.max) || RANKS[RANKS.length - 1];
    return {
      rank: rank.name,
      comment: rank.comment,
      hoursLine: hoursComment(hours),
      rating: ratingOf(watched, hours),
    };
  }

  async function makePoster() {
    if (!state.watched) {
      toast("先勾选几部再生成海报吧");
      return;
    }
    const need = Array.from(new Set([...state.yearStats.keys()].filter((y) => !state.cache.has(y))));
    if (need.length) {
      toast("正在整理清单…");
      await Promise.all(need.map((y) => loadYear(y).catch(() => [])));
    }
    const picks = [];
    for (const y of state.yearStats.keys()) {
      for (const e of entriesForYear(y)) {
        const i = state.idx.get(e.id);
        if (i !== undefined && watchedAt(i)) picks.push(e);
      }
    }
    // 海报按时间「降序」排（最新看的番排在最前面），全部已看都要出现
    picks.sort((a, b) => b.y - a.y || SEASON_ORDER_INDEX(b.s) - SEASON_ORDER_INDEX(a.s) || (b.d || "").localeCompare(a.d || ""));
    const items = picks;
    const W = 1400;
    const pad = 40;
    let mins = 0;
    for (let i = 0; i < state.catalog.ids.length; i++) {
      if (watchedAt(i)) mins += (state.catalog.eps[i] || 0) * (state.catalog.dur[i] || 24);
    }
    const hours = Math.round(mins / 60);
    const verdict = evaluate(state.watched, hours);

    // 全量已看：数量多时改用密集文字清单，避免封面小到看不清
    const listMode = items.length > 1500;
    const cols = listMode ? 4 : items.length <= 240 ? 8 : items.length <= 600 ? 12 : items.length <= 1200 ? 16 : 20;
    const gap = listMode ? 0 : 10;
    const cw = (W - pad * 2 - (cols - 1) * gap) / cols;
    const ch = listMode ? 22 : Math.max(34, Math.round(cw * 0.78));
    const gridTop = 660;
    const rows = Math.ceil(items.length / cols);

    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = gridTop + rows * (ch + gap) + 96;
    const ctx = canvas.getContext("2d");
    const g = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    g.addColorStop(0, "#0d1018");
    g.addColorStop(0.35, "#14101f");
    g.addColorStop(1, "#1c1024");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const rounded = (x, y, w, h, r) => {
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
      else ctx.rect(x, y, w, h);
    };

    // ---- 标题
    ctx.fillStyle = "#ff5d73";
    ctx.fillRect(pad, 54, 6, 62);
    ctx.fillStyle = "#ffb457";
    ctx.font = "700 40px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
    ctx.fillText("我的番剧年表", pad + 20, 96);
    ctx.fillStyle = "#c9d1e4";
    ctx.font = "400 19px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
    const eraText = ($(".era-title") && $(".era-title").textContent.replace("你的动画世代：", "")) || "";
    ctx.fillText(
      `看过 ${state.watched} 部 · 约 ${hours.toLocaleString("zh-CN")} 小时 · ${eraText}`,
      pad + 20,
      134
    );

    // ---- 评价卡片
    const boxY = 164;
    const boxH = 150;
    ctx.fillStyle = "rgba(255,93,115,.10)";
    rounded(pad, boxY, W - pad * 2, boxH, 16);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,93,115,.45)";
    ctx.lineWidth = 2;
    rounded(pad, boxY, W - pad * 2, boxH, 16);
    ctx.stroke();

    ctx.fillStyle = "#8e97ad";
    ctx.font = "500 15px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
    ctx.fillText("追番评价", pad + 24, boxY + 34);

    ctx.fillStyle = "#ffb457";
    ctx.font = "700 30px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
    ctx.fillText(verdict.rank, pad + 24, boxY + 74);
    const rankW = ctx.measureText(verdict.rank).width;
    ctx.fillStyle = "#ff5d73";
    ctx.font = "700 22px system-ui, sans-serif";
    ctx.fillText(`段位 ${verdict.rating}`, pad + 40 + rankW, boxY + 74);

    ctx.fillStyle = "#c9d1e4";
    ctx.font = "400 17px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
    ctx.fillText(verdict.comment, pad + 24, boxY + 106);
    ctx.fillStyle = "#9aa4bb";
    ctx.font = "400 15px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
    ctx.fillText(verdict.hoursLine, pad + 24, boxY + 132);

    // ---- per-year bars
    const yearsAsc = state.manifest.years.map((m) => m.year);
    const maxYear = Math.max(1, ...yearsAsc.map((y) => state.yearStats.get(y) || 0));
    const chartTop = 380;
    const chartH = 150;
    const bw = (W - pad * 2) / yearsAsc.length;
    yearsAsc.forEach((y, idx) => {
      const n = state.yearStats.get(y) || 0;
      const h = n ? Math.max(4, (n / maxYear) * chartH) : 2;
      const x = pad + idx * bw;
      ctx.fillStyle = n ? "#ff5d73" : "#242b3d";
      ctx.fillRect(x + 1, chartTop + chartH - h, bw - 4, h);
      if (y % 5 === 0 || idx === 0) {
        ctx.fillStyle = "#8e97ad";
        ctx.font = "400 13px system-ui, sans-serif";
        ctx.fillText(String(y), x - 2, chartTop + chartH + 22);
      }
    });
    ctx.fillStyle = "#8e97ad";
    ctx.font = "400 13px system-ui, sans-serif";
    ctx.fillText(`单年最多 ${maxYear} 部`, W - pad - 130, chartTop - 14);

    // ---- top genres
    const genreCount = new Map();
    for (let i = 0; i < state.catalog.ids.length; i++) {
      if (!watchedAt(i)) continue;
      const mask = state.catalog.gmask[i];
      state.catalog.genres.forEach((gn, bit) => {
        if (mask & (1 << bit)) genreCount.set(gn, (genreCount.get(gn) || 0) + 1);
      });
    }
    const topGenres = Array.from(genreCount.entries()).sort((a, b) => b[1] - a[1]).slice(0, 8);
    let gx = pad;
    const gy = 606;
    ctx.font = "500 15px system-ui, sans-serif";
    for (const [gn, n] of topGenres) {
      const label = `${gn} ${n}`;
      const w = ctx.measureText(label).width + 26;
      ctx.fillStyle = "#22182c";
      rounded(gx, gy - 20, w, 28, 14);
      ctx.fill();
      ctx.fillStyle = "#ffc7d1";
      ctx.fillText(label, gx + 13, gy);
      gx += w + 10;
      if (gx > W - pad - 140) break;
    }

    // ---- 全部已看清单（不画远程封面：AniList 图床没有 CORS 头，画布会被污染）
    const wrap = (text, maxWidth, maxLines) => {
      const lines = [];
      let line = "";
      for (const chr of text) {
        if (ctx.measureText(line + chr).width > maxWidth && line) {
          lines.push(line);
          line = chr;
          if (lines.length === maxLines) break;
        } else line += chr;
      }
      if (lines.length < maxLines && line) lines.push(line);
      return lines;
    };

    const rowsPerCol = listMode ? Math.ceil(items.length / cols) : rows;
    if (listMode) {
      const clip = (text, maxWidth) => {
        if (ctx.measureText(text).width <= maxWidth) return text;
        let out = "";
        for (const chr of text) {
          if (ctx.measureText(out + chr + "…").width > maxWidth) break;
          out += chr;
        }
        return out + "…";
      };
      ctx.font = "400 15px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
      items.forEach((e, n) => {
        const col = Math.floor(n / rowsPerCol);
        const row = n % rowsPerCol;
        const x = pad + col * cw;
        const y = gridTop + row * ch;
        ctx.fillStyle = "#ff5d73";
        ctx.fillRect(x, y - 9, 5, 5);
        ctx.fillStyle = "#e8ecf5";
        const title = e.t.zh || e.t.romaji || e.t.native;
        const line = clip(title, cw - 108);
        ctx.fillText(line, x + 12, y);
        ctx.fillStyle = "#8e97ad";
        ctx.font = "400 12px system-ui, sans-serif";
        const tw = ctx.measureText(line).width;
        ctx.fillText(`${e.y}${SEASON_LABEL[SEASON_ORDER_INDEX(e.s)][0]}·${e.ep}话`, x + 20 + tw, y);
        ctx.font = "400 15px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif";
      });
    } else {
      const fs = cw >= 110 ? 13 : cw >= 84 ? 12 : 11;
      items.forEach((e, n) => {
        const x = pad + (n % cols) * (cw + gap);
        const y = gridTop + Math.floor(n / cols) * (ch + gap);
        const base = /^#[0-9a-fA-F]{6}$/.test(e.col || "") ? e.col : "#2b3348";
        const grad = ctx.createLinearGradient(x, y, x + cw, y + ch);
        grad.addColorStop(0, base);
        grad.addColorStop(1, "#0f1219");
        ctx.fillStyle = grad;
        rounded(x, y, cw, ch, 8);
        ctx.fill();
        ctx.fillStyle = "rgba(8,10,15,.58)";
        ctx.fillRect(x, y + ch - 24, cw, 24);
        ctx.fillStyle = "#ffffff";
        ctx.font = `600 ${fs}px 'PingFang SC','Microsoft YaHei',system-ui,sans-serif`;
        const title = e.t.zh || e.t.romaji || e.t.native;
        wrap(title, cw - 14, 2).forEach((line, li) => {
          ctx.fillText(line, x + 7, y + 18 + li * (fs + 3));
        });
        ctx.fillStyle = "#cfd6e6";
        ctx.font = "400 10.5px system-ui, sans-serif";
        ctx.fillText(`${e.y} ${SEASON_LABEL[SEASON_ORDER_INDEX(e.s)]} · ${e.ep || "?"}话`, x + 7, y + ch - 8);
      });
    }

    ctx.fillStyle = "#8e97ad";
    ctx.font = "400 14px system-ui, sans-serif";
    ctx.fillText(
      `1990-2026 番剧年表 · 收录 ${state.catalog.ids.length} 部 · 本海报含全部已看 ${items.length} 部 · ` +
        `数据 ${new Date((state.manifest.generatedAt || 0) * 1000).toLocaleDateString("zh-CN")}`,
      pad,
      canvas.height - 34
    );
    ctx.fillStyle = "#6f7788";
    ctx.font = "400 13px system-ui, sans-serif";
    ctx.fillText("github.com/AoXiang-Soar/Anime-Lists", pad, canvas.height - 14);
    try {
      const url = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = url;
      const name = `anime-lists-poster-${new Date().toISOString().slice(0, 10)}.png`;
      if (state.saverMode === "server") {
        // exe 模式：海报也直接写进 exe 所在目录
        fetch("__save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, base64: url.split(",")[1] }),
        })
          .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
          .then((info) => {
            state.saveNote = `海报已保存到 ${info.path}`;
            renderSaveStatus();
            toast("海报已保存到 " + info.path);
          })
          .catch((err) => {
            toast("海报保存失败，改为下载");
            a.download = name;
            a.click();
          });
        return;
      }
      a.download = name;
      a.click();
      toast("海报已生成");
    } catch (err) {
      toast("海报导出失败：" + err.message);
    }
  }

  /* --------------------------------------------------------------------- init */

  async function init() {
    try {
      const manifest = window.ANIME_INDEX;
      const catalog = window.ANIME_CATALOG;
      if (!manifest || !catalog) throw new Error("缺少 data/index.js 或 data/catalog.js");
      state.manifest = manifest;
      state.catalog = catalog;
      state.bits = new Uint8Array((catalog.ids.length + 7) >> 3);
      state.starBits = new Uint8Array((catalog.ids.length + 7) >> 3);
      catalog.ids.forEach((id, i) => state.idx.set(id, i));
      $("#totalCount").textContent = `1990-2026 共收录 ${catalog.ids.length} 部`;
      wire();
      ensureSearchIndex();
      const hash = readHash();
      await detectSaver();
      const restored = await loadSavedState();
      recomputeStats();
      renderSaveStatus();
      const newest = manifest.years[manifest.years.length - 1].year;
      const startYear = hash.year || newest;
      await showYear(startYear);
      renderSaveStatus();
      renderDataStatus();
      if (restored) {
        toast(`已从本地文件恢复 ${state.watched} 部已看 / ${state.starred} 部补番`);
      }
      if (state.saverMode === "server") {
        // 保活：关掉页面后 exe 进程才会自己退出
        setInterval(() => {
          fetch("__ping", { cache: "no-store" }).catch(() => {});
        }, 60000);
      }
      // 先尝试在线更新：缓存不满一个月就直接用缓存
      updateOnline(false);
      // 后台逐年份预取，让全站搜索与海报秒开（不阻塞首屏）
      setTimeout(async () => {
        for (const m of manifest.years) {
          if (state.cache.has(m.year)) continue;
          await loadYear(m.year).catch(() => {});
        }
      }, 1200);
      // 调试 / 折腾入口
      window.__animeLists = {
        state,
        updateOnline,
        makePoster,
        evaluate,
        dataAgeDays,
        loadYear,
        refreshAll,
        recomputeStats,
        entriesForYear,
      };
    } catch (err) {
      console.error(err);
      document.body.insertAdjacentHTML(
        "beforeend",
        `<div class="empty">数据载入失败：${esc(err.message)}<br><br>请确认 index.html 与 <code>data/</code> 目录在一起，并重新生成数据（<code>python scripts/build_data.py</code>）。</div>`
      );
    }
  }

  init();
})();
