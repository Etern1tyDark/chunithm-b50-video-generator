# CHUNITHM B50 Generator

Inspiration: https://github.com/Nick-bit233/mai-gen-videob50/

## Install and launch

**Quick Start**

```bash
git clone https://github.com/Etern1tyDark/chunithm-b50-video-generator.git
cd chunithm-b50-video-generator

# Go to "Releases" tab and get runtime.zip, unzip and put it in chunithm-b50-video-generator/.
```

The bundled Windows runtime in releases contains the Python packages b50-gen needs. On macOS and Linux, install the dependencies and FFmpeg with your normal package manager.

| Platform | One-time setup | Command |
| --- | --- | --- |
| Windows | No extra setup: b50-gen includes the bundled runtime. | `.\start.bat health` |
| macOS | `brew install ffmpeg` and `python3 -m pip install -r requirements.txt` | `python3 b50.py health` |
| Linux | `sudo apt install ffmpeg` and `python3 -m pip install -r requirements.txt` | `python3 b50.py health` |

The local `tools/ffmpeg.exe` is used on Windows. Note that when cloning this is zipped due to size limits. On macOS and Linux, b50-gen uses `ffmpeg` from `PATH`.

For the rest of this README, use either launcher:

```text
Windows:      .\start.bat
macOS/Linux:  python3 b50.py
```

For example, `$B50 cards -h` below means either launcher followed by `cards -h`.

## Data Retrieval

https://reiwa.f5.si/ can be used to get a JSON file of your data and then you can just put it as `user/data.json`.

## Commands

```text
$B50 videos <search|download|all> [options]
$B50 cards <jackets|render|clips|concat|video|all> [options]
$B50 comments init [options]
$B50 metadata <fetch|check> [options]
$B50 health
```

`health` is read-only and verifies the required local files. Use component help for every option:

```text
$B50 videos -h
$B50 cards -h
$B50 metadata -h
```

## Video search and download

Search YouTube for every chart in the B50 export:

```text
$B50 videos search
```

This writes `matches.json`. Review every `selected` entry before downloading; choose another candidate or set `status` to `skip` when needed.

```text
$B50 videos download
```

Videos are saved in `downloads` with a stable B50-order prefix. Downloads prefer adaptive 1080p60 MP4 plus the best audio stream.

Useful options:

```text
$B50 videos search --results 6 --delay 3
$B50 videos search --limit 1
$B50 videos download --max-height 1080
```

## Cards and per-song clips

Fetch jackets and render static cards:

```text
$B50 cards jackets
$B50 cards render
```

Or perform both steps:

```text
$B50 cards all
```

Cards are written to `cards`. To choose another capture moment:

```text
$B50 cards render --frame-time 35
```

Render the B50-order clips over their matching cards:

```text
$B50 cards clips --clip-start 20 --clip-end 35
```

Clips are written to `clips`. Add `--force` to regenerate an existing clip.

## Final B50 video

`concat` orders clips as New 20 through New 1, then Best 30 through Best 1 (descending by the original B50 rank). By default it uses a one-second fade between clips; use `--transition none` for the fast, lossless MPEG-TS remux and stream-copy path.

```text
$B50 cards concat --final-output b50_full.mp4
```

`video` runs the clip-rendering phase and then concatenates the result:

```text
$B50 cards video --clip-start 20 --clip-end 35 --final-output b50_full.mp4
```

Fade and the other FFmpeg crossfades re-encode the final video. `--encoder auto` detects NVIDIA NVENC, AMD AMF, Intel Quick Sync, or macOS VideoToolbox, then falls back to CPU x264. Audio crossfades match the video transition.

```text
$B50 cards concat --transition fade --transition-duration 0.75 --encoder auto --bitrate 12000k
```

Other supported transitions are `wipeleft`, `slideright`, `circleopen`, and `dissolve`. Use `--normalize-audio` to apply one loudness-normalization pass to the finished file. `--intro path/to/intro.mp4` and `--outro path/to/outro.mp4` add pre-rendered video segments around the ordered B50 clips.

## Metadata

The card renderer uses `data/chuni_fusion_data.json`. Its source is the fusion-metadata endpoint (used by Nick-bit233's mai-gen-videob50).

Check the existing local file without changing it:

```text
$B50 metadata check
```

Download a candidate update only to an explicit path, then review it and replace the local file manually if desired:

```text
$B50 metadata fetch --output data/chuni_fusion_data.new.json
```

## Commentary

Generate a timing-ready template from the current B50 export:

```text
$B50 comments init
```

It reads every matching file in `downloads` and creates one entry per Best and New chart with a blank `comment`, `clip_start: 0`, a `clip_end` equal to that video's duration, `recommendation: 0`, and `pc: 0`. Existing files are protected; use `--force` to regenerate after downloading or replacing videos. The compact `comments.example.json` stays as a reference for the two supported entry styles.

Entries can be plain strings or objects with `comment`, `clip_start`, `clip_end`, `recommendation`, and `pc`. `recommendation` is a whole number from 0 to 10, rendered as five outline/filled stars with half stars for odd values; `pc` is a non-negative play count. Notes can have paragraph breaks and can be keyed by a song id (for example, `"2892"`) or by `"best:2"` / `"new:1"`; a song-id note wins.

## Project layout

```text
b50.py                 Unified command entry point
b50lib/paths.py        Local assets, runtime discovery, ffmpeg lookup
b50lib/data.py         B50 input, metadata, jackets, comments, rating logic
b50lib/concat.py       Ordered fast concat, xfade, hardware encoder detection
b50_downloader.py      Video search/download implementation
render_b50_cards.py    Card, clip, and final-video workflow implementation
data/                  Renderer assets, metadata, fonts, fallback jacket
user/data.json         Default B50 input export
tools/ffmpeg.exe       Windows-local encoder; POSIX uses ffmpeg from PATH
```

The B50 JSON export defaults to `user/data.json`. Pass `--data path/to/export.json` to either workflow to use a different export.
