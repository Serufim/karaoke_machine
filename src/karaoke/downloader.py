import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Tuple, Optional
import yt_dlp
from karaoke.cancel_manager import check_cancelled, run_cancellable_command, GenerationCancelledError
from karaoke.media import probe_media, video_streams, audio_duration


def sanitize_filename(name: str) -> str:
    """Removes invalid characters for file names."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def is_url(source: str) -> bool:
    """Checks if input string is a valid web URL."""
    return source.startswith("http://") or source.startswith("https://")


def find_ffmpeg_bin() -> str:
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        shutil.which("ffmpeg"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return "ffmpeg"


def extract_cover_art(source_path: Path, output_cover_path: Path) -> Optional[Path]:
    """
    Extracts embedded album cover art (ID3v2 APIC / attached picture) from MP3, M4A, FLAC, etc.
    """
    if not source_path.exists():
        return None
    ffmpeg_bin = find_ffmpeg_bin()
    output_cover_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(source_path),
        "-an",
        "-vcodec",
        "png",
        "-frames:v",
        "1",
        str(output_cover_path),
    ]
    try:
        run_cancellable_command(cmd, prefix="Обложка")
        if output_cover_path.exists() and output_cover_path.stat().st_size > 1000:
            return output_cover_path
    except GenerationCancelledError:
        raise
    except Exception:
        pass
    return None


def ensure_project_cover(title: str, work_dir: Path) -> Optional[Path]:
    """
    Finds or recovers cover art for a project:
    1. Checks if {title}_cover.png exists in work_dir.
    2. Searches TMPDIR/gradio for original uploaded {title}.mp3 and extracts cover.
    """
    direct_cover = work_dir / f"{title}_cover.png"
    if direct_cover.exists() and direct_cover.stat().st_size > 1000:
        return direct_cover

    # Scan for any temp uploaded mp3 matching title
    tmp_root = tempfile.gettempdir()
    clean_title = sanitize_filename(title).lower()
    for root, _, files in os.walk(tmp_root):
        if "gradio" not in root.lower():
            continue
        for f in files:
            if f.lower().endswith((".mp3", ".m4a", ".flac")):
                clean_f = sanitize_filename(Path(f).stem).lower()
                if clean_title in clean_f or clean_f in clean_title:
                    candidate = Path(root) / f
                    cover = extract_cover_art(candidate, direct_cover)
                    if cover:
                        return cover
    return None


def find_node_bin() -> Optional[str]:
    """Finds Node.js binary for yt-dlp JavaScript challenge solver."""
    candidates = [
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
        shutil.which("node"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def get_audio_from_source(
    source: str,
    output_dir: Path,
    download_video: bool = False,
    cookies_browser: Optional[str] = "chrome",
    cookies_file: Optional[Path] = None,
) -> Tuple[Path, str, Optional[Path], Optional[Path]]:
    """
    Downloads audio and optional video if source is a URL, or verifies and prepares local file.
    Extracts cover art if available.
    Returns: (path_to_audio_file, title, path_to_cover_art_or_None, path_to_video_bg_or_None)
    """
    check_cancelled()
    output_dir.mkdir(parents=True, exist_ok=True)
    cover_path: Optional[Path] = None
    video_bg_path: Optional[Path] = None

    if is_url(source):
        def _yt_progress_hook(d):
            check_cancelled()

        if download_video:
            # Download high quality video (up to 1080p) + audio, then extract WAV
            ydl_opts = {
                'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
                'outtmpl': str(output_dir / '%(title)s_raw.%(ext)s'),
                'writethumbnail': True,
                'progress_hooks': [_yt_progress_hook],
                'postprocessors': [
                    {
                        'key': 'FFmpegThumbnailsConvertor',
                        'format': 'png',
                    },
                ],
                'quiet': True,
                'no_warnings': True,
            }
        else:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(output_dir / '%(title)s.%(ext)s'),
                'writethumbnail': True,
                'progress_hooks': [_yt_progress_hook],
                'postprocessors': [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'wav',
                    },
                    {
                        'key': 'FFmpegThumbnailsConvertor',
                        'format': 'png',
                    },
                ],
                'quiet': True,
                'no_warnings': True,
            }

        # Configure Node JS runtime and remote component for challenge solver (anti-bot)
        node_bin = find_node_bin()
        if node_bin:
            ydl_opts['js_runtimes'] = {'node': {'path': node_bin}}
        ydl_opts['remote_components'] = ['ejs:github']

        # Cookie configuration for YouTube anti-bot verification
        if cookies_file and Path(cookies_file).exists():
            ydl_opts['cookiefile'] = str(cookies_file)
        elif cookies_browser and str(cookies_browser).lower() not in ("none", "null", ""):
            b_name = str(cookies_browser).lower()
            ydl_opts['cookiesfrombrowser'] = (b_name,)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source, download=True)
                check_cancelled()
                title = info.get('title', 'downloaded_song')
                sanitized = sanitize_filename(title)

                if download_video:
                    # Resolve this download only; never pick a different project's clip.
                    candidates = [info.get("filepath"), ydl.prepare_filename(info)]
                    candidates += [item.get("filepath") for item in info.get("requested_downloads", [])]
                    raw_video = next((Path(name) for name in candidates if name and Path(name).is_file()), None)
                    if raw_video is None:
                        raise FileNotFoundError(f"Не найден скачанный видеофайл: {sanitized}")
                    ffmpeg_bin = find_ffmpeg_bin()
                    metadata = probe_media(raw_video, ffmpeg_bin)
                    if not video_streams(metadata):
                        raise ValueError("В скачанном файле нет видеодорожки.")
                    audio_duration(metadata)
                    video_target = output_dir / f"{sanitized}_yt_video{raw_video.suffix}"
                    if raw_video != video_target:
                        shutil.move(raw_video, video_target)
                    video_bg_path = video_target
                    wav_path = output_dir / f"{sanitized}.wav"
                    run_cancellable_command(
                        [ffmpeg_bin, "-y", "-i", str(video_bg_path), "-map", "0:a:0", "-vn",
                         "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(wav_path)],
                        prefix="Извлечение аудио",
                    )
                else:
                    wav_path = output_dir / f"{title}.wav"
                    if not wav_path.exists():
                        candidates = list(output_dir.glob("*.wav"))
                        if candidates:
                            wav_path = max(candidates, key=os.path.getctime)
                        else:
                            raise FileNotFoundError(f"Could not locate downloaded audio for {title}")

                # Check downloaded thumbnail
                thumb_candidates = list(output_dir.glob(f"{sanitized}*.png")) + list(output_dir.glob("*.png"))
                for tc in thumb_candidates:
                    if tc.name != "default_bg.png" and not tc.name.endswith("_mix.png"):
                        cover_target = output_dir / f"{sanitized}_cover.png"
                        if tc != cover_target:
                            shutil.copy(tc, cover_target)
                        cover_path = cover_target
                        break

                return wav_path, sanitized, cover_path, video_bg_path
        except yt_dlp.utils.DownloadError as e:
            err_msg = str(e)
            if "Sign in to confirm you’re not a bot" in err_msg or "confirm you're not a bot" in err_msg:
                raise RuntimeError(
                    "YouTube заблокировал скачивание защитой от ботов ('Sign in to confirm you’re not a bot').\n\n"
                    "Способы решения:\n"
                    "1. В правой панели в '🍪 Настройки YouTube' выберите браузер с активной авторизацией на YouTube (Chrome, Safari, Yandex).\n"
                    "2. Либо загрузите файл cookies.txt.\n"
                    "3. Либо скачайте видеофайл вручную и загрузите его прямо в поле '🎬 2. Загрузите готовое видео'!"
                ) from e
            raise
    else:
        file_path = Path(source).expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        title = sanitize_filename(file_path.stem)
        target_cover = output_dir / f"{title}_cover.png"
        metadata = probe_media(file_path, find_ffmpeg_bin())
        is_video = bool(video_streams(metadata))

        if is_video:
            video_bg_path = file_path
            # Extract sample-accurate 44.1kHz 16-bit WAV for Demucs & Whisper
            wav_path = output_dir / f"{title}.wav"
            ffmpeg_bin = find_ffmpeg_bin()
            audio_duration(metadata)
            run_cancellable_command(
                [ffmpeg_bin, "-y", "-i", str(file_path), "-map", "0:a:0", "-vn",
                 "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(wav_path)],
                prefix="Извлечение аудио",
            )
            # Try embedded album art first, then capture frame at 3s if not present
            cover_path = extract_cover_art(file_path, target_cover)
            if not cover_path or not cover_path.exists():
                try:
                    run_cancellable_command(
                        [ffmpeg_bin, "-y", "-ss", "00:00:00", "-i", str(file_path), "-frames:v", "1", str(target_cover)],
                        prefix="Кадр обложки",
                    )
                    if target_cover.exists() and target_cover.stat().st_size > 1000:
                        cover_path = target_cover
                except GenerationCancelledError:
                    raise
                except Exception:
                    pass
            return wav_path, title, cover_path, video_bg_path
        else:
            cover_path = extract_cover_art(file_path, target_cover)
            return file_path, title, cover_path, None
