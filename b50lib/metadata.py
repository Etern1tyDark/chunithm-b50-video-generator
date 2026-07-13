"""Refresh the CHUNITHM fusion metadata used by b50-gen cards."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Sequence

from .paths import METADATA

# This is the same fusion-metadata feed used by mai-gen's DataUtils downloader.
FUSION_METADATA_URL = (
    "https://nickbit-maigen-images.oss-cn-shanghai.aliyuncs.com/"
    "metadata_json/chuni_fusion_data.json"
)


def validate(records: Any) -> list[dict[str, Any]]:
    """Reject error pages or incompatible JSON before touching local metadata."""
    if not isinstance(records, list):
        raise ValueError("Metadata response must be a JSON array")
    if not records:
        raise ValueError("Metadata response contains no songs")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("Metadata response contains a non-object song record")
    if not any(record.get("id_otoge") is not None for record in records):
        raise ValueError("Metadata response has no id_otoge values")
    return records


def fetch(url: str = FUSION_METADATA_URL, timeout: float = 30) -> list[dict[str, Any]]:
    """Download and validate the current fusion metadata."""
    import requests

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return validate(response.json())


def write(records: list[dict[str, Any]], output: Path, backup: bool = False) -> Path | None:
    """Atomically replace output, optionally retaining its prior revision."""
    output.parent.mkdir(parents=True, exist_ok=True)
    backup_path = output.with_suffix(output.suffix + ".bak") if backup and output.exists() else None
    if backup_path:
        backup_path.write_bytes(output.read_bytes())
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return backup_path


def refresh(output: Path, url: str = FUSION_METADATA_URL, timeout: float = 30,
            backup: bool = False) -> tuple[int, Path | None]:
    records = fetch(url, timeout)
    return len(records), write(records, output, backup)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Refresh b50-gen CHUNITHM fusion metadata.")
    parser.add_argument("command", choices=("fetch", "check"))
    parser.add_argument("--output", type=Path, help="Required destination for fetched metadata")
    parser.add_argument("--input", type=Path, default=METADATA, help="Metadata file checked by the read-only check command")
    parser.add_argument("--url", default=FUSION_METADATA_URL, help="Metadata endpoint override")
    parser.add_argument("--timeout", type=float, default=30, help="HTTP timeout in seconds")
    parser.add_argument("--backup", action="store_true", help="Save the current file as .json.bak before replacing it")
    args = parser.parse_args(argv)

    if args.command == "check":
        records = validate(json.loads(args.input.read_text(encoding="utf-8")))
        print(f"OK  {len(records)} songs: {args.input}")
        return

    if not args.output:
        parser.error("fetch requires --output so existing metadata is never replaced implicitly")

    print(f"Downloading CHUNITHM fusion metadata from {args.url}")
    count, backup_path = refresh(args.output, args.url, args.timeout, args.backup)
    print(f"Updated {args.output} with {count} songs.")
    if backup_path:
        print(f"Backup: {backup_path}")
