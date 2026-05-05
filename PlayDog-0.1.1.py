#!/usr/bin/python3
"""
PlayDog v0.6.0 (HTTP edition + shuffle mode + error handling)
Track played videos via VLC HTTP API and prune them from a playlist.

New:
- Robust error handling (missing file, XML parse failure, HTTP 401)
- Shuffle-only mode (--shuffle)
- Improved logging consistency and verbosity control
"""

import time
import argparse
import requests
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse
import unicodedata
from datetime import datetime
import random
import sys

XSPF_NS = "http://xspf.org/ns/0/"
NSMAP = {"xspf": XSPF_NS}


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg, *, verbose=False, level="INFO"):
    if verbose or level in ("ERROR", "WARN"):
        print(f"[{ts()}] [{level}] {msg}")


def normalize_basename(value: str) -> str:
    """Normalize filename or URI to lowercase basename."""
    if value is None:
        return ""
    path = urlparse(value).path if "://" in value else value
    path = unicodedata.normalize("NFKC", unquote(path))
    path = path.replace("\\", "/")
    base = path.split("/")[-1].strip().replace("\r", "").replace("\n", "")
    return base.lower()


def get_current_media(host, port, password, verbose=False, debug=False):
    """Poll VLC HTTP API for current playing media filename."""
    url = f"http://{host}:{port}/requests/status.json"
    try:
        r = requests.get(url, auth=("", password), timeout=5)
        if r.status_code == 401:
            log("Unauthorized (401) — wrong password or HTTP interface disabled.", level="ERROR")
            return None
        if r.status_code != 200:
            log(f"HTTP error {r.status_code}", level="ERROR", verbose=verbose)
            return None
        data = r.json()
        state = data.get("state")
        meta = data.get("information", {}).get("category", {}).get("meta", {}) or {}
        if debug:
            log(f"state={state} meta_keys={list(meta.keys())}", level="DEBUG", verbose=True)
        if state == "playing":
            return meta.get("filename") or meta.get("title") or meta.get("url")
        return None
    except requests.exceptions.ConnectionError:
        log("Failed to connect to VLC HTTP API (Connection refused).", level="ERROR")
        return None
    except Exception as e:
        log(f"VLC query failed: {e}", level="ERROR")
        return None


def summarize_playlist(playlist_path, verbose=False):
    """Return (#tracks, first few basenames)."""
    try:
        tree = ET.parse(playlist_path)
        root = tree.getroot()
        tracklist = root.find(".//xspf:trackList", NSMAP)
        if tracklist is None:
            return 0, []
        names = []
        for i, track in enumerate(tracklist):
            loc = track.find("xspf:location", NSMAP)
            if loc is None:
                continue
            names.append(normalize_basename(loc.text))
            if i >= 9:
                break
        return len(list(tracklist)), names
    except FileNotFoundError:
        log(f"Playlist not found: {playlist_path}", level="ERROR")
        return 0, []
    except ET.ParseError as e:
        log(f"Playlist parse error: {e}", level="ERROR")
        return 0, []
    except Exception as e:
        log(f"Unexpected error summarizing playlist: {e}", level="ERROR")
        return 0, []


def prune_from_playlist(playlist_path, filename, verbose=False, debug=False, dry_run=False):
    """Remove track matching VLC filename."""
    if not filename:
        return False
    if not Path(playlist_path).exists():
        log(f"Playlist file not found: {playlist_path}", level="ERROR")
        return False

    try:
        tree = ET.parse(playlist_path)
        root = tree.getroot()
        tracklist = root.find(".//xspf:trackList", NSMAP)
        if tracklist is None:
            log("No <trackList> in playlist.", level="ERROR")
            return False
    except ET.ParseError as e:
        log(f"Playlist parse failed: {e}", level="ERROR")
        return False

    vlc_base = normalize_basename(filename)
    log(f"Matching VLC basename='{vlc_base}'", verbose=verbose)

    removed = False
    total_before = len(list(tracklist))

    for track in list(tracklist):
        loc = track.find("xspf:location", NSMAP)
        if loc is None or not loc.text:
            continue
        pl_base = normalize_basename(loc.text)
        if debug:
            log(f"Compare: VLC='{vlc_base}' vs PL='{pl_base}'", level="DEBUG", verbose=True)
        if vlc_base == pl_base:
            log(f"Removing: {loc.text}", verbose=verbose)
            if not dry_run:
                tracklist.remove(track)
            removed = True

    if removed and not dry_run:
        ET.register_namespace("", XSPF_NS)
        tree.write(playlist_path, encoding="utf-8", xml_declaration=True)
        total_after = len(list(tracklist))
        log(f"Updated playlist: {total_before} → {total_after}", verbose=True)
    elif not removed:
        log("No matching track found to remove.", verbose=verbose)
    else:
        log("Dry-run: playlist not modified.", verbose=verbose)

    return removed


def shuffle_playlist(playlist_path, verbose=False):
    """Randomize order of tracks in playlist."""
    try:
        tree = ET.parse(playlist_path)
        root = tree.getroot()
        tracklist = root.find(".//xspf:trackList", NSMAP)
        if tracklist is None:
            log("No <trackList> found.", level="ERROR")
            return
        tracks = list(tracklist)
        random.shuffle(tracks)
        for t in list(tracklist):
            tracklist.remove(t)
        for t in tracks:
            tracklist.append(t)
        ET.register_namespace("", XSPF_NS)
        tree.write(playlist_path, encoding="utf-8", xml_declaration=True)
        log(f"Shuffled {len(tracks)} tracks.", level="INFO", verbose=True)
    except Exception as e:
        log(f"Shuffle failed: {e}", level="ERROR")


def main():
    parser = argparse.ArgumentParser(description="PlayDog - VLC playlist tracker and pruner.")
    parser.add_argument("--playlist", required=True, help="Path to XSPF playlist")
    parser.add_argument("--host", default="127.0.0.1", help="VLC HTTP host")
    parser.add_argument("--port", type=int, default=8080, help="VLC HTTP port")
    parser.add_argument("--password", help="VLC HTTP password (Lua interface)")
    parser.add_argument("--interval", type=int, default=3, help="Polling interval (s)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logs")
    parser.add_argument("--debug", action="store_true", help="Enable debug (implies verbose)")
    parser.add_argument("--dry-run", action="store_true", help="No write operations")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle playlist and exit")

    args = parser.parse_args()
    if args.debug:
        args.verbose = True

    playlist_path = Path(args.playlist)

    # Shuffle-only mode
    if args.shuffle:
        if not playlist_path.exists():
            log(f"Playlist not found: {playlist_path}", level="ERROR")
            sys.exit(1)
        shuffle_playlist(playlist_path, verbose=args.verbose)
        return

    # Playlist validation
    if not playlist_path.exists():
        log(f"Playlist not found: {playlist_path}", level="ERROR")
        sys.exit(1)

    log(f"Config: host={args.host} port={args.port} playlist={playlist_path} interval={args.interval}", verbose=True)
    count, sample = summarize_playlist(playlist_path, verbose=args.verbose)
    log(f"Playlist tracks={count} sample={sample}", verbose=True)

    seen = set()
    last_name = None
    last_state = None

    while True:
        name = get_current_media(args.host, args.port, args.password, verbose=args.verbose, debug=args.debug)
        if name:
            if name != last_name:
                log(f"VLC now playing: {name}", verbose=True)
                last_name = name
            if name not in seen:
                seen.add(name)
                pruned = prune_from_playlist(playlist_path, name, verbose=args.verbose, debug=args.debug, dry_run=args.dry_run)
                if args.verbose and not pruned:
                    log(f"'{name}' not found in playlist (maybe already removed).", verbose=True)
        else:
            if last_state != "idle":
                log("VLC idle/stopped.", verbose=args.verbose)
                last_state = "idle"
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
