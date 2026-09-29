"""Spot-check that well-known series are present in the built dataset."""

from __future__ import annotations

from anime_data import load_all

WANTED = [
    "進撃の巨人",
    "鬼滅の刃",
    "呪術廻戦",
    "ぼっち・ざ・ろっく",
    "葬送のフリーレン",
    "ONE PIECE",
    "SPY×FAMILY",
    "涼宮ハルヒ",
    "コードギアス",
    "鋼の錬金術師",
    "あの日見た花",
    "Re:ゼロ",
    "この素晴らしい世界",
    "ワンパンマン",
    "化物語",
    "とらドラ",
    "CLANNAD",
    "STEINS;GATE",
    "四月は君の嘘",
    "ヴァイオレット",
    "カウボーイビバップ",
    "少女革命ウテナ",
    "serial experiments lain",
    "serial experiments レイン",
    "おるちゅばんエビちゅ",
    "ピーター・グリルと賢者の時間",
    "回復術士のやり直し",
    "異世界迷宮でハーレムを",
    "終末のハーレム",
    "ヨスガノソラ",
]


def main() -> None:
    entries = load_all()
    print(f"dataset entries: {len(entries)}")
    missing = 0
    for name in WANTED:
        key = name.lower()
        hits = [
            e
            for e in entries
            if key in (e["t"]["native"] or "").lower()
            or key in (e["t"]["romaji"] or "").lower()
            or key in (e["t"]["zh"] or "").lower()
            or any(key in alt.lower() for alt in e["t"]["zhAlt"])
        ]
        if not hits:
            missing += 1
            print(f"  MISS {name}")
            continue
        best = max(hits, key=lambda e: e["po"])
        print(
            "  OK   {name:24s} -> {y} {s:6s} {title} ({fmt}, {ep} 话, {n} 个相关条目)".format(
                name=name,
                y=best["y"],
                s=best["s"],
                title=(best["t"]["zh"] or best["t"]["romaji"])[:30],
                fmt=best["f"],
                ep=best["ep"] or "?",
                n=len(hits),
            )
        )
    print(f"missing: {missing}/{len(WANTED)}")


if __name__ == "__main__":
    main()
