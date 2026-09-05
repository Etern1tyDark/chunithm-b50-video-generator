#!/usr/bin/env python3
"""Find and download CHUNITHM chart videos for a Best 50 compilation.

This tool is intentionally independent from mai-gen-videob50: it consumes the
international-server B50 export directly and produces plain MP4 files.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from b50lib.paths import ROOT, USER_DATA, enable_runtime_packages, ffmpeg_path as local_ffmpeg_path
from b50lib.data import load_charts as load_b50_charts

enable_runtime_packages()

try:
    from pytubefix import Search, YouTube
except ImportError as error:
    raise SystemExit(
        "pytubefix is unavailable. Run b50-gen\\start.bat, or install it with "
        "python -m pip install pytubefix.\n" + str(error)
    )


def load_charts(path: Path) -> list[dict[str, Any]]:
    return load_b50_charts(path)


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def score_result(video_title: str, chart: dict[str, Any]) -> int:
    title = normalise(video_title)
    target = normalise(chart["title"])
    difficulty = chart["difficulty"].casefold()
    score = 0
    if target and target in title:
        score += 70
    elif len(target) >= 4 and (target in title or title in target):
        score += 35
    if "chunithm" in video_title.casefold() or "チュウニズム" in video_title:
        score += 20
    if difficulty in video_title.casefold():
        score += 15
    if any(word in video_title for word in ("譜面", "chart", "play")):
        score += 5
    return score


def chart_video_version(video_title: str) -> float:
    """Read the leading `(9.0)` version marker used by CHUNITHM video uploads."""
    match = re.match(r"\s*[\(\[]\s*(\d+(?:\.\d+)?)\s*[\)\]]", video_title)
    return float(match.group(1)) if match else 0.0


def queries(chart: dict[str, Any]) -> list[str]:
    title = chart["title"]
    difficulty = chart["difficulty"]
    return [
        f"{title} {difficulty} CHUNITHM chart",
        f"{title} {difficulty} CHUNITHM 譜面確認",
        f"{title} CHUNITHM",
    ]


def _parse_length_seconds(length_text: str) -> int | None:
    """Convert a YouTube duration string like '2:43' or '1:02:15' to seconds."""
    try:
        parts = [int(p) for p in length_text.strip().split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except (ValueError, AttributeError):
        pass
    return None


def _extract_video_renderers(raw: dict[str, Any], results: list | None = None, depth: int = 0) -> list[dict[str, Any]]:
    """Recursively extract videoRenderer dicts from the raw innertube search response."""
    if results is None:
        results = []
    if depth > 15:
        return results
    if isinstance(raw, dict):
        if "videoRenderer" in raw:
            results.append(raw["videoRenderer"])
            return results
        for v in raw.values():
            _extract_video_renderers(v, results, depth + 1)
    elif isinstance(raw, list):
        for item in raw:
            _extract_video_renderers(item, results, depth + 1)
    return results


def search_chart(chart: dict[str, Any], results_per_query: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for query in queries(chart):
        try:
            s = Search(query)
            # Trigger the raw innertube fetch without accessing YouTube object
            # properties (which make individual bot-detectable requests per video).
            s.fetch_query()
            raw = s._initial_results or {}
            renderers = _extract_video_renderers(raw)[:results_per_query]
        except Exception as error:
            print(f"  Search failed for {query!r}: {error}", file=sys.stderr)
            continue
        for vr in renderers:
            try:
                video_id = vr.get("videoId", "")
                if not video_id or video_id in seen:
                    continue
                title_obj = vr.get("title", {})
                if isinstance(title_obj, dict):
                    runs = title_obj.get("runs")
                    title = runs[0]["text"] if runs else title_obj.get("simpleText", "")
                else:
                    title = str(title_obj)
                if not title:
                    continue
                length_text = vr.get("lengthText", {})
                if isinstance(length_text, dict):
                    length_text = length_text.get("simpleText", "")
                length_seconds = _parse_length_seconds(length_text)
                candidate = {
                    "id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": title,
                    "length_seconds": length_seconds,
                    "score": score_result(title, chart),
                    "version": chart_video_version(title),
                }
            except Exception as error:
                print(f"  Skipping result: {error}", file=sys.stderr)
                continue
            seen.add(video_id)
            candidates.append(candidate)
    # Match correctness comes first; among equally good chart matches, use the
    # newest/largest uploader version marker, e.g. `(9.0)` before `(8.0)`.
    return sorted(candidates, key=lambda item: (item["score"], item["version"]), reverse=True)


def build_matches(charts: list[dict[str, Any]], args: argparse.Namespace,
                  matches: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    matches = matches or []
    initial_count = len(matches)
    for number, chart in enumerate(charts, start=initial_count + 1):
        print(f"[{number:02}/{len(charts)}] {chart['difficulty']}: {chart['title']}")
        candidates = search_chart(chart, args.results)
        chosen = candidates[0] if candidates else None
        matches.append({
            "chart": chart,
            "selected": chosen,
            "candidates": candidates,
            "status": "selected" if chosen else "not_found",
        })
        # Keep the completed work even if YouTube fails later in the run.
        args.matches.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
        if chosen:
            print(f"  -> {chosen['title']} ({chosen['score']} points)")
        else:
            print("  -> no result")
        time.sleep(args.delay)
    return matches


def output_stem(item: dict[str, Any], number: int) -> str:
    chart = item["chart"]
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", chart["title"]).strip(" .")
    return f"{number:02d}_{chart['section']}_{chart['difficulty']}_{chart['idx']}_{title}"


def ffmpeg_path() -> str | None:
    return local_ffmpeg_path()


def choose_video_stream(yt: YouTube, maximum_height: int, preferred_fps: int = 60):
    """Prefer 1080p60 (or the requested height/FPS), then degrade gracefully."""
    streams = list(yt.streams.filter(adaptive=True, only_video=True, file_extension="mp4"))
    if not streams:
        return None

    def height(stream) -> int:
        match = re.match(r"(\d+)", str(stream.resolution or ""))
        return int(match.group(1)) if match else 0

    def fps(stream) -> int:
        return int(stream.fps or 0)

    # Exact target first: 1080p60 by default.
    exact = [stream for stream in streams if height(stream) == maximum_height and fps(stream) >= preferred_fps]
    if exact:
        return max(exact, key=fps)

    # Prefer the requested height even if only 30 fps exists, then the highest
    # available resolution at or below it. HFR wins ties.
    at_target = [stream for stream in streams if height(stream) == maximum_height]
    if at_target:
        return max(at_target, key=fps)
    below_target = [stream for stream in streams if height(stream) <= maximum_height]
    return max(below_target or streams, key=lambda stream: (height(stream), fps(stream)))


def download_one(item: dict[str, Any], number: int, destination: Path, maximum_height: int) -> None:
    selected = item.get("selected")
    if item.get("status") not in ("selected", "approved") or not selected:
        return
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{output_stem(item, number)}.mp4"
    if output.exists() and output.stat().st_size > 0:
        print(f"[{number:02}] Already exists: {output.name}")
        return
    print(f"[{number:02}] Downloading: {selected['title']}")
    yt = YouTube(selected["url"], client="ANDROID_VR")
    video = choose_video_stream(yt, maximum_height)
    audio = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
    if not video or not audio:
        raise RuntimeError("No compatible adaptive MP4 video/audio streams found")
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("Adaptive streams require ffmpeg, but ffmpeg.exe was not found")
    temp_video = destination / f".{number:02}_video.mp4"
    temp_audio = destination / f".{number:02}_audio.mp4"
    try:
        video.download(output_path=str(destination), filename=temp_video.name)
        audio.download(output_path=str(destination), filename=temp_audio.name)
        subprocess.run([ffmpeg, "-y", "-i", str(temp_video), "-i", str(temp_audio), "-c", "copy", str(output)], check=True)
    finally:
        temp_video.unlink(missing_ok=True)
        temp_audio.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download CHUNITHM Best 50 chart videos from YouTube.")
    parser.add_argument("command", choices=("search", "download", "all"))
    parser.add_argument("--data", type=Path, default=USER_DATA, help="B50 input path (default: user/data.json)")
    parser.add_argument("--matches", type=Path, default=ROOT / "matches.json", help="Editable matches file")
    parser.add_argument("--output", type=Path, default=ROOT / "downloads", help="Video output folder")
    parser.add_argument("--results", type=int, default=4, help="Candidates per search query")
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds between charts")
    parser.add_argument("--limit", type=int, help="Only process the first N charts (useful for a test run)")
    parser.add_argument("--fresh", action="store_true", help="Ignore an existing checkpoint and search from chart 1")
    parser.add_argument("--max-height", type=int, default=1080, help="Preferred video height (defaults to 1080p60)")
    args = parser.parse_args(argv)

    if args.command in ("search", "all"):
        charts = load_charts(args.data)
        if args.limit is not None:
            charts = charts[:args.limit]
        checkpoint: list[dict[str, Any]] = []
        if args.matches.exists() and not args.fresh:
            try:
                checkpoint = json.loads(args.matches.read_text(encoding="utf-8"))
                if not isinstance(checkpoint, list):
                    checkpoint = []
            except json.JSONDecodeError:
                print("Existing matches.json is invalid; starting a fresh search.", file=sys.stderr)
        if checkpoint:
            print(f"Resuming from checkpoint: {len(checkpoint)}/{len(charts)} charts already searched.")
            checkpoint = checkpoint[:len(charts)]
        matches = build_matches(charts[len(checkpoint):], args, checkpoint)
        args.matches.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved {len(matches)} entries to {args.matches}. Review 'selected' entries before downloading.")
        if args.command == "search":
            return
    else:
        matches = json.loads(args.matches.read_text(encoding="utf-8"))

    failures = 0
    for number, item in enumerate(matches, start=1):
        try:
            download_one(item, number, args.output, args.max_height)
        except Exception as error:
            failures += 1
            print(f"[{number:02}] FAILED: {error}", file=sys.stderr)
    print(f"\nDone. {len(matches) - failures}/{len(matches)} entries completed. Files: {args.output}")


if __name__ == "__main__":
    main()
