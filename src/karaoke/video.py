import os
import shutil
import subprocess
import colorsys
import tempfile
import math
from karaoke.render_progress import RenderProgress
from karaoke.media import probe_media, video_streams, audio_duration
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from karaoke.cancel_manager import (
    check_cancelled,
    run_cancellable_command,
    GenerationCancelledError,
)


def find_ffmpeg() -> str:
    """Finds ffmpeg binary with preference for ffmpeg-full."""
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        shutil.which("ffmpeg")
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return "ffmpeg"


def _rgb_to_vibrant_ass(r: float, g: float, b: float) -> str:
    """
    Converts RGB (0..255) to a vibrant, high-saturation ASS color string &H00BBGGRR&
    suitable for glowing neon/Ambilight borders.
    """
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    # Boost saturation and brightness so dark/grey cover edges still glow vividly
    if s < 0.15:
        # Near-greyscale cover edge: shift toward warm gold/cyan/magenta accent
        s = 0.75
        h = (h + 0.55) % 1.0
    else:
        s = max(0.78, min(1.0, s * 1.45))
    v = max(0.92, min(1.0, v * 1.35))
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    ri = max(0, min(255, int(round(nr * 255))))
    gi = max(0, min(255, int(round(ng * 255))))
    bi = max(0, min(255, int(round(nb * 255))))
    return f"&H00{bi:02X}{gi:02X}{ri:02X}&"


def extract_cover_edge_colors(cover_path: Optional[Path]) -> Dict[str, str]:
    """
    Samples the 4 edges (top, bottom, left, right) of an album cover image
    and returns vibrant ASS hex color strings (&H00BBGGRR&) for Ambilight edge pulsing.
    """
    default_colors = {
        "top": "&H00FFFF00&",     # Cyan
        "bottom": "&H00FF00FF&",  # Magenta
        "left": "&H0000D7FF&",    # Gold
        "right": "&H00FF55AA&",   # Electric Purple
    }
    if not cover_path or not Path(cover_path).exists():
        return default_colors

    try:
        img = Image.open(cover_path).convert("RGB").resize((120, 120), Image.Resampling.BILINEAR)
        w, h = img.size
        band = 18

        def avg_region(box):
            crop = img.crop(box)
            pixels = list(crop.getdata())
            if not pixels:
                return (0, 215, 255)
            # Weight colorful pixels higher than black/white pixels
            total_w = 0.0
            sr, sg, sb = 0.0, 0.0, 0.0
            for pr, pg, pb in pixels:
                mx = max(pr, pg, pb)
                mn = min(pr, pg, pb)
                sat = (mx - mn) / (mx + 1.0)
                lum = (pr + pg + pb) / (3.0 * 255.0)
                weight = 0.2 + sat * 2.5 + (0.8 if 0.15 < lum < 0.90 else 0.1)
                sr += pr * weight
                sg += pg * weight
                sb += pb * weight
                total_w += weight
            return (sr / total_w, sg / total_w, sb / total_w)

        top_rgb = avg_region((0, 0, w, band))
        bottom_rgb = avg_region((0, h - band, w, h))
        left_rgb = avg_region((0, 0, band, h))
        right_rgb = avg_region((w - band, 0, w, h))

        return {
            "top": _rgb_to_vibrant_ass(*top_rgb),
            "bottom": _rgb_to_vibrant_ass(*bottom_rgb),
            "left": _rgb_to_vibrant_ass(*left_rgb),
            "right": _rgb_to_vibrant_ass(*right_rgb),
        }
    except Exception as e:
        print(f"[Karaoke] Warning: Could not sample cover edge colors: {e}")
        return default_colors


def create_default_background(output_path: Path, width: int = 1920, height: int = 1080) -> Path:
    """Creates a stylish Full HD 1920x1080 dark radial/linear gradient background."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        return output_path

    image = Image.new("RGB", (width, height), "#0d0e15")
    draw = ImageDraw.Draw(image)

    # Draw smooth vertical gradient: dark navy (#0B0C10) to deep violet-black (#1F1A24)
    for y in range(height):
        ratio = y / height
        r = int(11 + (31 - 11) * ratio)
        g = int(12 + (26 - 12) * ratio)
        b = int(16 + (36 - 16) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    image.save(output_path, "PNG")
    return output_path


def prepare_background_image(
    input_path: Path,
    output_path: Path,
    width: int = 1920,
    height: int = 1080
) -> Path:
    """
    If background image is not 16:9 (square, portrait, 4:3), centers the crisp original
    without cropping, and fills the borders with a smooth Gaussian-blurred copy to 1920x1080.
    If already 16:9, resizes directly.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        img = Image.open(input_path).convert("RGB")
        orig_w, orig_h = img.size
        aspect = orig_w / orig_h
        target_aspect = width / height

        # If already ~16:9, direct high-quality resize
        if abs(aspect - target_aspect) < 0.03:
            img.resize((width, height), Image.Resampling.LANCZOS).save(output_path, "PNG")
            return output_path

        # 1. Fullscreen blurred and darkened backdrop (covers 1920x1080)
        scale = max(width / orig_w, height / orig_h)
        fill_w = int(round(orig_w * scale))
        fill_h = int(round(orig_h * scale))
        bg_fill = img.resize((fill_w, fill_h), Image.Resampling.LANCZOS)
        crop_x = (fill_w - width) // 2
        crop_y = (fill_h - height) // 2
        backdrop = bg_fill.crop((crop_x, crop_y, crop_x + width, crop_y + height))
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=40))
        backdrop = ImageEnhance.Brightness(backdrop).enhance(0.40)

        # Contrast vignette in lower half for karaoke text readability
        vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw_v = ImageDraw.Draw(vignette)
        for y in range(450, height):
            alpha = int(min(200, (y - 450) / (height - 450) * 200))
            draw_v.line([(0, y), (width, y)], fill=(8, 10, 16, alpha))
        backdrop = Image.alpha_composite(backdrop.convert("RGBA"), vignette).convert("RGB")

        # 2. Centered crisp foreground (fitted within 1920x1080)
        fit_scale = min(width / orig_w, height / orig_h) * 0.94
        fg_w = int(round(orig_w * fit_scale))
        fg_h = int(round(orig_h * fit_scale))
        fg_img = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

        # Rounded corners & shadow
        radius = 16
        mask = Image.new("L", (fg_w, fg_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (fg_w, fg_h)], radius=radius, fill=255)

        shadow_pad = 18
        shadow = Image.new("RGBA", (fg_w + shadow_pad * 2, fg_h + shadow_pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [(shadow_pad - 4, shadow_pad - 4), (fg_w + shadow_pad + 4, fg_h + shadow_pad + 4)],
            radius=radius + 4,
            fill=(0, 0, 0, 160)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=12))

        pos_x = (width - fg_w) // 2
        pos_y = (height - fg_h) // 2

        backdrop_rgba = backdrop.convert("RGBA")
        backdrop_rgba.paste(shadow, (pos_x - shadow_pad, pos_y - shadow_pad), shadow)
        backdrop_rgba.paste(fg_img, (pos_x, pos_y), mask)

        # Subtle fine border
        border = Image.new("RGBA", (fg_w, fg_h), (0, 0, 0, 0))
        ImageDraw.Draw(border).rounded_rectangle([(0, 0), (fg_w - 1, fg_h - 1)], radius=radius, outline=(255, 255, 255, 75), width=2)
        backdrop_rgba.paste(border, (pos_x, pos_y), border)

        final_rgb = backdrop_rgba.convert("RGB")
        final_rgb.save(output_path, "PNG")
        return output_path
    except Exception as e:
        print(f"[Karaoke] Warning: Failed to prepare non-16:9 background ({e}), using default.")
        return create_default_background(output_path, width, height)


def create_cover_background(
    cover_path: Path,
    output_path: Path,
    width: int = 1920,
    height: int = 1080
) -> Path:
    """
    Creates a Full HD 1920x1080 Apple Music / Spotify style backdrop:
    1. Fullscreen blurred and darkened cover backdrop with bottom vignette for crisp lyrics.
    2. Crisp UnsharpMask-enhanced rounded-corner album cover card floating in the upper center.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cover_path.exists():
        return create_default_background(output_path, width, height)

    try:
        cover = Image.open(cover_path).convert("RGB")

        # 1. Blurred and darkened full-screen 1920x1080 backdrop
        backdrop = cover.resize((width, height), Image.Resampling.LANCZOS)
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=48))
        backdrop = ImageEnhance.Color(backdrop).enhance(1.25)
        backdrop = ImageEnhance.Brightness(backdrop).enhance(0.28)

        # Dark vignette in lower half for maximum subtitle contrast
        vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw_v = ImageDraw.Draw(vignette)
        for y in range(400, height):
            alpha = int(min(220, (y - 400) / (height - 400) * 220))
            draw_v.line([(0, y), (width, y)], fill=(10, 11, 16, alpha))

        backdrop = Image.alpha_composite(backdrop.convert("RGBA"), vignette).convert("RGB")

        # 2. Crisp album art card in upper center (Y: 60..390, X: 795..1125)
        card_size = 330
        card_rgb = cover.resize((card_size, card_size), Image.Resampling.LANCZOS)
        card_rgb = card_rgb.filter(ImageFilter.UnsharpMask(radius=1.6, percent=135, threshold=2))
        card = card_rgb.convert("RGBA")

        # Rounded corners mask
        mask = Image.new("L", (card_size, card_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (card_size, card_size)], radius=24, fill=255)

        # Soft drop shadow + subtle inner frame around the 330x330 cover card
        border = Image.new("RGBA", (card_size + 12, card_size + 12), (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(border)
        b_draw.rounded_rectangle([(2, 2), (card_size + 10, card_size + 10)], radius=26, outline=(255, 255, 255, 95), width=2)

        pos_x = (width - card_size) // 2
        pos_y = 60

        # Composite border and card
        backdrop.paste(border, (pos_x - 6, pos_y - 6), border)
        backdrop.paste(card, (pos_x, pos_y), mask)

        backdrop.save(output_path, "PNG")
        return output_path
    except Exception as e:
        print(f"[Karaoke] Warning: Failed to create cover background: {e}, using default.")
        return create_default_background(output_path, width, height)


def _build_emoji_filter_graph(
    ass_escaped: str,
    fps: int,
    first_extra_input: int,
    lyric_concat: Optional[Path],
    particles: List[Dict[str, Any]],
    sprites: Dict[Tuple[str, int], Path],
    background_stream: str = "0:v:0",
) -> Tuple[List[str], str]:
    """
    Returns (extra_input_args, filter_complex) for:
    background -> flying emoji particles -> ASS subtitles -> lyric emoji overlay.
    Output label is [outv].
    """
    extra_inputs: List[str] = []
    graph: List[str] = [
        f"[{background_stream}]scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop=1920:1080,fps={fps},format=yuv420p[bg0]"
    ]
    cur = "bg0"
    next_idx = first_extra_input

    lyric_idx = None
    if lyric_concat is not None:
        extra_inputs += ["-f", "concat", "-safe", "0", "-i", str(lyric_concat)]
        lyric_idx = next_idx
        next_idx += 1

    # Group particles by sprite so each PNG is loaded once and split
    groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for p in particles:
        key = (p["emoji"], p["size"])
        if key in sprites:
            groups.setdefault(key, []).append(p)

    n_ov = 0
    for key, plist in groups.items():
        extra_inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(sprites[key])]
        idx = next_idx
        next_idx += 1
        labels = [f"s{idx}_{j}" for j in range(len(plist))]
        if len(plist) == 1:
            graph.append(f"[{idx}:v]format=rgba[{labels[0]}]")
        else:
            graph.append(f"[{idx}:v]format=rgba,split={len(plist)}" + "".join(f"[{l}]" for l in labels))
        for lab, p in zip(labels, plist):
            s, e = p["start"], p["end"]
            d = max(0.3, e - s)
            fade_out_st = max(s, e - 0.7)
            graph.append(
                f"[{lab}]fade=t=in:st={s:.3f}:d=0.35:alpha=1,"
                f"fade=t=out:st={fade_out_st:.3f}:d=0.7:alpha=1[{lab}f]"
            )
            u = f"((t-{s:.3f})/{d:.3f})"
            x_expr = f"{p['x1']}+({p['x2'] - p['x1']})*{u}+{p['wobble']}*sin(6.2832*1.4*{u}+{p['phase']})"
            y_expr = f"{p['y1']}+({p['y2'] - p['y1']})*{u}"
            out = f"ov{n_ov}"
            graph.append(
                f"[{cur}][{lab}f]overlay=x='{x_expr}':y='{y_expr}':"
                f"enable='between(t,{s:.3f},{e:.3f})':eof_action=pass[{out}]"
            )
            cur = out
            n_ov += 1

    graph.append(f"[{cur}]subtitles='{ass_escaped}'[subd]")
    cur = "subd"

    if lyric_idx is not None:
        graph.append(f"[{lyric_idx}:v]fps={fps},format=rgba[lyr]")
        graph.append(f"[{cur}][lyr]overlay=0:0:eof_action=pass[lyrv]")
        cur = "lyrv"

    graph.append(f"[{cur}]format=yuv420p[outv]")
    return extra_inputs, ";".join(graph)


BITRATE_PRESETS = {
    "light": {
        "b_v": "2200k",
        "maxrate": "3500k",
        "bufsize": "5000k",
        "crf": "24",
        "preset": "fast",
        "label": "Light Web (2.2 Mbps)",
    },
    "balanced": {
        "b_v": "4200k",
        "maxrate": "6500k",
        "bufsize": "8000k",
        "crf": "20",
        "preset": "medium",
        "label": "Balanced 1080p (4.2 Mbps)",
    },
    "hq": {
        "b_v": "8500k",
        "maxrate": "12000k",
        "bufsize": "16000k",
        "crf": "17",
        "preset": "slow",
        "label": "Studio HQ (8.5 Mbps)",
    },
}


def render_karaoke_video(
    instrumental_audio: Path,
    ass_subtitles: Path,
    output_video: Path,
    background: Optional[Path] = None,
    cover_image: Optional[Path] = None,
    use_cover_bg: bool = False,
    use_hardware_accel: bool = True,
    fps: int = 30,
    video_quality: str = "balanced",
    lyric_emoji_concat: Optional[Path] = None,
    emoji_particles: Optional[List[Dict[str, Any]]] = None,
    emoji_sprites: Optional[Dict[Tuple[str, int], Path]] = None,
    progress_callback=None,
) -> Path:
    """
    Renders the final Full HD 1080p (1920x1080) karaoke MP4 video by combining
    instrumental audio, background image/video or album cover backdrop, styled ASS subtitles,
    custom video bitrate (light, balanced, hq), and native Apple Color Emoji layers.
    """
    ffmpeg_bin = find_ffmpeg()
    output_video.parent.mkdir(parents=True, exist_ok=True)
    duration = audio_duration(probe_media(instrumental_audio.resolve(), ffmpeg_bin))
    if fps <= 0:
        raise ValueError("FPS должен быть положительным.")

    # Escape path for FFmpeg subtitles filter
    ass_escaped = str(ass_subtitles.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    # Select a moving stream explicitly, excluding attached album artwork.
    background_stream = "0:v:0"
    if background is not None and not Path(background).exists():
        raise FileNotFoundError(f"Не найден фон: {background}")
    # Determine background
    if background is not None and Path(background).exists():
        raw_bg = Path(background).resolve()
        moving_streams = video_streams(probe_media(raw_bg, ffmpeg_bin))
        is_video_bg = bool(moving_streams)
        if is_video_bg:
            background_stream = f"0:{moving_streams[0]['index']}"
            bg_file = raw_bg
        else:
            cached_bg = output_video.parent / "work" / f"{output_video.stem}_custom_bg_1080p.png"
            bg_file = prepare_background_image(raw_bg, cached_bg, width=1920, height=1080)
    elif use_cover_bg and cover_image is not None and Path(cover_image).exists():
        cover_bg = output_video.parent / "work" / f"{output_video.stem}_cover_bg.png"
        bg_file = create_cover_background(Path(cover_image), cover_bg, width=1920, height=1080)
        is_video_bg = False
    else:
        default_bg = output_video.parent / "default_bg.png"
        bg_file = create_default_background(default_bg, width=1920, height=1080)
        is_video_bg = False

    cmd = [ffmpeg_bin, "-y", "-nostdin", "-hide_banner", "-loglevel", "warning",
           "-nostats", "-stats_period", "0.5", "-progress", "pipe:1"]

    if is_video_bg:
        cmd.extend(["-stream_loop", "-1", "-i", str(bg_file)])
    else:
        cmd.extend(["-loop", "1", "-framerate", str(fps), "-i", str(bg_file)])

    # Input 1: instrumental audio
    cmd.extend(["-i", str(instrumental_audio.resolve())])

    particles = emoji_particles or []
    use_emoji_graph = bool(lyric_emoji_concat) or bool(particles and emoji_sprites)

    if use_emoji_graph:
        extra_inputs, graph = _build_emoji_filter_graph(
            ass_escaped, fps, 2, lyric_emoji_concat, particles, emoji_sprites or {}, background_stream
        )
        cmd.extend(extra_inputs)
        cmd.extend(["-filter_complex", graph, "-map", "[outv]", "-map", "1:a:0"])
    else:
        # Video filter: high-quality Lanczos scale & crop to exact 1920x1080 Full HD, then burn in ASS subtitles
        vf_filter = (
            f"scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop=1920:1080,"
            f"fps={fps},"
            f"subtitles='{ass_escaped}'"
        )
        cmd.extend(["-vf", vf_filter, "-map", background_stream, "-map", "1:a:0"])

    q_cfg = BITRATE_PRESETS.get(video_quality, BITRATE_PRESETS["balanced"])

    if use_hardware_accel:
        cmd.extend([
            "-c:v", "h264_videotoolbox",
            "-profile:v", "high",
            "-b:v", q_cfg["b_v"],
            "-maxrate", q_cfg["maxrate"],
            "-bufsize", q_cfg["bufsize"],
            "-allow_sw", "1",
        ])
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-preset", q_cfg["preset"],
            "-crf", q_cfg["crf"],
            "-profile:v", "high",
            "-maxrate", q_cfg["maxrate"],
            "-bufsize", q_cfg["bufsize"],
        ])

    # Independent duration, frame-count and disk budgets prevent runaway output.
    max_bitrate = int(q_cfg["maxrate"].rstrip("k")) * 1000 + 256_000
    size_limit = math.ceil(duration * max_bitrate / 8 * 1.5) + 8 * 1024 * 1024
    cmd.extend([
        "-frames:v", str(math.ceil(duration * fps)),
        "-fs", str(size_limit),
        "-t", f"{duration:.9f}",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", "256k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-shortest",
    ])

    check_cancelled()
    codec_label = f"h264_videotoolbox 1080p {q_cfg['label']}" if use_hardware_accel else f"libx264 1080p CRF{q_cfg['crf']}"
    emoji_label = f", emoji: lyrics={'yes' if lyric_emoji_concat else 'no'}, particles={len(particles)}" if use_emoji_graph else ""
    print(f"[Karaoke] Rendering Full HD 1920x1080 video with FFmpeg ({codec_label}{emoji_label})...")
    # A failed rebuild must never replace the last successful video.
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{output_video.stem}-", suffix=".mp4", dir=output_video.parent
    )
    os.close(temp_fd)
    temporary_video = Path(temp_name)
    cmd.append(str(temporary_video.resolve()))
    print(f"[Karaoke] Audio: input 1, duration={duration:.3f}s; output limited to audio duration.")
    tracker = RenderProgress(duration, temporary_video, size_limit, progress_callback)
    try:
        tracker.tick(force=True)
        run_cancellable_command(cmd, prefix="FFmpeg", on_stdout_line=tracker.line, on_tick=tracker.tick)
        if progress_callback:
            progress_callback("Проверка длительности и сохранение готового MP4…", 0.99)
        check_cancelled()
        result = probe_media(temporary_video, ffmpeg_bin)
        actual_duration = float(result.get("format", {}).get("duration") or 0)
        if not video_streams(result) or abs(actual_duration - duration) > max(0.15, 2 / fps):
            raise RuntimeError("Рендер создал видео с неправильной длительностью.")
        audio_duration(result)
        check_cancelled()
        temporary_video.replace(output_video)
    except GenerationCancelledError:
        raise
    except subprocess.CalledProcessError as e:
        temporary_video.unlink(missing_ok=True)
        check_cancelled()
        stderr = e.stderr.decode('utf-8', errors='ignore') if isinstance(e.stderr, bytes) else str(e.stderr or "")
        if use_hardware_accel:
            print("[Karaoke] Warning: Hardware encoding failed, falling back to libx264...")
            if progress_callback:
                progress_callback("Аппаратный кодек недоступен. Повтор рендера на CPU…", 0.0)
            print(stderr[-1500:])
            return render_karaoke_video(
                instrumental_audio, ass_subtitles, output_video,
                background=background, cover_image=cover_image,
                use_cover_bg=use_cover_bg, use_hardware_accel=False, fps=fps,
                video_quality=video_quality,
                lyric_emoji_concat=lyric_emoji_concat,
                emoji_particles=emoji_particles,
                emoji_sprites=emoji_sprites,
                progress_callback=progress_callback,
            )
        else:
            raise RuntimeError(f"FFmpeg rendering failed:\n{stderr[-3000:]}")

    finally:
        temporary_video.unlink(missing_ok=True)

    print(f"[Karaoke] Full HD 1080p video rendered successfully: {output_video} "
          f"({output_video.stat().st_size / 1_000_000:.1f} MB, {duration:.3f}s)")
    if progress_callback:
        progress_callback(f"Готово: {duration:.1f} с, {output_video.stat().st_size / 1_000_000:.1f} МБ", 1.0)
    return output_video
