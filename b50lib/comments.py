"""Generate timing-ready commentary templates from a B50 export."""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .concat import media_duration
from .data import load_charts
from .paths import ROOT, USER_DATA, ffmpeg_path


def downloaded_video(chart: dict, videos: Path) -> Path | None:
    """Find a chart download without depending on its old or new B50 position."""
    matches = sorted(videos.glob(f"*_{chart['group']}_{chart['difficulty']}_{chart['idx']}_*.mp4"))
    return matches[0] if matches else None


def comment_template(charts: Sequence[dict], videos: Path, ffmpeg: str) -> dict[str, dict[str, float | int | str]]:
    """Return blank comments with a 0-to-video-duration interval for every chart."""
    grouped = {
        group: sorted((chart for chart in charts if chart["group"] == group), key=lambda chart: chart["group_number"])
        for group in ("best", "new")
    }
    missing = [chart["title"] for group in grouped.values() for chart in group if not downloaded_video(chart, videos)]
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} chart download(s): {', '.join(missing)}")
    return {
        f"{group}:{chart['group_number']}": {
            "comment": "",
            "clip_start": 0,
            "clip_end": media_duration(downloaded_video(chart, videos), ffmpeg),
            "recommendation": 0,
            "pc": 0,
        }
        for group in ("best", "new")
        for chart in grouped[group]
    }


def write_template(output: Path, charts: Sequence[dict], videos: Path, force: bool) -> Path:
    """Write a template without replacing an existing editable file by default."""
    if output.exists() and not force:
        raise FileExistsError(f"{output} already exists; use --force to replace it")
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found; it is needed to read downloaded video durations")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(comment_template(charts, videos, ffmpeg), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a B50 commentary template from downloaded video durations.")
    parser.add_argument("command", choices=("init",))
    parser.add_argument("--data", type=Path, default=USER_DATA, help="B50 input path (default: user/data.json)")
    parser.add_argument("--videos", type=Path, default=ROOT / "downloads", help="Downloaded chart-video folder")
    parser.add_argument("--output", type=Path, default=ROOT / "comments.json", help="Template output path")
    parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    args = parser.parse_args(argv)
    result = write_template(args.output, load_charts(args.data), args.videos, args.force)
    print(f"Generated {result}")
