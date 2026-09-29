"""Paginate every TV anime whose start date falls in a year and compare with
the dataset (used to sanity-check coverage per year)."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from anime_data import load_year  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
API = "https://graphql.anilist.co"

QUERY = """
query ($page: Int, $from: FuzzyDateInt, $to: FuzzyDateInt) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(type: ANIME, startDate_greater: $from, startDate_lesser: $to, format: TV) {
      id
      title { romaji native }
      episodes
      duration
      season
      seasonYear
      countryOfOrigin
      isAdult
      genres
    }
  }
}
"""


def ask(page: int, year: int) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps(
            {"query": QUERY, "variables": {"page": page, "from": year * 10000 + 101, "to": year * 10000 + 1231}}
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "anime-season-lists/1.0 (coverage probe)",
        },
    )
    for attempt in range(5):
        try:
            body = json.loads(urllib.request.urlopen(req, timeout=40).read())
            if "errors" in body:
                raise RuntimeError(body["errors"])
            return body["data"]["Page"]
        except urllib.error.HTTPError as exc:
            wait = 6 * (attempt + 1)
            print(f"  HTTP {exc.code}, retry in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit("giving up")


def main() -> None:
    for year in [int(a) for a in sys.argv[1:]] or [2010]:
        items: list[dict] = []
        page = 1
        while True:
            res = ask(page, year)
            items.extend(res["media"])
            if not res["pageInfo"]["hasNextPage"]:
                break
            page += 1
            time.sleep(2.6)
        known = {e["id"] for e in load_year(year)}
        missing = [m for m in items if m["id"] not in known]
        jp = [m for m in items if m["countryOfOrigin"] == "JP"]
        print(f"\n{year}: startDate 里 TV 共 {len(items)} 部（日本 {len(jp)} 部），不在数据集里 {len(missing)} 部")
        for m in missing:
            print(
                f"   - {m['title']['romaji'][:44]:44s} ep={m['episodes']} dur={m['duration']} "
                f"season={m['season']}/{m['seasonYear']} origin={m['countryOfOrigin']} adult={m['isAdult']}"
            )
        time.sleep(2.0)


if __name__ == "__main__":
    main()
