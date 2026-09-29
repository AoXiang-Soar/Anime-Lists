"""Read the generated site data without a server (data/*.js are plain JS
assignments wrapping JSON, which keeps the page file:// friendly)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

def load_var(path: Path):
    """把 `window.X=<json>;`（前面可能还有一行初始化语句）解析成 Python 对象。"""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith("window.")]
    if not lines:
        raise ValueError(f"cannot parse {path}")
    payload = lines[-1].split("=", 1)[1].strip().rstrip(";")
    return json.loads(payload)


def load_year(year: int) -> list[dict]:
    return load_var(DATA / f"{year}.js")


def load_all() -> list[dict]:
    out: list[dict] = []
    for path in sorted(DATA.glob("[12][0-9][0-9][0-9].js")):
        out.extend(load_var(path))
    return out


def load_manifest() -> dict:
    return load_var(DATA / "index.js")


def load_catalog() -> dict:
    return load_var(DATA / "catalog.js")
