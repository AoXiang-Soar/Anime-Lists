"""Fetch every seasonal anime from AniList (1990 -> now).

Usage:
    python scripts/fetch_anilist.py            # fetch missing years
    python scripts/fetch_anilist.py --year 2024 --force

Raw results are cached as data/raw/anilist_<year>.json so the build can be
re-run without hitting the API again.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
API = "https://graphql.anilist.co"

START_YEAR = 1990
END_YEAR = 2026

# Seasonal anime formats. Movies and music videos are intentionally excluded.
FORMATS = ["TV", "TV_SHORT", "ONA", "OVA", "SPECIAL"]

QUERY = """
query ($year: Int, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { currentPage hasNextPage total }
    media(
      type: ANIME
      seasonYear: $year
      format_in: [TV, TV_SHORT, ONA, OVA, SPECIAL]
      genre_not_in: ["Hentai"]
    ) {
      id
      idMal
      title { romaji english native }
      synonyms
      format
      status
      episodes
      duration
      season
      seasonYear
      startDate { year month day }
      endDate { year month day }
      genres
      isAdult
      averageScore
      meanScore
      popularity
      favourites
      source
      countryOfOrigin
      coverImage { extraLarge large color }
      bannerImage
      studios(isMain: true) { nodes { name } }
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""


def request_page(year: int, page: int, per_page: int = 50, attempts: int = 6) -> dict:
    payload = json.dumps(
        {"query": QUERY, "variables": {"year": year, "page": page, "perPage": per_page}}
    ).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            API,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "anime-season-lists/1.0 (dataset build)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if "errors" in body and body["errors"]:
                raise RuntimeError(f"AniList error: {body['errors'][:1]}")
            return body["data"]["Page"]
        except urllib.error.HTTPError as exc:  # rate limited / server error
            last_error = exc
            wait = min(60.0, 3.0 * (2**attempt)) + random.uniform(0, 1.5)
            print(f"  HTTP {exc.code} on year {year} page {page}; retry in {wait:.1f}s", flush=True)
            time.sleep(wait)
        except Exception as exc:  # noqa: BLE001 - network flake
            last_error = exc
            wait = 2.0 * (attempt + 1)
            print(f"  {type(exc).__name__} on year {year} page {page}; retry in {wait:.1f}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Failed year {year} page {page}: {last_error}")


def fetch_year(year: int) -> list[dict]:
    media: list[dict] = []
    page = 1
    while True:
        result = request_page(year, page)
        media.extend(result["media"])
        print(f"  {year} page {page}: +{len(result['media'])} (total {len(media)})", flush=True)
        if not result["pageInfo"]["hasNextPage"]:
            break
        page += 1
        time.sleep(2.4)
    return media


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, action="append", help="only fetch this year (repeatable)")
    parser.add_argument("--force", action="store_true", help="refetch years already cached")
    parser.add_argument("--start", type=int, default=START_YEAR)
    parser.add_argument("--end", type=int, default=END_YEAR)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    years = args.year or list(range(args.start, args.end + 1))

    for year in years:
        target = RAW_DIR / f"anilist_{year}.json"
        if target.exists() and not args.force:
            print(f"{year}: cached, skipping", flush=True)
            continue
        print(f"{year}: fetching...", flush=True)
        media = fetch_year(year)
        target.write_text(
            json.dumps({"year": year, "fetchedAt": int(time.time()), "media": media}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"{year}: saved {len(media)} entries", flush=True)
        time.sleep(1.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
