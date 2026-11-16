"""
Free lyrics and LRC timing lookup via LRCLIB (https://lrclib.net).
No API key or account required. Synced LRC results can be converted into
sparse timing pegs ([mm:ss.xx] line) so alignment stays anchored across
verses and long instrumental breaks without blindly locking every word.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

LRCLIB_BASE = (os.environ.get("KARAOKE_LYRICS_API") or "https://lrclib.net").rstrip("/")
LRCLIB_TIMEOUT = int(os.environ.get("KARAOKE_LYRICS_TIMEOUT") or 12)

_LRC_TAG_RE = re.compile(r"^\s*(\[[0-9]{1,3}:[0-9]{2}(?:[.:][0-9]{1,3})?\]\s*)+")
_ONE_TAG_RE = re.compile(r"^\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


class LyricsFetchError(RuntimeError):
    """Raised when LRCLIB cannot be reached or returns an invalid payload."""


def strip_lrc_tags(synced_lyrics: str) -> str:
    """Strips all [mm:ss.xx] LRC timestamps from synced lyrics, leaving plain lines."""
    if not synced_lyrics:
        return ""
    lines = [_LRC_TAG_RE.sub("", ln).strip() for ln in synced_lyrics.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def extract_sparse_pegs_lrc(
    synced_lyrics: str,
    every: int = 4,
    gap: float = 4.0,
) -> str:
    """
    Keeps LRC timestamps as sparse anchor pegs:
    - on the first sung line,
    - whenever a pause >= `gap` seconds occurs before a line,
    - otherwise once every `every` lines.
    """
    synced = (synced_lyrics or "").strip()
    if not synced:
        return ""

    out: List[str] = []
    prev: float | None = None
    since = 0
    pegged = False

    for raw in synced.splitlines():
        s_raw = raw.strip()
        m = _ONE_TAG_RE.match(s_raw)
        words = _LRC_TAG_RE.sub("", s_raw).strip()
        if not words:
            continue
        t: float | None = None
        if m:
            t = int(m.group(1)) * 60.0 + float(m.group(2).replace(":", "."))
        take = t is not None and (
            not pegged
            or since >= every
            or (prev is not None and t - prev >= gap)
        )
        if take and t is not None:
            out.append(f"[{int(t // 60)}:{t % 60:05.2f}] {words}")
            since = 0
            pegged = True
        else:
            out.append(words)
            since += 1
        if t is not None:
            prev = t
    return "\n".join(out).strip()


def _ask_lrclib(path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    url = f"{LRCLIB_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AIKaraokeStudio/0.6 (https://github.com/serufim0/karaoke_generator)"
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=LRCLIB_TIMEOUT) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise LyricsFetchError(f"LRCLIB ответил кодом {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise LyricsFetchError(f"Не удалось подключиться к LRCLIB: {reason}") from e
    except ValueError as e:
        raise LyricsFetchError("LRCLIB вернул некорректный JSON") from e

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def search_lrclib(
    track: str,
    artist: str = "",
    duration: float = 0.0,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Searches LRCLIB by track (and optional artist). Results are sorted by
    proximity to `duration` when provided.
    """
    q_track = (track or "").strip()
    if not q_track:
        raise LyricsFetchError("Введите название трека для поиска текста.")

    params: Dict[str, Any] = {"track_name": q_track}
    if artist and artist.strip():
        params["artist_name"] = artist.strip()

    found = _ask_lrclib("/api/search", params)
    if not found and artist and artist.strip():
        found = _ask_lrclib("/api/search", {"q": q_track})
    elif not found:
        found = _ask_lrclib("/api/search", {"q": q_track})

    results: List[Dict[str, Any]] = []
    for item in found:
        synced = (item.get("syncedLyrics") or "").strip()
        plain = (item.get("plainLyrics") or "").strip() or strip_lrc_tags(synced)
        if not plain:
            continue
        pegged = extract_sparse_pegs_lrc(synced) if synced else ""
        results.append({
            "source": "LRCLIB",
            "title": item.get("trackName") or q_track,
            "artist": item.get("artistName") or "",
            "duration": float(item.get("duration") or 0.0),
            "lines_count": len([ln for ln in plain.splitlines() if ln.strip()]),
            "text": plain,
            "timed": bool(pegged),
            "text_timed": pegged,
        })

    if duration and duration > 0:
        results.sort(key=lambda r: abs((r["duration"] or 0.0) - float(duration)))
    return results[: max(1, int(limit))]
