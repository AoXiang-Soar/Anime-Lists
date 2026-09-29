"""Check whether seasonYear-based filtering misses titles that a plain
start-date filter finds (AniList's pageInfo.total is unreliable, so this
paginates and compares id sets).

Usage: python scripts/probe_missing.py 2010 1998 2024
"""

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
    media(
      type: ANIME
      startDate_greater: $from
      startDate_lesser: $to
      format_in: [TV, TV_SHORT, ONA, OVA, SPECIAL]
      genre_not_in: ["Hentai"]
    ) {
      id
      title { romaji native }
      format
      episodes
      season
      seasonYear
      startDate { year month day }
      isAdult
    }
  }
}
"""


def ask(variables: dict) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
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
            wait = 5 * (attempt + 1)
            print(f"  HTTP {exc.code}, retry in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit("giving up")


def fetch_year(year: int) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        res = ask({"page": page, "from": year * 10000 + 101, "to": year * 10000 + 1231})
        out.extend(res["media"])
        if not res["pageInfo"]["hasNextPage"]:
            break
        page += 1
        time.sleep(2.6)
    return out


def main() -> None:
    years = [int(a) for a in sys.argv[1:]] or [2010]
    for year in years:
        known = {e["id"] for e in load_year(year)}
        found = fetch_year(year)
        missing = [m for m in found if m["id"] not in known]
        print(f"\n{year}: startDate 查到 {len(found)} 条，我们已有 {len(known)} 条，缺 {len(missing)} 条")
        for m in missing[:25]:
            sd = m["startDate"]
            print(
                "   - {romaji} | {fmt} | ep={ep} | start={y}-{mo}-{d} | season={s}/{sy} | adult={ad}".format(
                    romaji=(m["title"]["romaji"] or m["title"]["native"])[:46],
                    fmt=m["format"],
                    ep=m["episodes"],
                    y=sd["year"],
                    mo=sd["month"],
                    d=sd["day"],
                    s=m["season"],
                    sy=m["seasonYear"],
                    ad=m["isAdult"],
                )
            )
        time.sleep(2.0)


if __name__ == "__main__":
    main()
