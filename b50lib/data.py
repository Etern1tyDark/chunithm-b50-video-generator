"""B50 input, metadata, jacket, and commentary helpers."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .paths import DEFAULT_JACKET


def decode_mojibake(value: str) -> str:
    """Repair UTF-8 text accidentally decoded as Windows-1252 or Latin-1."""
    for encoding in ("cp1252", "latin1"):
        try:
            repaired = value.encode(encoding).decode("utf-8")
            if repaired != value:
                return repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return value


def load_charts(path: Path) -> list[dict[str, Any]]:
    """Load New then Best, descending by each array's original rank."""
    source = json.loads(path.read_text(encoding="utf-8"))
    charts = [
        {
            **chart,
            "title": decode_mojibake(str(chart["title"])),
            "group": group,
            "section": group,
            "group_number": group_number,
        }
        for group in ("new", "best")
        for group_number, chart in reversed(list(enumerate(source.get(group, []), 1)))
    ]
    if not charts:
        raise ValueError("No charts found. Expected 'best' and/or 'new' arrays.")
    return charts


def metadata_by_id(path: Path) -> dict[int, dict[str, Any]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {entry["id_otoge"]: entry for entry in records if entry.get("id_otoge") is not None}


def load_comments(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("comments JSON must be an object of card keys and text")
    configs: dict[str, dict[str, Any]] = {}
    for key, entry in value.items():
        if isinstance(entry, str):
            configs[str(key)] = {"comment": entry}
        elif isinstance(entry, dict):
            configs[str(key)] = entry
        else:
            raise ValueError(f"comments JSON entry {key!r} must be text or an object")
    return configs


def card_config(configs: dict[str, dict[str, Any]], chart: dict[str, Any], group_number: int) -> dict[str, Any]:
    """Song-id settings override an OLD/NEW ordinal setting."""
    original_number = int(chart.get("group_number", group_number))
    return configs.get(str(chart["idx"]), configs.get(f"{chart['group']}:{original_number}", {}))


def jacket_path(chart: dict[str, Any], metadata: dict[int, dict[str, Any]], jackets: Path) -> Path | None:
    entry = metadata.get(chart["idx"])
    if not entry or not entry.get("image_code_otoge"):
        return None
    return jackets / f"{chart['idx']}_{entry['image_code_otoge']}"


def fallback_jacket() -> Path:
    return DEFAULT_JACKET


def fetch_jackets(charts: list[dict[str, Any]], metadata: dict[int, dict[str, Any]], jackets: Path,
                  delay: float, requests_module: Any, image_type: Any) -> None:
    """Cache official jackets without making rendering depend on a web request."""
    jackets.mkdir(parents=True, exist_ok=True)
    for position, chart in enumerate(charts, 1):
        target = jacket_path(chart, metadata, jackets)
        if not target:
            print(f"[{position:02}] No metadata jacket: {chart['title']}")
            continue
        if target.exists() and target.stat().st_size > 0:
            print(f"[{position:02}] Cached: {chart['title']}")
            continue
        url = f"https://otoge-db.net/chunithm/jacket/{target.name.split('_', 1)[1]}"
        try:
            response = requests_module.get(url, timeout=30)
            response.raise_for_status()
            from io import BytesIO
            image_type.open(BytesIO(response.content)).convert("RGB").save(target, "JPEG", quality=95)
            print(f"[{position:02}] Downloaded: {chart['title']}")
        except Exception as error:
            print(f"[{position:02}] FAILED: {chart['title']}: {error}")
        time.sleep(delay)


def level_info(chart: dict[str, Any], metadata: dict[int, dict[str, Any]], difficulty_index: dict[str, int]) -> tuple[str, float]:
    entry = metadata.get(chart["idx"], {})
    difficulty = difficulty_index.get(chart["difficulty"], 3)
    for info in entry.get("charts_info", []):
        if info.get("difficulty") == difficulty:
            level = info.get("level_latest") or info.get("level_cn") or chart["difficulty"]
            constant = info.get("level_value_latest") or info.get("level_value_cn") or 0
            return str(level), float(constant)
    return chart["difficulty"], 0.0


def calculate_rating(constant: float, score: int) -> float:
    if constant <= 0:
        return 0.0
    tiers = ((1_009_000, None, 2.15), (1_007_500, 1_009_000, 2.00), (1_005_000, 1_007_500, 1.50), (1_000_000, 1_005_000, 1.00), (990_000, 1_000_000, .60), (975_000, 990_000, .00))
    for minimum, maximum, base in tiers:
        if score >= minimum and (maximum is None or score < maximum):
            if minimum == 1_009_000:
                return round(constant + base, 2)
            step = 50 if minimum == 1_005_000 else 100 if minimum >= 1_000_000 else 250
            cap = 2.15 if minimum == 1_007_500 else 2.00 if minimum == 1_005_000 else 1.50 if minimum == 1_000_000 else 1.00 if minimum == 990_000 else .60
            return round(constant + base + min(((score - minimum) // step) * .01, cap - base), 2)
    return round(constant - 1.5 if score >= 950_000 else constant - 3 if score >= 925_000 else constant - 5 if score >= 900_000 else max(0, (constant - 5) / 2), 2)
