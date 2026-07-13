"""FFmpeg-only B50 clip assembly, modelled after mai-gen's final stage."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from .paths import ffmpeg_path

_ENCODERS = (
    ("h264_videotoolbox", "macOS VideoToolbox"),
    ("h264_nvenc", "NVIDIA NVENC"),
    ("h264_amf", "AMD AMF"),
    ("h264_qsv", "Intel Quick Sync"),
)


def ordered_clips(clips_dir: Path, charts: Sequence[dict], allow_missing: bool = False) -> list[Path]:
    """Return clips in B50 order, never relying on filesystem ordering."""
    clips, missing = [], []
    for number, chart in enumerate(charts, 1):
        clip = clips_dir / f"{number:02}_{chart['group']}_{chart['idx']}.mp4"
        if clip.exists() and clip.stat().st_size > 0:
            clips.append(clip)
        else:
            missing.append(clip.name)
    if missing and not allow_missing:
        sample = ", ".join(missing[:5])
        suffix = " ..." if len(missing) > 5 else ""
        raise FileNotFoundError(f"Missing {len(missing)} rendered clip(s): {sample}{suffix}")
    if not clips:
        raise FileNotFoundError(f"No rendered clips found in {clips_dir}")
    return clips


def _encoder_args(codec: str, bitrate: str) -> list[str]:
    if codec == "h264_videotoolbox":
        return ["-c:v", codec, "-b:v", bitrate, "-allow_sw", "1"]
    if codec == "h264_nvenc":
        return ["-c:v", codec, "-b:v", bitrate, "-preset", "p4", "-tune", "hq"]
    if codec == "h264_amf":
        return ["-c:v", codec, "-b:v", bitrate, "-quality", "balanced"]
    if codec == "h264_qsv":
        return ["-c:v", codec, "-b:v", bitrate, "-preset", "medium"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]


def choose_encoder(requested: str = "auto") -> tuple[str, str]:
    """Use a working hardware H.264 encoder when requested and available."""
    if requested != "auto":
        return ("libx264", "CPU software") if requested == "cpu" else (requested, requested)
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg.exe was not found")
    try:
        available = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                   text=True, timeout=10).stdout
        for codec, label in _ENCODERS:
            if codec not in available:
                continue
            probe = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                 "nullsrc=s=256x256:d=0.1:r=30", "-c:v", codec, "-f", "null", "-"],
                capture_output=True, text=True, timeout=10,
            )
            if probe.returncode == 0:
                return codec, label
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "libx264", "CPU software"


def _duration(path: Path, ffmpeg: str) -> float:
    """Read duration without requiring a separately bundled ffprobe binary."""
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise ValueError(f"Could not read the duration of {path.name}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _stream_copy_concat(clips: Sequence[Path], output: Path, ffmpeg: str) -> Path:
    """Remux MP4 clips to transport streams, then concat-copy them losslessly."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b50-concat-", dir=output.parent) as temporary:
        temp = Path(temporary)
        manifest = temp / "clips.txt"
        entries = []
        for index, clip in enumerate(clips):
            segment = temp / f"{index:03}.ts"
            subprocess.run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "warning", "-i", str(clip),
                "-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", str(segment),
            ], check=True)
            entries.append(f"file '{segment.as_posix()}'")
        manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")
        subprocess.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning", "-f", "concat", "-safe", "0",
            "-i", str(manifest), "-c", "copy", "-movflags", "+faststart", str(output),
        ], check=True)
    return output


def _xfade_concat(clips: Sequence[Path], output: Path, ffmpeg: str, transition: str,
                  duration: float, encoder: str, bitrate: str, fps: int) -> Path:
    """Concatenate clips with video and audio crossfades, as mai-gen does."""
    if duration <= 0:
        raise ValueError("Transition duration must be greater than zero")
    durations = [_duration(clip, ffmpeg) for clip in clips]
    if any(item <= duration for item in durations):
        raise ValueError("Every clip must be longer than the transition duration")
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning"]
    for clip in clips:
        command += ["-i", str(clip)]

    filters = []
    for index, clip_duration in enumerate(durations):
        filters.append(
            f"[{index}:v]setpts=PTS-STARTPTS,trim=duration={clip_duration:.6f},"
            f"fps={fps},format=yuv420p,settb=AVTB[v{index}]"
        )
        filters.append(
            f"[{index}:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
            f"atrim=duration={clip_duration:.6f},asetpts=N/SR/TB,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
        )

    accumulated = durations[0]
    for index in range(len(clips) - 1):
        left_video = "[v0]" if index == 0 else f"[vfade{index - 1}]"
        left_audio = "[a0]" if index == 0 else f"[afade{index - 1}]"
        right_video, right_audio = f"[v{index + 1}]", f"[a{index + 1}]"
        final = index == len(clips) - 2
        video_out = "[vout]" if final else f"[vfade{index}]"
        audio_out = "[aout]" if final else f"[afade{index}]"
        offset = max(0.01, accumulated - duration)
        filters.append(
            f"{left_video}{right_video}xfade=transition={transition}:duration={duration}:offset={offset:.6f}{video_out}"
        )
        filters.append(f"{left_audio}{right_audio}acrossfade=d={duration}:c1=tri:c2=tri{audio_out}")
        accumulated = offset + durations[index + 1]

    command += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]"]
    command += _encoder_args(encoder, bitrate)
    command += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    subprocess.run(command, check=True)
    return output


def _normalize_audio(source: Path, output: Path, ffmpeg: str) -> Path:
    """Keep video bit-for-bit and normalize the assembled audio once."""
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning", "-i", str(source), "-c:v", "copy",
        "-af", "loudnorm=I=-20:TP=-1.5:LRA=11,aresample=48000:first_pts=0,asetpts=N/SR/TB",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(output),
    ], check=True)
    return output


def concat(clips: Sequence[Path], output: Path, transition: str = "none", transition_duration: float = 1,
           encoder: str = "auto", bitrate: str = "12000k", fps: int = 60,
           normalize_audio: bool = False) -> Path:
    """Build the final B50 video from already rendered clips."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg.exe was not found")
    output = output.resolve()
    if transition == "none" or len(clips) == 1:
        assembled = _stream_copy_concat(clips, output, ffmpeg)
        print(f"Concatenated {len(clips)} clips with stream copy.")
    else:
        codec, label = choose_encoder(encoder)
        print(f"Concatenating {len(clips)} clips with {transition} transitions using {label}.")
        assembled = _xfade_concat(clips, output, ffmpeg, transition, transition_duration, codec, bitrate, fps)
    if not normalize_audio:
        return assembled
    normalized = output.with_name(f"{output.stem}.normalized{output.suffix}")
    _normalize_audio(assembled, normalized, ffmpeg)
    os.replace(normalized, output)
    return output
