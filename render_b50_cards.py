#!/usr/bin/env python3
"""Fetch CHUNITHM jackets and render international B50 video cards."""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from b50lib.paths import ASSETS, DATA as LOCAL_ASSETS, DEFAULT_JACKET, FONTS, METADATA, ROOT, USER_DATA
from b50lib.paths import enable_runtime_packages, ffmpeg_path as local_ffmpeg_path
from b50lib import data as b50_data

enable_runtime_packages()

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS = (1920, 1080)
# The stock 1311x780 frames have a 71px/50px border around a 1169x665
# aperture.  Trim only the excess outer border instead of scaling the entire
# frame down: the chart stays prominent while retaining the difficulty art.
FRAME_CROP = (40, 25, 1271, 755)
CHART_FRAME_POSITION = (66, 62)
CHART_FRAME_SIZE = (1231, 730)
CHART_VIDEO_POSITION = (96, 87)
CHART_VIDEO_SIZE = (1169, 665)
DIFFICULTY_INDEX = {"Basic": 0, "Advanced": 1, "Expert": 2, "Master": 3, "Ultima": 4}
DIFFICULTY_COLORS = {
    0: (72, 200, 111, 255), 1: (244, 184, 44, 255), 2: (237, 77, 74, 255),
    3: (163, 74, 230, 255), 4: (34, 33, 38, 255),
}


def charts_from_file(path: Path) -> list[dict[str, Any]]:
    return b50_data.load_charts(path)


def metadata_by_id(path: Path) -> dict[int, dict[str, Any]]:
    return b50_data.metadata_by_id(path)


def load_comments(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load comments and optional clip timing keyed by id or `best:1` / `new:1`."""
    return b50_data.load_comments(path)


def card_config(configs: dict[str, dict[str, Any]], chart: dict[str, Any], group_number: int) -> dict[str, Any]:
    return b50_data.card_config(configs, chart, group_number)


def jacket_path(chart: dict[str, Any], metadata: dict[int, dict[str, Any]], jackets: Path) -> Path | None:
    return b50_data.jacket_path(chart, metadata, jackets)


def fetch_jackets(charts: list[dict[str, Any]], metadata: dict[int, dict[str, Any]], jackets: Path, delay: float) -> None:
    b50_data.fetch_jackets(charts, metadata, jackets, delay, requests, Image)


def level_info(chart: dict[str, Any], metadata: dict[int, dict[str, Any]]) -> tuple[str, float]:
    return b50_data.level_info(chart, metadata, DIFFICULTY_INDEX)


def calculate_rating(constant: float, score: int) -> float:
    return b50_data.calculate_rating(constant, score)


def image(path: Path) -> Image.Image:
    with Image.open(path) as loaded:
        return loaded.convert("RGBA")


def fit(image_in: Image.Image, size: tuple[int, int]) -> Image.Image:
    ratio = max(size[0] / image_in.width, size[1] / image_in.height)
    scaled = image_in.resize((round(image_in.width * ratio), round(image_in.height * ratio)), Image.Resampling.LANCZOS)
    left, top = (scaled.width - size[0]) // 2, (scaled.height - size[1]) // 2
    return scaled.crop((left, top, left + size[0], top + size[1]))


def text(draw: ImageDraw.ImageDraw, value: str, box: tuple[int, int, int, int], font_path: Path, size: int, color: tuple[int, int, int, int], anchor: str = "la") -> None:
    font = ImageFont.truetype(str(font_path), size)
    while draw.textbbox((0, 0), value, font=font)[2] > box[2] - box[0] and size > 16:
        size -= 2
        font = ImageFont.truetype(str(font_path), size)
    x = box[0] if anchor == "la" else (box[0] + box[2]) // 2
    draw.text((x, box[1]), value, font=font, fill=color, anchor=anchor)


def multiline_text(draw: ImageDraw.ImageDraw, value: str, box: tuple[int, int, int, int], font_path: Path, size: int, color: tuple[int, int, int, int]) -> None:
    font = ImageFont.truetype(str(font_path), size)
    lines = []
    # Keep paragraph breaks from comments.json.  An empty line is intentional:
    # it lets a longer note use the tall commentary panel with readable rhythm.
    for paragraph in value.splitlines() or [""]:
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), candidate, font=font)[2] > box[2] - box[0]:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    y = box[1]
    for line in lines:
        if y + size > box[3]:
            break
        draw.text((box[0], y), line, font=font, fill=color)
        y += size + 12


def wrapped_lines(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Wrap on words where possible; use character wrapping only for CJK/no-space text."""
    if draw.textlength(value, font=font) <= width:
        return [value]
    units = value.split(" ") if " " in value else list(value)
    joiner = " " if " " in value else ""
    lines, line = [], ""
    for unit in units:
        candidate = f"{line}{joiner if line else ''}{unit}"
        if line and draw.textlength(candidate, font=font) > width:
            lines.append(line)
            line = unit
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def wrapped_text(draw: ImageDraw.ImageDraw, value: str, box: tuple[int, int, int, int], font_path: Path,
                 preferred_size: int, minimum_size: int, color: tuple[int, int, int, int], max_lines: int) -> None:
    """Prefer a readable single line; wrap only when shrinking is no longer enough."""
    available_width = box[2] - box[0]
    # A title such as Kaleidoscope should become a slightly smaller one-liner,
    # not an awkward two-line word fragment.
    for size in range(preferred_size, minimum_size - 1, -1):
        font = ImageFont.truetype(str(font_path), size)
        if draw.textlength(value, font=font) <= available_width:
            lines = [value]
            break
    else:
        # A two-line block must also fit vertically; otherwise the second line
        # collides with the artist/constant rows below it.
        wrapped_max_size = min(preferred_size, max(minimum_size, (box[3] - box[1]) // max_lines - 3))
        for size in range(wrapped_max_size, minimum_size - 1, -1):
            font = ImageFont.truetype(str(font_path), size)
            lines = wrapped_lines(draw, value, font, available_width)
            if len(lines) <= max_lines:
                break
        else:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" .") + "…"
    line_height = min(size + 2, max(1, (box[3] - box[1]) // max_lines))
    for index, line in enumerate(lines[:max_lines]):
        draw.text((box[0], box[1] + index * line_height), line, font=font, fill=color)


def number_sprite(value: str, folder: Path, height: int, tracking: int = -3) -> Image.Image:
    """Build a compact number: source sprites include generous side padding."""
    parts = []
    for char in value:
        glyph = image(folder / ({",": "comma.png", ".": "dot.png"}.get(char, f"{char}.png")))
        bounds = glyph.getbbox()
        if bounds:
            # Keep the original vertical canvas: commas/dots sit below the
            # digit baseline and must not be recentered independently.
            glyph = glyph.crop((bounds[0], 0, bounds[2], glyph.height))
        glyph = glyph.resize((round(glyph.width * height / glyph.height), height), Image.Resampling.LANCZOS)
        if char in (",", "."):
            glyph = glyph.resize((max(1, glyph.width // 2), glyph.height), Image.Resampling.LANCZOS)
        parts.append(glyph)
    result = Image.new("RGBA", (max(1, sum(item.width for item in parts) + tracking * (len(parts) - 1)), height))
    cursor = 0
    for glyph in parts:
        result.alpha_composite(glyph, (cursor, 0)); cursor += glyph.width + tracking
    return result


def centered_image(canvas: Image.Image, item: Image.Image, box: tuple[int, int, int, int]) -> None:
    """Centre the visible pixels, not the transparent padding around a sprite."""
    bounds = item.getbbox() or (0, 0, item.width, item.height)
    visible_width, visible_height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    x = box[0] + (box[2] - box[0] - visible_width) // 2 - bounds[0]
    y = box[1] + (box[3] - box[1] - visible_height) // 2 - bounds[1]
    canvas.alpha_composite(item, (x, y))


def status_asset(chart: dict[str, Any], combo: bool) -> Path | None:
    if combo:
        if chart.get("isAllJustice") and chart.get("isFullCombo"): return ASSETS / "ComboStatus" / "13.png"
        if chart.get("isAllJustice"): return ASSETS / "ComboStatus" / "12.png"
        if chart.get("isFullCombo"): return ASSETS / "ComboStatus" / "11.png"
        return LOCAL_ASSETS / "fcombooff.png"
    else:
        level = int(chart.get("fullChainLv", 0) or 0)
        if level >= 2: return ASSETS / "ComboStatus" / "22.png"
        if level == 1: return ASSETS / "ComboStatus" / "21.png"
        return LOCAL_ASSETS / "fchainoff.png"
    return None


def ffmpeg_path() -> str | None:
    return local_ffmpeg_path()


def video_path(chart: dict[str, Any], number: int, videos: Path) -> Path | None:
    found = sorted(videos.glob(f"{number:02}_{chart['group']}_{chart['difficulty']}_{chart['idx']}_*.mp4"))
    return found[0] if found else None


def chart_frame(video: Path | None, timestamp: float, size: tuple[int, int]) -> Image.Image | None:
    ffmpeg = ffmpeg_path()
    if not video or not video.exists() or not ffmpeg:
        return None
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(timestamp), "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with Image.open(io.BytesIO(result.stdout)) as captured:
            # Chart captures are normally 16:9 while the frame aperture is
            # fractionally taller.  Fill and centre-crop the extra rows so no
            # black letterbox seam remains around the chart view.
            return fit(captured.convert("RGBA"), size)
    except (OSError, subprocess.CalledProcessError, Image.UnidentifiedImageError):
        return None


def render_video_clip(chart: dict[str, Any], number: int, card: Path, videos: Path, clips: Path,
                      start: float, duration: float, force: bool) -> None:
    """Overlay a chart-video segment into a previously rendered static card."""
    source = video_path(chart, number, videos)
    if not source or not source.exists():
        print(f"[{number:02}] No chart video: {chart['title']}", file=sys.stderr)
        return
    if not card.exists():
        print(f"[{number:02}] Card image missing: {card.name}", file=sys.stderr)
        return
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg.exe was not found; clips cannot be rendered")
    clips.mkdir(parents=True, exist_ok=True)
    output = clips / f"{number:02}_{chart['group']}_{chart['idx']}.mp4"
    if output.exists() and output.stat().st_size > 0 and not force:
        print(f"[{number:02}] Cached: {output.name}")
        return
    chart_w, chart_h = CHART_VIDEO_SIZE
    chart_x, chart_y = CHART_VIDEO_POSITION
    filter_graph = (
        f"[1:v]scale={chart_w}:{chart_h}:force_original_aspect_ratio=increase,"
        f"crop={chart_w}:{chart_h},setsar=1[chart];"
        f"[0:v][chart]overlay={chart_x}:{chart_y}:shortest=1,format=yuv420p[video]"
    )
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-loop", "1", "-framerate", "60", "-i", str(card),
        "-ss", str(start), "-t", str(duration), "-i", str(source),
        "-filter_complex", filter_graph, "-map", "[video]", "-map", "1:a?",
        "-r", "60", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(output),
    ]
    subprocess.run(command, check=True)
    print(f"[{number:02}] Rendered clip: {output.name}")


def render_clips(charts: list[dict[str, Any]], comments: dict[str, dict[str, Any]], output: Path,
                 videos: Path, clips: Path, start: float, end: float, force: bool) -> None:
    """Render every chart clip in B50 order before final-video assembly."""
    counts = {"best": 0, "new": 0}
    for number, chart in enumerate(charts, 1):
        counts[chart["group"]] += 1
        config = card_config(comments, chart, counts[chart["group"]])
        clip_start = float(config.get("clip_start", start))
        clip_end = float(config.get("clip_end", end))
        if clip_start < 0 or clip_end <= clip_start:
            raise ValueError(f"Invalid clip timing for {chart['title']}: end must be greater than a non-negative start")
        card = output / f"{number:02}_{chart['group']}_{chart['idx']}.jpg"
        render_video_clip(chart, number, card, videos, clips, clip_start, clip_end - clip_start, force)


def concat_clips(charts: list[dict[str, Any]], clips: Path, final_output: Path, transition: str,
                 transition_duration: float, encoder: str, bitrate: str, fps: int,
                 normalize_audio: bool, allow_missing: bool, intro: Path | None, outro: Path | None) -> None:
    """Assemble the ordered B50 clips using the same FFmpeg paths as mai-gen."""
    from b50lib.concat import concat, ordered_clips

    ordered = ordered_clips(clips, charts, allow_missing=allow_missing)
    for label, extra in (("intro", intro), ("outro", outro)):
        if extra:
            if not extra.exists():
                raise FileNotFoundError(f"{label.title()} clip was not found: {extra}")
            ordered = ([extra] + ordered) if label == "intro" else (ordered + [extra])
    result = concat(ordered, final_output, transition, transition_duration, encoder, bitrate, fps, normalize_audio)
    print(f"Final B50 video: {result}")


def render_card(chart: dict[str, Any], number: int, group_number: int, metadata: dict[int, dict[str, Any]], jackets: Path, videos: Path, comments: dict[str, dict[str, Any]], frame_time: float, output: Path) -> None:
    jacket_file = jacket_path(chart, metadata, jackets)
    jacket = image(jacket_file) if jacket_file and jacket_file.exists() else image(DEFAULT_JACKET)
    canvas = Image.new("RGBA", CANVAS, (10, 14, 27, 255))
    canvas.alpha_composite(fit(jacket, CANVAS).filter(ImageFilter.GaussianBlur(42)))
    canvas.alpha_composite(Image.new("RGBA", CANVAS, (8, 11, 23, 228)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((38, 34, 1882, 1046), radius=32, fill=(13, 18, 35, 242), outline=(255, 255, 255, 42), width=2)
    font, title_font = FONTS / "FOT_NewRodin_Pro_EB.otf", FONTS / "SweiBellLegCJKsc-Black.ttf"
    difficulty = DIFFICULTY_INDEX.get(chart["difficulty"], 3); accent = DIFFICULTY_COLORS[difficulty]
    level, constant, score = (*level_info(chart, metadata), int(chart["score"]))
    rating = calculate_rating(constant, score)

    draw.rectangle((CHART_FRAME_POSITION[0], CHART_FRAME_POSITION[1], CHART_FRAME_POSITION[0] + CHART_FRAME_SIZE[0], CHART_FRAME_POSITION[1] + CHART_FRAME_SIZE[1]), fill=(4, 5, 10, 255))
    preview = chart_frame(video_path(chart, number, videos), frame_time, CHART_VIDEO_SIZE)
    if preview:
        canvas.alpha_composite(preview, CHART_VIDEO_POSITION)
    else:
        text_y = CHART_VIDEO_POSITION[1] + CHART_VIDEO_SIZE[1] // 2 - 28
        text(draw, "CHART VIDEO NOT FOUND", (CHART_VIDEO_POSITION[0], text_y, CHART_VIDEO_POSITION[0] + CHART_VIDEO_SIZE[0], text_y + 55), font, 42, (184, 195, 222, 255), "ma")
    frame = image(ASSETS / "Frames" / f"{difficulty}.png").crop(FRAME_CROP)
    canvas.alpha_composite(frame, CHART_FRAME_POSITION)
    # alpha_composite can replace Pillow's underlying drawing buffer.  Create
    # a fresh draw object before laying out the right panel and score strip.
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle((1325, 62, 1854, 792), radius=18, fill=(23, 29, 51, 245), outline=(255, 255, 255, 35), width=2)
    draw.rounded_rectangle((1325, 62, 1854, 128), radius=18, fill=accent)
    label = f"OLD - Best {group_number:02}" if chart["group"] == "best" else f"NEW - Best {group_number:02}"
    text(draw, label, (1349, 77, 1830, 116), font, 32, (255, 255, 255, 255))
    comment = str(card_config(comments, chart, group_number).get("comment", ""))
    text(draw, "COMMENTARY", (1351, 164, 1828, 202), font, 27, (163, 177, 215, 255))
    draw.line((1349, 216, 1830, 216), fill=(255, 255, 255, 30), width=2)
    multiline_text(draw, comment or "No commentary yet.\n\nLorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.", (1349, 244, 1830, 758), title_font, 29, (239, 242, 255, 255))

    draw.rounded_rectangle((66, 820, 1854, 1018), radius=18, fill=(244, 247, 255, 255))
    canvas.alpha_composite(fit(jacket, (166, 166)), (90, 836)); draw.rounded_rectangle((90, 836, 256, 1002), radius=12, outline=accent, width=6)
    # Each value owns a fixed cell: this prevents wide score sprites from
    # entering the rating/status area and keeps every number optically centred.
    level_box, info_box = (282, 839, 420, 1005), (450, 838, 735, 1004)
    score_box, rating_box, status_box = (755, 825, 1205, 998), (1215, 825, 1475, 998), (1500, 825, 1828, 998)
    level_base = image(LOCAL_ASSETS / "level.png").resize((124, 142), Image.Resampling.LANCZOS)
    canvas.alpha_composite(level_base, (289, 848))
    # The level graphic contains its own header.  Its value is vertically
    # centred in the lower dark field using Pillow's true middle anchor.
    level_font, plus_font = ImageFont.truetype(str(font), 54), ImageFont.truetype(str(font), 28)
    if level.endswith("+"):
        main_level = level[:-1]
        main_width = draw.textlength(main_level, font=level_font)
        plus_width = draw.textlength("+", font=plus_font)
        left = (level_box[0] + level_box[2] - main_width - plus_width + 2) / 2
        draw.text((left + main_width / 2, 938), main_level, font=level_font, fill=(255, 255, 255, 255), anchor="mm")
        draw.text((left + main_width - 1, 901), "+", font=plus_font, fill=(255, 255, 255, 255), anchor="lt")
    else:
        draw.text(((level_box[0] + level_box[2]) // 2, 938), level, font=level_font, fill=(255, 255, 255, 255), anchor="mm")
    # Keep metadata in its own lower block; score/rating coordinates stay independent.
    wrapped_text(draw, chart["title"], (info_box[0], 836, info_box[2], 890), title_font, 42, 20, (22, 27, 58, 255), 2)
    wrapped_text(draw, metadata.get(chart["idx"], {}).get("artist", "Unknown artist"), (info_box[0], 895, info_box[2], 953), title_font, 25, 16, (71, 78, 106, 255), 2)
    # Keep this as the last baseline in the information cell, even for a long title/artist.
    text(draw, f"CONSTANT {constant:.1f}" if constant else "CONSTANT —", (info_box[0], 975, info_box[2], 1003), font, 22, (71, 78, 106, 255))
    # Centre each label-and-value group, not just its numeral, in the bottom strip.
    text(draw, "SCORE", (score_box[0], 844, score_box[2], 884), font, 24, (71, 78, 106, 255), "ma")
    score_image = number_sprite(f"{score:,}", ASSETS / "Numbers" / "AchievementNumber", 105)
    centered_image(canvas, score_image, (score_box[0], 880, score_box[2], 1010))
    text(draw, "RATING", (rating_box[0], 844, rating_box[2], 884), font, 24, (71, 78, 106, 255), "ma")
    style = "ex_rainbow" if rating >= 17 else "rainbow" if rating >= 16 else "gold"
    rating_image = number_sprite(f"{rating:.2f}", ASSETS / "Numbers" / "RatingNumber" / style, 80, 0)
    centered_image(canvas, rating_image, (rating_box[0], 880, rating_box[2], 1010))
    status_y = 858
    for combo in (True, False):
        path = status_asset(chart, combo)
        if path:
            icon = image(path)
            width = 300
            height = round(icon.height * width / icon.width)
            icon = icon.resize((width, height), Image.Resampling.LANCZOS)
            centered_image(canvas, icon, (status_box[0], status_y, status_box[2], status_y + height)); status_y += 68
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, "JPEG", quality=96, subsampling=0)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch CHUNITHM jackets and render B50 video cards.")
    parser.add_argument("command", choices=("jackets", "render", "clips", "concat", "video", "all")); parser.add_argument("--data", type=Path, default=USER_DATA)
    parser.add_argument("--metadata", type=Path, default=METADATA); parser.add_argument("--jackets", type=Path, default=ROOT / "jackets")
    parser.add_argument("--videos", type=Path, default=ROOT / "downloads", help="Downloaded chart videos used for previews"); parser.add_argument("--output", type=Path, default=ROOT / "cards")
    parser.add_argument("--clips", type=Path, default=ROOT / "clips", help="Rendered chart-video cards")
    parser.add_argument("--comments", type=Path, default=ROOT / "comments.json", help="Optional notes keyed by id or best:1/new:1"); parser.add_argument("--frame-time", type=float, default=20, help="Preview timestamp in seconds")
    parser.add_argument("--clip-start", type=float, default=20, help="Seconds into the chart video when a clip starts")
    parser.add_argument("--clip-end", type=float, default=35, help="Seconds into the chart video when a clip ends")
    parser.add_argument("--final-output", type=Path, default=ROOT / "b50_full.mp4", help="Assembled B50 video path")
    parser.add_argument("--transition", choices=("none", "fade", "wipeleft", "slideright", "circleopen", "dissolve"), default="fade", help="FFmpeg xfade transition between clips (default: fade)")
    parser.add_argument("--transition-duration", type=float, default=1, help="Transition duration in seconds")
    parser.add_argument("--encoder", choices=("auto", "cpu", "h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"), default="auto", help="Encoder for transition mode")
    parser.add_argument("--bitrate", default="12000k", help="Video bitrate for transition mode")
    parser.add_argument("--fps", type=int, default=60, help="Output FPS for transition mode")
    parser.add_argument("--normalize-audio", action="store_true", help="Normalize the final audio once with loudnorm")
    parser.add_argument("--allow-missing", action="store_true", help="Concat available clips instead of requiring the complete B50")
    parser.add_argument("--intro", type=Path, help="Optional existing video prepended to the B50")
    parser.add_argument("--outro", type=Path, help="Optional existing video appended to the B50")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing rendered clip")
    parser.add_argument("--delay", type=float, default=.5); parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv); charts, metadata, comments = charts_from_file(args.data), metadata_by_id(args.metadata), load_comments(args.comments)
    if args.limit is not None: charts = charts[:args.limit]
    if args.command in ("jackets", "all"): fetch_jackets(charts, metadata, args.jackets, args.delay)
    if args.command in ("render", "all"):
        counts = {"best": 0, "new": 0}
        for number, chart in enumerate(charts, 1):
            counts[chart["group"]] += 1; filename = f"{number:02}_{chart['group']}_{chart['idx']}.jpg"
            render_card(chart, number, counts[chart["group"]], metadata, args.jackets, args.videos, comments, args.frame_time, args.output / filename)
            print(f"[{number:02}] Rendered: {filename}")
    if args.command in ("clips", "video"):
        render_clips(charts, comments, args.output, args.videos, args.clips, args.clip_start, args.clip_end, args.force)
    if args.command in ("concat", "video"):
        concat_clips(charts, args.clips, args.final_output, args.transition, args.transition_duration,
                     args.encoder, args.bitrate, args.fps, args.normalize_audio, args.allow_missing,
                     args.intro, args.outro)


if __name__ == "__main__":
    main()
