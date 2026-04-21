#!/usr/bin/env python3
"""Run from the repo root after merges to sync backend files to C:\\Users\\Raghu\\Google Drive\\Futures_Scalp_Analyzer."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

FILES_TO_COPY = [
    "backend/futures_scalp_analyzer/__init__.py",
    "backend/futures_scalp_analyzer/models.py",
    "backend/futures_scalp_analyzer/service.py",
    "backend/futures_scalp_analyzer/recommendations.py",
    "backend/futures_scalp_analyzer/risk.py",
    "backend/futures_scalp_analyzer/price_feed.py",
    "backend/futures_scalp_analyzer/symbols.py",
    "backend/app.py",
    "backend/requirements.txt",
    "Procfile",
    "pyproject.toml",
]

DEFAULT_DEST = r"C:\\Users\\Raghu\\Google Drive\\Futures_Scalp_Analyzer"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync backend files from this repo to a Google Drive folder."
    )
    parser.add_argument(
        "--dest",
        default=DEFAULT_DEST,
        help=f"Destination root folder (default: {DEFAULT_DEST})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    dest_root = Path(args.dest).expanduser()

    copied_count = 0
    for relative_file in FILES_TO_COPY:
        source = repo_root / relative_file
        if not source.exists():
            raise FileNotFoundError(f"Source file does not exist: {source}")

        destination = dest_root / relative_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_count += 1
        print(f"✓ Copied {relative_file}")

    print(f"Sync complete. {copied_count} files copied to {dest_root}")


if __name__ == "__main__":
    main()
