"""Merge the raw AniList dump with bangumi-data and emit the site dataset.

数据以 .js 形式输出（`window.ANIME_XXX = ...`），这样整个站点可以直接双击
index.html 打开，不需要任何本地服务器（file:// 下 fetch 会被浏览器拦截，
但 <script src> 不会）。

Output:
    data/index.js        - manifest (years, season labels, counts, build time)
    data/catalog.js      - fixed-order index used by stats / heat map / share links
    data/search.js       - lazy-loaded search index
    data/<year>.js       - one compact file per year

Entry schema (compact keys keep the payload small):
    id  AniList id                t   titles {zh, zhAlt, romaji, en, native}
    f   format (TV/TV_SHORT/ONA/OVA/SPECIAL)
    ep  episodes                  du  duration in minutes
    y   year                      s   season (WINTER/SPRING/SUMMER/FALL)
    d   start date (YYYY-MM-DD)   e   end date (YYYY-MM-DD)
    g   genres                    k   content flags
    sc  AniList average score     po  popularity    fa  favourites
    cov cover image url           col cover dominant colour
    stu main studio               src source material
    mal MyAnimeList id            bgm bangumi.tv subject id
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"

def write_js(path: Path, expr: str, payload) -> int:
    """写入 `window.<expr> = <json>;`，expr 形如 ANIME_DATA['1990']。"""
    prefix = "window.ANIME_DATA=window.ANIME_DATA||{};\n" if expr.startswith("ANIME_DATA[") else ""
    text = prefix + f"window.{expr}=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))

SEASON_BY_MONTH = {
    1: "WINTER", 2: "WINTER", 3: "WINTER",
    4: "SPRING", 5: "SPRING", 6: "SPRING",
    7: "SUMMER", 8: "SUMMER", 9: "SUMMER",
    10: "FALL", 11: "FALL", 12: "FALL",
}

SEASON_ORDER = ["WINTER", "SPRING", "SUMMER", "FALL"]
FORMAT_ORDER = ["TV", "TV_SHORT", "ONA", "OVA", "SPECIAL"]

# Formats that describe an actual broadcast/streaming series rather than a
# bonus episode or a promo short.
SERIES_FORMATS = {"TV", "ONA", "TV_SHORT"}

# Must stay identical to SEARCH_DROP in app.js: characters ignored when
# normalising titles for the search index.
SEARCH_DROP = " \u3000·・,，、.。:：;；!！?？'\"“”‘’`-–—_/\\|()（）[]【】「」『』<>《》&×～~+＋*#^"

# 少数 AniList 标了成人向、但实际是正常 TV 播出、剧情完整、集数标准的作品，
# 需要保留（用户明确要求「剧情完整、集数标准的肉番」要收录）。
ADULT_KEEP = {
    1060,    # おるちゅばんエビちゅ / Oruchuban Ebichu (1999, TV, 24 集)
}


def search_key(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch not in SEARCH_DROP)


# 只保留集数明确大于 8 集、且已经播完的作品：
#   - 12 / 24 集的标准季番
#   - 集数略有出入的季度番
#   - 长篇年番（可用前端筛选隐藏）
MIN_EPISODES = 9          # > 8 集
AIRING_STATUSES = {"RELEASING", "NOT_YET_RELEASED"}


def iso_date(node: dict | None) -> str:
    if not node or not node.get("year"):
        return ""
    return "{year:04d}-{month:02d}-{day:02d}".format(
        year=node["year"], month=node.get("month") or 1, day=node.get("day") or 1
    )


def load_bangumi() -> dict[int, dict]:
    path = RAW / "bangumi_data.json"
    if not path.exists():
        print("! bangumi_data.json missing - Chinese titles will be unavailable")
        return {}, {}
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    index: dict[int, dict] = {}
    by_title: dict[str, list[str]] = {}
    for item in items:
        site_ids = {s["site"]: s.get("id") for s in item.get("sites", []) if s.get("id")}
        translate = item.get("titleTranslate") or {}
        zh = [t for t in translate.get("zh-Hans", []) if t]
        key_title = normalize_title(item.get("title", ""))
        if key_title and zh:
            by_title.setdefault(key_title, []).extend(zh)
        anilist_id = site_ids.get("aniList")
        if not anilist_id:
            continue
        try:
            key = int(anilist_id)
        except (TypeError, ValueError):
            continue
        index[key] = {
            "zh": zh,
            "bgm": site_ids.get("bangumi"),
            "mal": site_ids.get("mal"),
            "type": item.get("type"),
            "begin": item.get("begin", ""),
            "title": item.get("title", ""),
        }
    print(f"bangumi index: {len(index)} anilist ids, {len(by_title)} titles")
    return index, by_title


def normalize_title(text: str) -> str:
    """Loose key for cross-database title matching."""
    drop = " \u3000・·,，.。:：!！?？~～'\"“”‘’-_/\\()（）[]【】「」『』&×"
    out = []
    for ch in (text or "").lower():
        if ch in drop:
            continue
        out.append(ch)
    return "".join(out)


def classify(media: dict) -> dict:
    """Content flags used by the UI filters."""
    genres = media.get("genres") or []
    episodes = media.get("episodes") or 0
    duration = media.get("duration") or 0
    fmt = media.get("format") or "TV"
    flags = []
    if "Ecchi" in genres:
        flags.append("ecchi")
    if media.get("isAdult"):
        flags.append("adult")
    if fmt == "TV_SHORT" or (duration and duration < 15):
        flags.append("short")
    if duration and duration >= 100:
        flags.append("long_episode")
    if episodes >= 45:
        flags.append("long_run")
    if fmt in {"OVA", "SPECIAL"}:
        flags.append("extra")
    if media.get("status") == "NOT_YET_RELEASED" or media.get("status") == "RELEASING":
        flags.append("airing" if media.get("status") == "RELEASING" else "upcoming")
    if not episodes and media.get("nextAiringEpisode"):
        flags.append("ongoing")
    return {"genres": genres, "flags": flags, "format": fmt, "episodes": episodes, "duration": duration}


def is_hentai(media: dict) -> bool:
    genres = {g.lower() for g in (media.get("genres") or [])}
    if "hentai" in genres:
        return True
    # AniList 里有一部分成人向作品没有打 Hentai 标签（多为 ONA/OVA 短篇）。
    # 判定标准：只有「TV 播出 + 单集 ≥20 分钟 + ≥9 集」的剧情向肉番才保留，
    # 其余成人向一律视为里番排除。
    if media.get("isAdult") and media["id"] not in ADULT_KEEP:
        fmt = media.get("format")
        duration = media.get("duration") or 0
        episodes = media.get("episodes") or 0
        if fmt != "TV" or duration < 20 or episodes < 9:
            return True
    return False


def convert(media: dict, bangumi: dict[int, dict], by_title: dict[str, list[str]] | None = None) -> dict | None:
    if is_hentai(media):
        return None
    # 只要日漫：AniList 里混进来的国创 / 韩番 / 台番一律排除。
    origin = media.get("countryOfOrigin")
    if origin and origin != "JP":
        return None
    # 未完结 / 未开播的新番不收
    if (media.get("status") or "") in AIRING_STATUSES:
        return None
    # 只收 9 集以上（即「大于 8 集」）的作品
    if (media.get("episodes") or 0) < MIN_EPISODES:
        return None
    info = classify(media)
    start = media.get("startDate") or {}
    year = media.get("seasonYear") or start.get("year")
    if not year:
        return None
    season = media.get("season")
    if not season and start.get("month"):
        season = SEASON_BY_MONTH.get(start["month"])
    if not season:
        # Unknown month: bucket into the season AniList would use by default.
        season = "WINTER"

    bgm = bangumi.get(media["id"], {})
    titles = media.get("title") or {}
    zh_list = list(bgm.get("zh") or [])
    romaji = titles.get("romaji") or titles.get("english") or titles.get("native") or ""
    if not zh_list and by_title:
        # 二级匹配：用日文原名去 bangumi-data 里找（很多老番没有 aniList 站点链接）
        for candidate in (titles.get("native"), titles.get("romaji"), *([])):
            if not candidate:
                continue
            hit = by_title.get(normalize_title(candidate))
            if hit:
                zh_list = list(dict.fromkeys(hit))
                break

    studios = media.get("studios") or {}
    nodes = studios.get("nodes") or []
    cover = media.get("coverImage") or {}

    entry = {
        "id": media["id"],
        "t": {
            "zh": zh_list[0] if zh_list else "",
            "zhAlt": zh_list[1:],
            "romaji": romaji,
            "en": titles.get("english") or "",
            "native": titles.get("native") or "",
        },
        "f": info["format"],
        "ep": info["episodes"],
        "du": info["duration"],
        "y": year,
        "s": season,
        "d": iso_date(start),
        "e": iso_date(media.get("endDate")),
        "g": info["genres"],
        "k": info["flags"],
        "sc": media.get("averageScore") or 0,
        "po": media.get("popularity") or 0,
        "fa": media.get("favourites") or 0,
        "cov": cover.get("large") or cover.get("extraLarge") or "",
        "col": cover.get("color") or "",
        "stu": nodes[0]["name"] if nodes else "",
        "src": (media.get("source") or "").replace("_", " ").title(),
        "mal": media.get("idMal") or 0,
        "bgm": int(bgm["bgm"]) if bgm.get("bgm") else 0,
    }
    if not entry["cov"]:
        return None
    return entry


def main() -> int:
    bangumi, by_title = load_bangumi()
    OUT.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(RAW.glob("anilist_*.json"))
    if not raw_files:
        print("no raw data found; run scripts/fetch_anilist.py first")
        return 1

    years: dict[int, list[dict]] = {}
    seen: set[int] = set()
    dropped = 0
    for path in raw_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        year = payload["year"]
        bucket: list[dict] = []
        for media in payload["media"]:
            if media["id"] in seen:
                continue
            seen.add(media["id"])
            entry = convert(media, bangumi, by_title)
            if entry is None:
                dropped += 1
                continue
            bucket.append(entry)
        years[year] = bucket

    manifest_years = []
    total = 0
    for year in sorted(years):
        bucket = years[year]
        if not bucket:
            continue
        bucket.sort(key=lambda e: (e["s"], e["d"] or "9999", -e["po"], e["id"]))
        write_js(OUT / f"{year}.js", f"ANIME_DATA['{year}']", bucket)
        counts = Counter(e["s"] for e in bucket)
        total += len(bucket)
        manifest_years.append(
            {
                "year": year,
                "count": len(bucket),
                "seasons": {s: counts.get(s, 0) for s in ("WINTER", "SPRING", "SUMMER", "FALL")},
                "withZh": sum(1 for e in bucket if e["t"]["zh"]),
            }
        )
        zh = sum(1 for e in bucket if e["t"]["zh"])
        print(f"{year}: {len(bucket):4d} entries ({zh} with zh title)")

    manifest = {
        "generatedAt": int(time.time()),
        "source": "AniList GraphQL (CC BY-NC-SA 4.0) + bangumi-data (Chinese titles)",
        "years": manifest_years,
        "total": total,
    }
    write_js(OUT / "index.js", "ANIME_INDEX", manifest)

    # ---- catalog: one fixed-order record per title, used for stats, the
    # heat map, search and the bitmask share links (no per-year fetch needed).
    genres = sorted({g for bucket in years.values() for e in bucket for g in e["g"]})
    genre_bit = {g: 1 << i for i, g in enumerate(genres)}

    ordered = [e for year in sorted(years) for e in years[year]]
    catalog = {
        "generatedAt": manifest["generatedAt"],
        "genres": genres,
        "formats": FORMAT_ORDER,
        "ids": [e["id"] for e in ordered],
        "years": [e["y"] for e in ordered],
        "seasons": "".join(str(SEASON_ORDER.index(e["s"])) for e in ordered),
        "fmts": "".join(str(FORMAT_ORDER.index(e["f"])) for e in ordered),
        "eps": [e["ep"] for e in ordered],
        "dur": [e["du"] for e in ordered],
        "gmask": [
            sum(genre_bit[g] for g in e["g"] if g in genre_bit) for e in ordered
        ],
        "kinds": "".join(
            ("e" if "ecchi" in e["k"] else "-")
            + ("a" if "adult" in e["k"] else "-")
            + ("s" if "short" in e["k"] else "-")
            + ("x" if "extra" in e["k"] else "-")
            + ("l" if "long_run" in e["k"] else "-")
            for e in ordered
        ),
    }
    write_js(OUT / "catalog.js", "ANIME_CATALOG", catalog)
    print(
        "catalog: {n} titles, {kb:.0f} KB".format(
            n=len(ordered), kb=(OUT / "catalog.js").stat().st_size / 1024
        )
    )

    # 搜索索引单独放一个文件，首屏之后再懒加载，避免拖慢第一眼。
    search = [
        search_key(
            "".join(
                part
                for part in (
                    e["t"]["zh"],
                    *e["t"]["zhAlt"],
                    e["t"]["romaji"],
                    e["t"]["en"],
                    e["t"]["native"],
                )
                if part
            )
        )
        for e in ordered
    ]
    write_js(OUT / "search.js", "ANIME_SEARCH", search)
    print(f"search index: {(OUT / 'search.js').stat().st_size / 1024:.0f} KB")
    print(f"\ntotal {total} entries across {len(manifest_years)} years, dropped {dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
