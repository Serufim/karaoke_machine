import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Cache duration in seconds (20 minutes)
CACHE_TTL = 1200
_CHARTS_CACHE: Dict[str, Dict[str, Any]] = {}


@dataclass
class ChartTrack:
    rank: int
    title: str
    artist: str
    cover_url: Optional[str]
    platform: str
    trend: Optional[str] = None  # e.g. "+2", "-1", "NEW", "—"
    search_query: str = ""
    external_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d["search_query"]:
            d["search_query"] = f"{self.artist} - {self.title}"
        return d


def _get_cached(cache_key: str) -> Optional[List[Dict[str, Any]]]:
    now = time.time()
    if cache_key in _CHARTS_CACHE:
        entry = _CHARTS_CACHE[cache_key]
        if now - entry["timestamp"] < CACHE_TTL:
            return entry["data"]
    return None


def _set_cache(cache_key: str, data: List[Dict[str, Any]]) -> None:
    _CHARTS_CACHE[cache_key] = {
        "timestamp": time.time(),
        "data": data,
    }


def fetch_yandex_chart(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetches official Top-100 chart from Yandex Music public JSON endpoint.
    No authentication or API key required.
    """
    cache_key = f"yandex_{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = "https://api.music.yandex.net/landing3/chart"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )

    results: List[Dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            chart_entries = data.get("result", {}).get("chart", {}).get("tracks", [])

            for item in chart_entries[:limit]:
                track = item.get("track", {})
                chart_info = item.get("chart", {})
                pos = chart_info.get("position", len(results) + 1)
                progress = chart_info.get("progress")

                trend_str = None
                if progress == "new":
                    trend_str = "NEW"
                elif progress == "up":
                    shift = chart_info.get("shift", 0)
                    trend_str = f"+{shift}" if shift else "▲"
                elif progress == "down":
                    shift = chart_info.get("shift", 0)
                    trend_str = f"-{shift}" if shift else "▼"
                elif progress == "same":
                    trend_str = "—"

                artists_list = [a.get("name", "") for a in track.get("artists", []) if a.get("name")]
                artist_name = ", ".join(artists_list) if artists_list else "Неизвестный исполнитель"
                track_title = track.get("title", "Без названия")
                version = track.get("version")
                if version:
                    track_title = f"{track_title} ({version})"

                cover_uri = track.get("coverUri")
                cover_url = None
                if cover_uri:
                    cover_url = f"https://{cover_uri.replace('%%', '400x400')}"

                ct = ChartTrack(
                    rank=pos,
                    title=track_title,
                    artist=artist_name,
                    cover_url=cover_url,
                    platform="yandex",
                    trend=trend_str,
                    search_query=f"{artist_name} - {track_title}",
                    external_url=f"https://music.yandex.ru/track/{track.get('id')}" if track.get("id") else None,
                )
                results.append(ct.to_dict())

        _set_cache(cache_key, results)
    except Exception as e:
        logger.error(f"Error fetching Yandex Music chart: {e}")
        if cache_key in _CHARTS_CACHE:
            return _CHARTS_CACHE[cache_key]["data"]
        # If no cache exists, return empty or re-raise
        raise

    return results


def fetch_apple_chart(country: str = "ru", limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetches top songs from official Apple Music RSS/JSON feeds.
    Supports 'ru', 'vn', 'us', 'gb', etc. No authentication required.
    """
    valid_country = country.lower().strip()
    cache_key = f"apple_{valid_country}_{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # Apple marketing tools prefers 25, 50, 100
    feed_limit = max(10, min(100, limit))
    url = f"https://rss.applemarketingtools.com/api/v2/{valid_country}/music/most-played/{feed_limit}/songs.json"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )

    results: List[Dict[str, Any]] = []
    # Try up to 2 times
    last_err = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                entries = data.get("feed", {}).get("results", [])

                for idx, item in enumerate(entries[:limit], start=1):
                    track_title = item.get("name", "Без названия")
                    artist_name = item.get("artistName", "Неизвестный исполнитель")
                    artwork_url = item.get("artworkUrl100")
                    if artwork_url:
                        artwork_url = artwork_url.replace("100x100bb.jpg", "600x600bb.jpg")

                    ct = ChartTrack(
                        rank=idx,
                        title=track_title,
                        artist=artist_name,
                        cover_url=artwork_url,
                        platform="apple",
                        trend=None,
                        search_query=f"{artist_name} - {track_title}",
                        external_url=item.get("url"),
                    )
                    results.append(ct.to_dict())

            _set_cache(cache_key, results)
            return results
        except Exception as e:
            last_err = e
            time.sleep(0.5)

    logger.error(f"Error fetching Apple Music chart ({valid_country}): {last_err}")
    if cache_key in _CHARTS_CACHE:
        return _CHARTS_CACHE[cache_key]["data"]
    if last_err:
        raise last_err
    return results


def fetch_spotify_chart(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetches Global Top songs from public Spotify web charts endpoint.
    No authentication required.
    """
    cache_key = f"spotify_global_{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = "https://charts-spotify-com-service.spotify.com/public/v0/charts"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )

    results: List[Dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            views = data.get("chartEntryViewResponses", [])
            entries = views[0].get("entries", []) if views else []

            for idx, item in enumerate(entries[:limit], start=1):
                meta = item.get("trackMetadata", {})
                chart_data = item.get("chartEntryData", {})

                track_title = meta.get("trackName", "Без названия")
                artists_list = [a.get("name", "") for a in meta.get("artists", []) if a.get("name")]
                artist_name = ", ".join(artists_list) if artists_list else "Неизвестный исполнитель"

                rank = chart_data.get("currentRank", idx)
                prev_rank = chart_data.get("previousRank")

                trend_str = None
                if prev_rank == -1 or prev_rank is None:
                    trend_str = "NEW"
                elif prev_rank > rank:
                    trend_str = f"+{prev_rank - rank}"
                elif prev_rank < rank:
                    trend_str = f"-{rank - prev_rank}"
                else:
                    trend_str = "—"

                cover_url = meta.get("displayImageUri")

                ct = ChartTrack(
                    rank=rank,
                    title=track_title,
                    artist=artist_name,
                    cover_url=cover_url,
                    platform="spotify",
                    trend=trend_str,
                    search_query=f"{artist_name} - {track_title}",
                    external_url=meta.get("trackUri"),
                )
                results.append(ct.to_dict())

        _set_cache(cache_key, results)
    except Exception as e:
        logger.error(f"Error fetching Spotify chart: {e}")
        if cache_key in _CHARTS_CACHE:
            return _CHARTS_CACHE[cache_key]["data"]
        raise

    return results


def get_platform_chart(platform: str, country: str = "ru", limit: int = 50) -> Dict[str, Any]:
    """
    Unified router for fetching charts across platforms.
    """
    p = platform.lower().strip()
    try:
        if p == "yandex":
            tracks = fetch_yandex_chart(limit=limit)
            return {
                "status": "ok",
                "platform": "yandex",
                "platform_name": "Яндекс Музыка",
                "country": "ru",
                "description": "Официальный Топ-100 треков в России",
                "tracks": tracks,
            }
        elif p == "apple":
            tracks = fetch_apple_chart(country=country, limit=limit)
            country_names = {
                "ru": "Россия 🇷🇺",
                "vn": "Вьетнам 🇻🇳",
                "us": "США / Global 🇺🇸",
                "gb": "Великобритания 🇬🇧",
                "kz": "Казахстан 🇰🇿",
            }
            return {
                "status": "ok",
                "platform": "apple",
                "platform_name": "Apple Music",
                "country": country,
                "description": f"Топ-50 Apple Music — {country_names.get(country, country.upper())}",
                "tracks": tracks,
            }
        elif p == "spotify":
            tracks = fetch_spotify_chart(limit=limit)
            return {
                "status": "ok",
                "platform": "spotify",
                "platform_name": "Spotify",
                "country": "global",
                "description": "Global Top-50 треков в Spotify",
                "tracks": tracks,
            }
        elif p == "zvuk":
            return {
                "status": "protected",
                "platform": "zvuk",
                "platform_name": "СберЗвук",
                "country": "ru",
                "description": "СберЗвук защищен антифрод-системой Servicepipe (требуется сессия браузера)",
                "message": "Прямой анонимный доступ к чартам СберЗвука заблокирован защитой платформы Servicepipe.",
                "tracks": [],
            }
        elif p == "vk":
            return {
                "status": "auth_required",
                "platform": "vk",
                "platform_name": "ВК Музыка",
                "country": "ru",
                "description": "ВКонтакте требует обязательный пользовательский access_token для аудио",
                "message": "Аудио-раздел ВКонтакте закрыт для публичных запросов без авторизованного аккаунта.",
                "tracks": [],
            }
        else:
            return {
                "status": "error",
                "platform": platform,
                "platform_name": platform,
                "message": f"Неизвестная платформа: {platform}",
                "tracks": [],
            }
    except Exception as e:
        logger.exception(f"Failed to fetch chart for {platform}: {e}")
        return {
            "status": "error",
            "platform": platform,
            "platform_name": platform,
            "message": f"Ошибка загрузки чарта: {e}",
            "tracks": [],
        }
