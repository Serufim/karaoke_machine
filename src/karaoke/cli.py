import argparse
import json
import tempfile
import hashlib
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Union

from karaoke.downloader import get_audio_from_source, ensure_project_cover
from karaoke.separator import separate_stems, DEMUCS_MODELS
from karaoke.transcriber import transcribe_vocals, WHISPER_MODELS
from karaoke.aligner import (
    split_into_karaoke_lines,
    lines_to_editor_text,
    editor_text_to_lines,
    validate_karaoke_lines,
)
from karaoke.mixer import (
    mix_guide_vocals,
    ensure_full_guide_mix,
    compute_waveform_peaks,
    detect_chorus_fx_intervals,
)
from karaoke.ass_writer import generate_ass_from_lines
from karaoke.video import render_karaoke_video, extract_cover_edge_colors
from karaoke.cancel_manager import check_cancelled


def analyze_and_transcribe(
    source: str,
    output_dir: Path,
    model_size: str = "large-v3-turbo",
    demucs_model: str = "htdemucs",
    language: str = "ru",
    reference_lyrics: Optional[str] = None,
    use_ctc_align: bool = False,
    device: Optional[str] = None,
    download_video: bool = False,
    cookies_browser: Optional[str] = "chrome",
    cookies_file: Optional[Path] = None,
    custom_cover: Optional[Union[str, Path]] = None,
    custom_bg: Optional[Union[str, Path]] = None,
    condition_on_previous_text: bool = False,
    vad: Optional[str] = "auditok",
    strict_repeats: bool = False,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Stage 1: Acquires audio, extracts cover art and Ambilight edge colors, separates vocals/instrumental
    with Demucs, transcribes and aligns Russian words, computes waveform peaks for the timeline,
    and builds editable state.
    """
    def log(msg: str, progress: float = 0.0):
        check_cancelled()
        print(f"\n>>> {msg}")
        if progress_callback:
            progress_callback(msg, progress)

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"

    log("Шаг 1/4: Получение аудиофайла и извлечение обложки...", 0.10)
    raw_audio, title, cover_path, video_bg = get_audio_from_source(
        source, work_dir,
        download_video=download_video,
        cookies_browser=cookies_browser,
        cookies_file=cookies_file,
    )
    # Gradio uploads are temporary; retain one byte-for-byte project copy.
    if video_bg:
        video_bg = Path(video_bg).resolve()
        try:
            video_bg.relative_to(Path(tempfile.gettempdir()).resolve())
            is_temporary = True
        except ValueError:
            is_temporary = False
        if is_temporary and not video_bg.is_relative_to(work_dir.resolve()):
            signature = f"{video_bg}:{video_bg.stat().st_size}:{video_bg.stat().st_mtime_ns}"
            identity = hashlib.sha256(signature.encode()).hexdigest()[:16]
            stored_video = work_dir / "source_videos" / f"{identity}{video_bg.suffix}"
            stored_video.parent.mkdir(parents=True, exist_ok=True)
            if not stored_video.exists():
                copy_fd, copy_name = tempfile.mkstemp(dir=stored_video.parent, suffix=".part")
                try:
                    with video_bg.open("rb") as original, open(copy_fd, "wb") as target:
                        while chunk := original.read(1024 * 1024):
                            check_cancelled()
                            target.write(chunk)
                    check_cancelled()
                    Path(copy_name).replace(stored_video)
                finally:
                    Path(copy_name).unlink(missing_ok=True)
            video_bg = stored_video.resolve()

    custom_bg_path = None
    if custom_bg and Path(custom_bg).exists():
        custom_bg_p = Path(custom_bg).resolve()
        dest_bg = work_dir / f"{title}_custom_bg{custom_bg_p.suffix.lower()}"
        if custom_bg_p != dest_bg:
            shutil.copy2(custom_bg_p, dest_bg)
        custom_bg_path = dest_bg

    if custom_cover and Path(custom_cover).exists():
        custom_cover_p = Path(custom_cover).resolve()
        dest_cover = work_dir / f"{title}_cover{custom_cover_p.suffix.lower()}"
        if custom_cover_p != dest_cover:
            shutil.copy2(custom_cover_p, dest_cover)
        cover_path = dest_cover
    elif custom_bg_path:
        cover_path = custom_bg_path
    elif not cover_path:
        cover_path = ensure_project_cover(title, work_dir)
    cover_edge_colors = extract_cover_edge_colors(cover_path)

    log(f"Шаг 2/4: Разделение вокала и минуса (Demucs: {demucs_model})...", 0.25)
    vocals_wav, no_vocals_wav = separate_stems(
        audio_path=raw_audio,
        output_dir=work_dir,
        model_name=demucs_model,
        device=device,
    )

    log(f"Шаг 3/4: Распознавание текста и калибровка таймингов ({model_size}, язык={language})...", 0.55)
    transcription = transcribe_vocals(
        vocals_path=vocals_wav,
        model_size=model_size,
        language=language,
        device=device,
        initial_prompt=None,  # Do not feed sequential lyrics as initial_prompt to prevent Whisper intro hallucinations
        use_ctc_align=use_ctc_align,
        condition_on_previous_text=condition_on_previous_text,
        vad=vad,
    )

    alignment_warnings = []
    lines = split_into_karaoke_lines(
        transcription.get("segments", []),
        reference_lyrics=reference_lyrics,
        warnings_out=alignment_warnings,
        vocals_path=vocals_wav,
        strict_repeats=strict_repeats,
    )
    validate_karaoke_lines(lines)
    editor_text = lines_to_editor_text(lines)

    # Compute timeline waveform envelopes and auto-detect chorus FX
    log("Генерация огибающих волны для 3-дорожечного таймлайна...", 0.70)
    inst_peaks, duration = compute_waveform_peaks(no_vocals_wav)
    vocal_peaks, _ = compute_waveform_peaks(vocals_wav)
    auto_fx = detect_chorus_fx_intervals(no_vocals_wav, vocals_wav)

    # Save state for fast re-rendering without re-running AI models
    state_path = work_dir / f"{title}_state.json"
    state_data = {
        "title": title,
        "source": source,
        "source_type": "url" if str(source).startswith(("http://", "https://", "ytsearch")) else "file",
        "source_audio": str(raw_audio.resolve()) if raw_audio and Path(raw_audio).exists() else None,
        "reference_lyrics": reference_lyrics or "",
        "generation_params": {
            "model_size": model_size,
            "demucs_model": demucs_model,
            "language": language,
            "vad": vad,
            "use_ctc_align": use_ctc_align,
            "use_video_bg": bool(video_bg) if not custom_bg_path else False,
            "condition_on_previous_text": condition_on_previous_text,
            "strict_repeats": strict_repeats,
        },
        "vocals_wav": str(vocals_wav),
        "no_vocals_wav": str(no_vocals_wav),
        "cover_image": str(cover_path) if cover_path else None,
        "cover_edge_colors": cover_edge_colors,
        "custom_bg": str(custom_bg_path) if custom_bg_path else None,
        "video_bg": str(video_bg) if video_bg else None,
        "use_video_bg": bool(video_bg) if not custom_bg_path else False,
        "use_cover_bg": False if custom_bg_path else True,
        "lines": lines,
        "editor_text": editor_text,
        "alignment_warnings": alignment_warnings,
        "inst_peaks": inst_peaks,
        "vocal_peaks": vocal_peaks,
        "duration": duration,
        "vocal_intervals": [],
        "fx_intervals": auto_fx,
    }
    state_path.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    lyrics_txt_path = output_dir / f"{title}_lyrics.txt"
    lyrics_txt_path.write_text(editor_text, encoding="utf-8")

    return state_data


def render_from_state(
    state_data: Dict[str, Any],
    output_dir: Path,
    editor_text: Optional[str] = None,
    vocal_volume: float = 0.0,
    vocal_intervals: Optional[List[Dict[str, Any]]] = None,
    num_lines: int = 4,
    background: Optional[Path] = None,
    use_cover_bg: bool = False,
    use_video_bg: bool = False,
    visual_effects: str = "sparkles_pulse",
    edge_color_mode: str = "cyberpunk",
    font_size_mode: str = "large",
    highlight_color: str = "gold_neon",
    video_quality: str = "balanced",
    fx_intervals: Optional[List[Dict[str, Any]]] = None,
    emoji_intervals: Optional[List[Dict[str, Any]]] = None,
    dual_audio_mp4: bool = True,
    watermark_text: Optional[str] = None,
    export_dj_pack: bool = False,
    progress_callback=None,
) -> Tuple[Path, Path, str]:
    """
    Stage 2: Takes prepared state + user's edited lyrics, settings, vocal automation curve,
    and FX timeline, mixes audio, writes ASS with full-perimeter visual effects, and renders Full HD 1080p MP4.
    Returns (final_video_path, mixed_audio_path, updated_editor_text).
    """
    def log(msg: str, progress: float = 0.0):
        check_cancelled()
        print(f"\n>>> {msg}")
        if progress_callback:
            progress_callback(msg, progress)

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"

    title = state_data["title"]
    vocals_wav = Path(state_data["vocals_wav"])
    no_vocals_wav = Path(state_data["no_vocals_wav"])
    original_lines = state_data.get("lines", [])
    cover_image = Path(state_data["cover_image"]) if state_data.get("cover_image") else None
    if not cover_image or not cover_image.exists():
        recovered = ensure_project_cover(title, work_dir)
        if recovered:
            cover_image = recovered
            state_data["cover_image"] = str(recovered)

    cover_edge_colors = state_data.get("cover_edge_colors")
    if not cover_edge_colors and cover_image and cover_image.exists():
        cover_edge_colors = extract_cover_edge_colors(cover_image)
        state_data["cover_edge_colors"] = cover_edge_colors

    if editor_text and editor_text.strip():
        lines = editor_text_to_lines(editor_text, original_lines=original_lines, vocals_path=vocals_wav)
    else:
        lines = original_lines

    validate_karaoke_lines(lines)
    updated_editor_text = lines_to_editor_text(lines)

    # Use vocal_intervals if provided, else from state_data
    active_vocal_intervals = vocal_intervals if vocal_intervals is not None else state_data.get("vocal_intervals", [])
    active_fx_intervals = fx_intervals if fx_intervals is not None else state_data.get("fx_intervals", [])

    log(f"Микширование аудио (базовый вокал {int(round(vocal_volume * 100))}%, зон автоматизации: {len(active_vocal_intervals)})...", 0.75)
    vol_pct = int(round(vocal_volume * 100))
    mixed_wav_path = work_dir / f"{title}_mix_{vol_pct}pct.wav"
    backing_audio = mix_guide_vocals(
        instrumental_path=no_vocals_wav,
        vocals_path=vocals_wav,
        output_path=mixed_wav_path,
        vocal_volume=vocal_volume,
        vocal_intervals=active_vocal_intervals,
    )

    guide_full_wav: Optional[Path] = None
    if dual_audio_mp4 and vocals_wav.exists():
        guide_full_wav = ensure_full_guide_mix(
            instrumental_path=no_vocals_wav,
            vocals_path=vocals_wav,
            output_path=work_dir / f"{title}_guide_100pct.wav",
        )

    effective_watermark = watermark_text if watermark_text is not None else state_data.get("watermark_text")

    if use_cover_bg:
        background = None
    elif background is None and (use_video_bg or state_data.get("use_video_bg", bool(state_data.get("video_bg")))) and state_data.get("video_bg"):
        candidate_bg = Path(state_data["video_bg"])
        if not candidate_bg.exists():
            raise FileNotFoundError("Исходное видео проекта недоступно. Выберите замену в поле «Свой фон».")
        background = candidate_bg
    elif background is None and state_data.get("custom_bg") and Path(state_data["custom_bg"]).exists() and not use_cover_bg:
        background = Path(state_data["custom_bg"])

    has_cover_card = bool(use_cover_bg and cover_image and cover_image.exists() and not (background and Path(background).exists()))

    # Collect emoji positions from lyrics for native Apple Color Emoji rendering
    lyric_emoji_events: List[Dict[str, Any]] = []

    log(f"Генерация субтитров и спецэффектов ({num_lines} строки, FX={visual_effects}, стиль={edge_color_mode}, шрифт={font_size_mode}, цвет={highlight_color}, зон FX: {len(active_fx_intervals)})...", 0.82)
    ass_path = output_dir / f"{title}_karaoke.ass"
    generate_ass_from_lines(
        lines=lines,
        output_path=ass_path,
        title=title,
        num_lines=num_lines,
        visual_effects=visual_effects,
        fx_intervals=active_fx_intervals,
        audio_for_pulse=no_vocals_wav,
        edge_color_mode=edge_color_mode,
        cover_edge_colors=cover_edge_colors,
        has_cover_card=has_cover_card,
        emoji_events_out=lyric_emoji_events,
        font_size_mode=font_size_mode,
        highlight_color=highlight_color,
        watermark_text=effective_watermark,
    )

    # 1. Native Apple Color Emoji in lyrics (replaces tofu squares)
    from karaoke.emoji_layer import (
        build_lyric_emoji_sequence,
        generate_emoji_particles,
        save_particle_sprites,
    )
    total_duration = float(state_data.get("duration") or (lines[-1][-1]["end"] + 3.0 if lines else 60.0))
    lyric_concat = build_lyric_emoji_sequence(lyric_emoji_events, work_dir, total_duration)

    # 2. Flying Apple Color Emoji particles for 'emoji_burst' (independent or from FX intervals)
    active_emoji_intervals = emoji_intervals if emoji_intervals is not None else state_data.get("emoji_intervals", [])
    if visual_effects == "none":
        emoji_fx_itvs = []
    elif active_emoji_intervals:
        emoji_fx_itvs = [
            {
                "start": float(itv.get("start", 0.0)),
                "end": float(itv.get("end", total_duration)),
                "effect": "emoji_burst",
                "intensity": float(itv.get("intensity", 0.85)),
                "emojis": itv.get("emojis") or "🔥✨🎤👑",
            }
            for itv in active_emoji_intervals
        ]
    else:
        emoji_fx_itvs = [itv for itv in active_fx_intervals if itv.get("effect") in ("emoji_burst", "emoji_pulse")]
        if not emoji_fx_itvs and visual_effects in ("emoji_burst", "emoji_pulse") and active_fx_intervals:
            emoji_fx_itvs = [
                {
                    "start": float(itv.get("start", 0.0)),
                    "end": float(itv.get("end", total_duration)),
                    "effect": visual_effects,
                    "intensity": float(itv.get("intensity", 0.85)),
                    "emojis": itv.get("emojis") or "🔥✨🎤👑",
                }
                for itv in active_fx_intervals
            ]

    emoji_particles = []
    emoji_sprites = {}
    if emoji_fx_itvs:
        emoji_particles = generate_emoji_particles(emoji_fx_itvs)
        if emoji_particles:
            emoji_sprites = save_particle_sprites(emoji_particles, work_dir)

    log(f"Шаг 4/4: Рендеринг финального караоке-видео в Full HD 1080p ({video_quality})...", 0.90)
    final_video_path = output_dir / f"{title}_karaoke.mp4"
    render_karaoke_video(
        instrumental_audio=backing_audio,
        ass_subtitles=ass_path,
        output_video=final_video_path,
        background=background,
        cover_image=cover_image,
        use_cover_bg=use_cover_bg,
        video_quality=video_quality,
        lyric_emoji_concat=lyric_concat,
        emoji_particles=emoji_particles,
        emoji_sprites=emoji_sprites,
        guide_vocal_audio=guide_full_wav,
        progress_callback=progress_callback,
    )

    if export_dj_pack:
        from karaoke.pro_exporter import export_dj_master_pack
        export_dj_master_pack(
            state_data=state_data,
            output_dir=output_dir,
            editor_text=updated_editor_text,
            vocal_volume=vocal_volume,
            vocal_intervals=active_vocal_intervals,
            progress_callback=progress_callback,
        )

    log(f"Готово! Караоке 1080p сохранено: {final_video_path}", 1.0)
    return final_video_path, backing_audio, updated_editor_text


def run_pipeline(
    source: str,
    output_dir: Path,
    background: Optional[Path] = None,
    use_cover_bg: bool = True,
    use_video_bg: bool = False,
    visual_effects: str = "sparkles_pulse",
    edge_color_mode: str = "cyberpunk",
    font_size_mode: str = "large",
    highlight_color: str = "gold_neon",
    video_quality: str = "balanced",
    model_size: str = "large-v3-turbo",
    demucs_model: str = "htdemucs",
    language: Optional[str] = "ru",
    vocal_volume: float = 0.0,
    num_lines: int = 4,
    reference_lyrics: Optional[str] = None,
    use_ctc_align: bool = False,
    device: Optional[str] = None,
    cookies_browser: Optional[str] = "chrome",
    cookies_file: Optional[Path] = None,
    dual_audio_mp4: bool = True,
    watermark_text: Optional[str] = None,
    export_dj_pack: bool = False,
) -> Path:
    state_data = analyze_and_transcribe(
        source=source,
        output_dir=output_dir,
        model_size=model_size,
        demucs_model=demucs_model,
        language=language or "ru",
        reference_lyrics=reference_lyrics,
        use_ctc_align=use_ctc_align,
        device=device,
        download_video=use_video_bg,
        cookies_browser=cookies_browser,
        cookies_file=cookies_file,
    )
    # If source was a video, automatically use it as background unless explicit background provided
    effective_use_video_bg = use_video_bg or bool(state_data.get("video_bg") and not background)

    final_video, _, _ = render_from_state(
        state_data=state_data,
        output_dir=output_dir,
        editor_text=state_data["editor_text"],
        vocal_volume=vocal_volume,
        num_lines=num_lines,
        background=background,
        use_cover_bg=use_cover_bg,
        use_video_bg=effective_use_video_bg,
        visual_effects=visual_effects,
        edge_color_mode=edge_color_mode,
        font_size_mode=font_size_mode,
        highlight_color=highlight_color,
        video_quality=video_quality,
        dual_audio_mp4=dual_audio_mp4,
        watermark_text=watermark_text,
        export_dj_pack=export_dj_pack,
    )
    return final_video


def main():
    parser = argparse.ArgumentParser(description="AI Karaoke Generator (Local)")
    parser.add_argument("source", help="Path to audio file, video file (MP4/MOV), or YouTube URL")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    parser.add_argument("--bg", default=None, help="Background image or video file")
    parser.add_argument("--no-cover-bg", action="store_true", help="Disable using extracted cover art as background")
    parser.add_argument("--use-video-bg", action="store_true", help="Download and use original YouTube video as background")
    parser.add_argument("--cookies-browser", default="chrome", choices=["chrome", "safari", "yandex", "firefox", "brave", "edge", "none"], help="Browser to extract YouTube cookies from")
    parser.add_argument("--cookies-file", default=None, help="Path to cookies.txt file for YouTube")
    parser.add_argument("--fx", default="sparkles_pulse", choices=["sparkles_pulse", "sparkles", "pulse", "climax", "emoji_burst", "emoji_pulse", "police_strobe", "green_neon", "none"], help="Visual effects")
    parser.add_argument("--edge-color", default="cyberpunk", choices=["cyberpunk", "pink", "blue", "purple", "fire", "cover_colors", "neon_rainbow", "police", "green_neon"], help="Edge pulse color mode")
    parser.add_argument("--font-size", default="large", choices=["standard", "large", "huge"], help="Karaoke font size")
    parser.add_argument("--highlight-color", default="gold_neon", choices=["gold_neon", "electric_cyan", "neon_magenta", "acid_lime", "green_neon", "emerald", "fire_orange"], help="Karaoke sweep highlight color")
    parser.add_argument("--video-quality", default="balanced", choices=["light", "balanced", "hq"], help="Video bitrate and quality")
    parser.add_argument("--model-size", default="large-v3-turbo", choices=WHISPER_MODELS, help="Whisper model")
    parser.add_argument("--demucs-model", default="htdemucs", choices=DEMUCS_MODELS, help="Demucs stem model")
    parser.add_argument("--language", default="ru", help="Language code (default: ru)")
    parser.add_argument("--vocal-volume", type=float, default=0.0, help="Guide vocal volume (0.00 to 1.00)")
    parser.add_argument("--num-lines", type=int, default=4, choices=[3, 4], help="Karaoke lines on screen (3 or 4)")
    parser.add_argument("--reference-lyrics", default=None, help="Reference text file for alignment")
    parser.add_argument("--use-ctc", action="store_true", help="Enable Cyrillic Wav2Vec2 CTC alignment")
    parser.add_argument("--watermark", default=None, help="Custom DJ / Club branding watermark text in top-right corner")
    parser.add_argument("--no-dual-audio", action="store_true", help="Disable multiplexing the 2nd 100%% vocal guide audio track into MP4")
    parser.add_argument("--export-dj-pack", action="store_true", help="Also export professional DJ pack (.kfn, .cdg.zip, .lrc, UltraStar .txt)")

    args = parser.parse_args()
    ref_txt = Path(args.reference_lyrics).read_text(encoding="utf-8") if args.reference_lyrics else None
    c_file = Path(args.cookies_file) if args.cookies_file else None

    run_pipeline(
        source=args.source,
        output_dir=Path(args.output_dir),
        background=Path(args.bg) if args.bg else None,
        use_cover_bg=not args.no_cover_bg,
        use_video_bg=args.use_video_bg,
        visual_effects=args.fx,
        edge_color_mode=args.edge_color,
        font_size_mode=args.font_size,
        highlight_color=args.highlight_color,
        video_quality=args.video_quality,
        model_size=args.model_size,
        demucs_model=args.demucs_model,
        language=args.language,
        vocal_volume=args.vocal_volume,
        num_lines=args.num_lines,
        reference_lyrics=ref_txt,
        use_ctc_align=args.use_ctc,
        cookies_browser=args.cookies_browser,
        cookies_file=c_file,
        dual_audio_mp4=not args.no_dual_audio,
        watermark_text=args.watermark,
        export_dj_pack=args.export_dj_pack,
    )


if __name__ == "__main__":
    main()
