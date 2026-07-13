#!/usr/bin/env python3
"""Single entry point for the standalone CHUNITHM B50 generator.

Examples:
    python b50.py videos search --limit 1
    python b50.py cards render --frame-time 35
    python b50.py comments init
    python b50.py health
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from b50lib.paths import DEFAULT_JACKET, FFMPEG, METADATA, RUNTIME, enable_runtime_packages


def health() -> int:
    """Report the local files required by b50-gen without touching the network."""
    checks = {
        "metadata": METADATA,
        "default jacket": DEFAULT_JACKET,
        "ffmpeg": FFMPEG,
        "bundled runtime (optional)": RUNTIME,
    }
    failed = False
    for label, path in checks.items():
        optional = label == "bundled runtime (optional)"
        available = path.exists()
        failed |= not available and not optional
        print(f"{'OK' if available else 'MISSING'}  {label}: {path}")
    if not RUNTIME.exists():
        print("The runtime is optional only when Pillow, requests, and pytubefix are installed in Python.")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone CHUNITHM B50 video and card generator.")
    parser.add_argument("component", choices=("videos", "cards", "comments", "metadata", "health"), help="Workflow to run")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for the selected workflow")
    args = parser.parse_args(argv)

    if args.component == "health":
        if args.args:
            parser.error("health does not take additional arguments")
        return health()

    enable_runtime_packages()
    if not args.args:
        parser.error(f"{args.component} needs a command; run with -h after the component for its options")
    if args.component == "videos":
        from b50_downloader import main as videos_main
        videos_main(args.args)
    elif args.component == "cards":
        from render_b50_cards import main as cards_main
        cards_main(args.args)
    elif args.component == "comments":
        from b50lib.comments import main as comments_main
        comments_main(args.args)
    else:
        from b50lib.metadata import main as metadata_main
        metadata_main(args.args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
