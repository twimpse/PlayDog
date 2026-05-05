#!/usr/bin/python3
"""
PlayScribe v0.3.0
Create incremental XSPF playlists.

New:
- --newer-than DAYS  → only include files modified within last N days
- --since YYYY-MM-DD → include only files modified after this date
- --exclude-from XSPF → skip items already listed in another playlist
- Unified logging & error handling like PlayDog v0.6.0
"""

import xml.etree.ElementTree as ET
from pathlib import Path
import random
import argparse
import os
import re
import sys
import time
import datetime
from datetime import datetime as dt

try:
    from mutagen import File as AudioFile
except ImportError:
    AudioFile = None

SUPPORTED_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".mp4", ".mkv", ".avi"}
XSPF_NS = "http://xspf.org/ns/0/"


# --------------------------------------------------------
# Utility
# --------------------------------------------------------
def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def log(msg, level="INFO", verbose=True):
    if verbose or level in ("ERROR", "WARN"):
        print(f"[{ts()}] [{level}] {msg}")


def parse_size(value: str) -> int:
    value = str(value).strip().upper()
    match = re.fullmatch(r"(\d+)([KMG]?)", value)
    if not match:
        raise argparse.ArgumentTypeError(f"Invalid size format: {value}")
    num, suffix = match.groups()
    num = int(num)
    if suffix == "K":
        return num * 1024
    elif suffix in ("M", ""):
        return num * 1024 * 1024
    elif suffix == "G":
        return num * 1024 * 1024 * 1024
    return num


def load_excluded_basenames(xspf_path):
    """Parse another playlist and collect its basenames."""
    try:
        tree = ET.parse(xspf_path)
        ns = {"xspf": XSPF_NS}
        names = set()
        for loc in tree.findall(".//xspf:location", ns):
            name = Path(loc.text).name.lower()
            names.add(name)
        return names
    except Exception as e:
        log(f"Failed to parse exclude playlist {xspf_path}: {e}", level="WARN")
        return set()


def file_is_new_enough(file_path, newer_than_days=None, since_date=None):
    """Check if file is newer than a threshold or date."""
    try:
        mtime = file_path.stat().st_mtime
    except FileNotFoundError:
        return False

    if newer_than_days:
        cutoff = time.time() - (newer_than_days * 86400)
        return mtime >= cutoff
    if since_date:
        cutoff = dt.strptime(since_date, "%Y-%m-%d").timestamp()
        return mtime >= cutoff
    return True


# --------------------------------------------------------
# Core
# --------------------------------------------------------
def add_track(tracklist, path: Path, relative=False, output_file=None):
    track = ET.SubElement(tracklist, "track")
    location = ET.SubElement(track, "location")

    if relative and output_file:
        rel = os.path.relpath(path, Path(output_file).parent.resolve())
        location.text = Path(rel).as_posix()
    else:
        location.text = path.resolve().as_uri()

    title = ET.SubElement(track, "title")
    creator = ET.SubElement(track, "creator")

    default_title = path.stem
    default_creator = path.parent.name

    if AudioFile:
        try:
            meta = AudioFile(path)
            if meta and meta.tags:
                title_val = meta.tags.get("TIT2", [default_title])[0]
                creator_val = meta.tags.get("TPE1", [default_creator])[0]
                title.text = str(title_val)
                creator.text = str(creator_val)
                return
        except Exception:
            pass

    title.text = default_title
    creator.text = default_creator


def filter_by_size(files, min_size_bytes, max_size_bytes):
    result = []
    for f in files:
        try:
            size = f.stat().st_size
            if size >= min_size_bytes and (max_size_bytes == 0 or size <= max_size_bytes):
                result.append(f)
        except FileNotFoundError:
            pass
    return result


def get_files_from_list(input_txt, min_size_bytes, max_size_bytes):
    base_dir = Path(input_txt).parent.resolve()
    with open(input_txt, "r", encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    files = []
    for path in paths:
        p = Path(path)
        if not p.is_absolute():
            p = base_dir / p
        p = p.resolve()
        if p.exists():
            files.append(p)
    return filter_by_size(files, min_size_bytes, max_size_bytes)


def get_files_from_dir(directory, min_size_bytes, max_size_bytes):
    files = []
    for ext in SUPPORTED_EXTS:
        files.extend(Path(directory).rglob(f"*{ext}"))
    return filter_by_size(files, min_size_bytes, max_size_bytes)


def build_playlist(files, output_xspf, title_text, shuffle=False, relative=False):
    if shuffle:
        random.shuffle(files)
    else:
        files.sort()

    playlist = ET.Element("playlist", version="1", xmlns=XSPF_NS)
    title = ET.SubElement(playlist, "title")
    title.text = title_text
    tracklist = ET.SubElement(playlist, "trackList")

    for f in files:
        add_track(tracklist, f, relative=relative, output_file=output_xspf)

    ET.register_namespace("", XSPF_NS)
    ET.ElementTree(playlist).write(output_xspf, encoding="utf-8", xml_declaration=True)


# --------------------------------------------------------
# Main
# --------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate incremental VLC XSPF playlists.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-f", "--filelist", help="Text file with paths to media files")
    group.add_argument("-d", "--directory", help="Directory to scan for media files")
    parser.add_argument("-o", "--output", default="playlist.xspf", help="Output XSPF file")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle playlist order")
    parser.add_argument("--min-size", type=parse_size, default="0M",
                        help="Minimum file size (e.g. 500K, 50M, 2G)")
    parser.add_argument("--max-size", type=parse_size, default="0",
                        help="Maximum file size (0 = unlimited)")
    parser.add_argument("--relative", action="store_true",
                        help="Use relative paths instead of absolute URIs")
    parser.add_argument("--newer-than", type=int, help="Only include files newer than N days")
    parser.add_argument("--since", help="Only include files modified after YYYY-MM-DD")
    parser.add_argument("--exclude-from", help="Exclude files already in another XSPF playlist")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    # Validate inputs
    if args.filelist and not Path(args.filelist).exists():
        log(f"File list not found: {args.filelist}", level="ERROR")
        sys.exit(1)
    if args.directory and not Path(args.directory).exists():
        log(f"Directory not found: {args.directory}", level="ERROR")
        sys.exit(1)
    if args.since:
        try:
            dt.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            log(f"Invalid date format for --since: {args.since} (use YYYY-MM-DD)", level="ERROR")
            sys.exit(1)

    min_size_bytes = args.min_size
    max_size_bytes = args.max_size

    try:
        if args.filelist:
            files = get_files_from_list(args.filelist, min_size_bytes, max_size_bytes)
            title_text = f"Playlist from {args.filelist}"
        else:
            files = get_files_from_dir(args.directory, min_size_bytes, max_size_bytes)
            title_text = f"Playlist from {args.directory}"
    except Exception as e:
        log(f"Error scanning input: {e}", level="ERROR")
        sys.exit(1)

    if not files:
        log("No media files found matching criteria.", level="ERROR")
        sys.exit(1)

    # Filter by date
    if args.newer_than or args.since:
        before = len(files)
        files = [f for f in files if file_is_new_enough(f, args.newer_than, args.since)]
        log(f"Filtered by date: {before} → {len(files)} files", level="INFO", verbose=args.verbose)

    # Exclude from another playlist
    if args.exclude_from and Path(args.exclude_from).exists():
        excluded = load_excluded_basenames(args.exclude_from)
        before = len(files)
        files = [f for f in files if f.name.lower() not in excluded]
        log(f"Excluded from {args.exclude_from}: {before - len(files)} skipped", level="INFO", verbose=args.verbose)

    if not files:
        log("No remaining media after filters.", level="ERROR")
        sys.exit(1)

    try:
        build_playlist(files, args.output, title_text,
                       shuffle=args.shuffle, relative=args.relative)
        log(f"Playlist written: {args.output} ({len(files)} tracks)", level="INFO", verbose=True)
    except PermissionError:
        log(f"Permission denied writing to: {args.output}", level="ERROR")
        sys.exit(1)
    except Exception as e:
        log(f"Failed to build playlist: {e}", level="ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
