import random
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import soundfile as sf
from karaoke.aligner import clean_word_token, split_into_karaoke_lines, validate_karaoke_lines
from karaoke.emoji_layer import split_text_emoji, ass_placeholder, layout_line_emoji

# All teleprompter styles use opaque text/outline and a 50% shadow (BackColour &H80......)
_RESTORE_ALPHA = "\\1a&H00&\\2a&H00&\\3a&H00&\\4a&H80&"


def _ass_text_with_emoji(text: str, font_size: float) -> str:
    """Replaces Apple emoji with invisible placeholders of the same width (libass can't draw color emoji)."""
    segments = split_text_emoji(text)
    if not any(kind == "e" for kind, _ in segments):
        return text
    return "".join(
        seg if kind == "t" else ass_placeholder(font_size, _RESTORE_ALPHA)
        for kind, seg in segments
    )


def format_ass_time(seconds: float) -> str:
    """Formats seconds into ASS timestamp: H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))
    hours = total_cs // 360000
    rem = total_cs % 360000
    minutes = rem // 6000
    rem = rem % 6000
    secs = rem // 100
    centis = rem % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _plain_text_and_scale(line_words: List[Dict[str, Any]]) -> Tuple[str, int]:
    words = [clean_word_token(w.get("text", "")) for w in line_words]
    words = [w for w in words if w]
    text = " ".join(words)
    scale_pct = 100
    if len(text) > 40:
        scale_pct = max(72, int(100 * (39.0 / len(text))))
    return text, scale_pct


def get_plain_line_text(line_words: List[Dict[str, Any]], font_size: float = 48) -> str:
    """
    Returns clean text for preview/past lines without karaoke tags.
    Applies font scale reduction if the text is longer than 40 chars.
    Emoji are replaced by invisible placeholders (drawn later by the Apple emoji layer).
    """
    text, scale_pct = _plain_text_and_scale(line_words)
    ass_text = _ass_text_with_emoji(text, font_size)
    if scale_pct != 100:
        return f"{{\\fscx{scale_pct}\\fscy{scale_pct}}}{ass_text}"
    return ass_text


def _karaoke_scale(line_words: List[Dict[str, Any]]) -> int:
    total_chars = sum(len(clean_word_token(w.get("text", ""))) + 1 for w in line_words)
    if total_chars > 40:
        return max(72, int(100 * (39.0 / total_chars)))
    return 100


def build_karaoke_line_tags(
    line_words: List[Dict[str, Any]],
    display_start: float,
    font_size: float = 54,
) -> str:
    """
    Builds the ASS {\k} and {\kf} tagged string for the active karaoke line.
    Automatically scales down font width if the line is very long (> 40 chars) so it never wraps.
    """
    line_start = line_words[0]["start"]
    lead_in_gap = max(0.0, line_start - display_start)

    scale_pct = _karaoke_scale(line_words)
    scale_prefix = ""
    if scale_pct != 100:
        scale_prefix = f"{{\\fscx{scale_pct}\\fscy{scale_pct}}}"

    k_text = scale_prefix
    if lead_in_gap > 0.02:
        lead_in_cs = int(round(lead_in_gap * 100))
        k_text += f"{{\\k{lead_in_cs}}}"

    prev_word_end = line_start
    for word_info in line_words:
        word_str = clean_word_token(word_info.get("text", ""))
        if not word_str:
            continue
        w_start = max(prev_word_end, float(word_info.get("start", prev_word_end)))
        w_end = max(w_start + 0.08, float(word_info.get("end", w_start + 0.25)))

        inter_word_gap = max(0.0, w_start - prev_word_end)
        if inter_word_gap > 0.02:
            gap_cs = int(round(inter_word_gap * 100))
            k_text += f"{{\\k{gap_cs}}}"

        duration_cs = max(8, int(round((w_end - w_start) * 100)))
        k_text += f"{{\\kf{duration_cs}}}{_ass_text_with_emoji(word_str, font_size)} "
        prev_word_end = w_end

    return k_text.strip()


def _generate_sparkles_events(
    start_t: float,
    end_t: float,
    intensity: float = 0.8,
    is_climax: bool = False,
    edge_color_mode: str = "cyberpunk",
    cover_edge_colors: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Generates glowing neon sparkle and star particles (✦, ✧, ★, ●, ✶)
    pulsing with radiant bloom and fading gracefully, matching the selected frame palette.
    """
    if end_t <= start_t:
        return []

    events = []
    dur = end_t - start_t
    multiplier = 2.4 if is_climax else 1.0
    num_particles = max(3, int(dur * 3.6 * intensity * multiplier))

    rng = random.Random(int(start_t * 100) + 42)
    symbols = ["✦", "✧", "★", "●", "✶", "✦"]

    # Neon colors from active palette
    neon_colors = []
    if edge_color_mode == "cover_colors" and cover_edge_colors:
        neon_colors = [c for c in cover_edge_colors.values() if c]
    if not neon_colors:
        neon_colors = NEON_PALETTES.get(edge_color_mode, NEON_PALETTES["cyberpunk"])

    for _ in range(num_particles):
        p_start = start_t + rng.uniform(0.0, max(0.1, dur - 1.2))
        p_dur = rng.uniform(1.6, 2.8)
        p_end = min(end_t, p_start + p_dur)
        if p_end <= p_start:
            continue

        sym = rng.choice(symbols)
        col = rng.choice(neon_colors)
        sz = rng.randint(26, 50 if is_climax else 42)

        zone = rng.random()
        if zone < 0.42:
            x1 = rng.randint(40, 340)
            x2 = x1 + rng.randint(-35, 35)
            y1 = rng.randint(180, 950)
            y2 = y1 - rng.randint(90, 220)
        elif zone < 0.84:
            x1 = rng.randint(1580, 1880)
            x2 = x1 + rng.randint(-35, 35)
            y1 = rng.randint(180, 950)
            y2 = y1 - rng.randint(90, 220)
        else:
            x1 = rng.randint(380, 1540)
            x2 = x1 + rng.randint(-25, 25)
            y1 = rng.randint(50, 240)
            y2 = y1 - rng.randint(40, 110)

        dur_ms = int(p_dur * 1000)
        mid_ms = int(dur_ms * 0.45)
        fade_in = int(dur_ms * 0.22)
        fade_out = int(dur_ms * 0.50)
        blur_val = rng.choice([4, 5, 6, 7])
        bord_sz = 2.8 if sz < 36 else 3.4

        # Radiant neon bloom: White-hot core, vivid neon aura, breathing twinkle
        tag = (
            f"{{\\an5\\fs{sz}\\c&H00FFFFFF&\\3c{col}\\bord{bord_sz}\\shad0\\blur{blur_val}"
            f"\\fad({fade_in},{fade_out})"
            f"\\fscx75\\fscy75"
            f"\\t(0,{mid_ms},\\fscx125\\fscy125\\blur{blur_val + 2})"
            f"\\t({mid_ms},{dur_ms},\\fscx60\\fscy60\\blur2)"
            f"\\move({x1},{y1},{x2},{y2})}}{sym}"
        )
        entry = f"Dialogue: 0,{format_ass_time(p_start)},{format_ass_time(p_end)},FX_Sparkle,,0,0,0,,{tag}"
        events.append(entry)

    return events


def _extract_audio_pulse_times(audio_path: Optional[Path]) -> List[float]:
    """Finds peak beat onsets in the audio for syncing edge pulses to the rhythm."""
    if not audio_path or not Path(audio_path).exists():
        return []
    try:
        data, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
        mono = np.max(np.abs(data), axis=1)
        frame_sz = int(sr * 0.08)  # 80ms frames
        n_frames = len(mono) // frame_sz
        if n_frames < 20:
            return []
        rms = np.array([np.sqrt(np.mean(mono[i * frame_sz:(i + 1) * frame_sz] ** 2)) for i in range(n_frames)])
        thresh = float(np.percentile(rms, 82))
        pulse_times = []
        for i in range(1, n_frames - 1):
            if rms[i] > thresh and rms[i] > rms[i - 1] and rms[i] >= rms[i + 1]:
                t = round(i * 0.08, 2)
                if not pulse_times or (t - pulse_times[-1] >= 0.32):
                    pulse_times.append(t)
        return pulse_times
    except Exception:
        return []


NEON_PALETTES: Dict[str, List[str]] = {
    "cyberpunk": [
        "&H00FFF500&",  # Electric Cyan (#00F5FF)
        "&H00FF00F0&",  # Hot Magenta Pink (#F000FF)
        "&H00FF009D&",  # Deep Violet (#9D00FF)
        "&H00CCFF00&",  # Bright Turquoise
    ],
    "pink": [
        "&H009314FF&",  # Deep Neon Pink (#FF1493)
        "&H00B469FF&",  # Hot Pink (#FF69B4)
        "&H00D400FF&",  # Violet Magenta
        "&H00C020FF&",  # Electric Pink
    ],
    "blue": [
        "&H00FFF000&",  # Electric Cyan (#00F0FF)
        "&H00FFB000&",  # Sky Blue (#00B0FF)
        "&H00FFAA33&",  # Neon Blue
        "&H00FFFF00&",  # Pure Aqua (#00FFFF)
    ],
    "purple": [
        "&H00D400AA&",  # Ultra Violet
        "&H00FF0099&",  # Purple Neon
        "&H00990066&",  # Deep Indigo
        "&H00FF55DD&",  # Light Lavender Neon
    ],
    "fire": [
        "&H000055FF&",  # Fire Orange (#FF5500)
        "&H000022FF&",  # Crimson Red (#FF2200)
        "&H0000D7FF&",  # Gold Yellow (#FFD700)
        "&H000088FF&",  # Amber (#FF8800)
    ],
    "neon_rainbow": [
        "&H00FFFF00&",  # Cyan
        "&H00FF00FF&",  # Electric Magenta
        "&H0000D7FF&",  # Neon Gold
        "&H00FF3399&",  # Laser Violet
        "&H0099FF00&",  # Aqua Mint
        "&H008000FF&",  # Hot Rose
    ],
    "police": [
        "&H000000FF&",  # Pure Neon Red (#FF0000)
        "&H00FF3300&",  # Electric Police Blue (#0033FF)
        "&H000022EE&",  # Crimson Red
        "&H00FFAA00&",  # Neon Cyan-Blue
    ],
    "green_neon": [
        "&H0014FF39&",  # Vivid Acid / Lime Green (#39FF14)
        "&H0000FF7F&",  # Spring Green (#7FFF00)
        "&H0050C878&",  # Emerald Green (#78C850)
        "&H00A6FF00&",  # Electric Mint (#00FFA6)
    ],
}

HIGHLIGHT_COLORS: Dict[str, str] = {
    "gold_neon": "&H0000D7FF",       # High-contrast Gold (#FFD700) - default
    "electric_cyan": "&H00FFF000",   # Electric Cyan (#00F0FF)
    "neon_magenta": "&H009314FF",    # Neon Pink / Magenta (#FF1493)
    "acid_lime": "&H0014FF39",       # Acid Green (#39FF14)
    "green_neon": "&H0014FF39",      # Vivid Green Neon (#39FF14)
    "emerald": "&H0050C878",         # Deep Emerald Glow (#78C850)
    "fire_orange": "&H00006AFF",     # Fire Orange (#FF6A00)
}

FONT_SIZE_MODES: Dict[str, Dict[int, Dict[str, int]]] = {
    "standard": {
        4: {"active": 54, "next": 48, "prev": 44, "next2": 42, "mv_active": 365, "mv_next": 265, "mv_prev": 470, "mv_next2": 165},
        3: {"active": 56, "next": 50, "prev": 46, "mv_active": 310, "mv_next": 185, "mv_prev": 430},
    },
    "large": {  # Default: +20% larger, high contrast
        4: {"active": 64, "next": 54, "prev": 48, "next2": 44, "mv_active": 375, "mv_next": 265, "mv_prev": 490, "mv_next2": 160},
        3: {"active": 68, "next": 56, "prev": 50, "mv_active": 320, "mv_next": 185, "mv_prev": 450},
    },
    "huge": {
        4: {"active": 74, "next": 60, "prev": 52, "next2": 48, "mv_active": 385, "mv_next": 265, "mv_prev": 510, "mv_next2": 155},
        3: {"active": 78, "next": 62, "prev": 54, "mv_active": 330, "mv_next": 185, "mv_prev": 470},
    },
}


def _generate_edge_pulse_events(
    start_t: float,
    end_t: float,
    pulse_times: List[float],
    intensity: float = 0.85,
    is_climax: bool = False,
    edge_color_mode: str = "neon_rainbow",
    cover_edge_colors: Optional[Dict[str, str]] = None,
    has_cover_card: bool = True,
) -> List[str]:
    """
    Renders full-perimeter glowing neon / Ambilight borders around all 4 edges of the
    1920x1080 frame (Top, Bottom, Left, Right) PLUS the 330x330 cover square contour
    using ASS vector drawing mode ({\\p1}) pulsing in sync with the musical beat.
    """
    if end_t <= start_t:
        return []

    # Filter pulses within interval
    active_pulses = [t for t in pulse_times if start_t <= t <= end_t]
    if not active_pulses:
        # Fallback periodic pulses every 0.55s
        step = 0.45 if is_climax else 0.65
        cur = start_t
        while cur < end_t:
            active_pulses.append(round(cur, 2))
            cur += step

    events: List[str] = []

    palette_key = edge_color_mode if edge_color_mode in NEON_PALETTES else "cyberpunk"
    neon_palette = NEON_PALETTES.get(palette_key, NEON_PALETTES["cyberpunk"])

    cov_colors = cover_edge_colors or {
        "top": "&H00FFFF00&",
        "bottom": "&H00FF00FF&",
        "left": "&H0000D7FF&",
        "right": "&H00FF55AA&",
    }

    # Scale border thickness and blur by intensity and climax
    scale_mult = (1.35 if is_climax else 1.0) * max(0.5, min(1.2, intensity))
    outer_bord = int(round(32 * scale_mult))
    outer_blur = int(round(26 * scale_mult))
    inner_bord = int(round(10 * scale_mult))
    inner_blur = int(round(7 * scale_mult))

    is_police = (edge_color_mode == "police")

    # Full 1920x1080 edge vector rectangles (split in halves for police strobe)
    if is_police:
        edges_geom = {
            "left": "m 0 0 l 6 0 l 6 1080 l 0 1080",
            "top_left": "m 0 0 l 960 0 l 960 6 l 0 6",
            "bottom_left": "m 0 1074 l 960 1074 l 960 1080 l 0 1080",
            "right": "m 1914 0 l 1920 0 l 1920 1080 l 1914 1080",
            "top_right": "m 960 0 l 1920 0 l 1920 6 l 960 6",
            "bottom_right": "m 960 1074 l 1920 1074 l 1920 1080 l 960 1080",
        }
    else:
        edges_geom = {
            "top": "m 0 0 l 1920 0 l 1920 6 l 0 6",
            "bottom": "m 0 1074 l 1920 1074 l 1920 1080 l 0 1080",
            "left": "m 0 0 l 6 0 l 6 1080 l 0 1080",
            "right": "m 1914 0 l 1920 0 l 1920 1080 l 1914 1080",
        }

    # Album cover card square contour in upper center: X=795..1125, Y=60..390 (330x330)
    cover_box_geom = (
        "m 793 58 l 1127 58 l 1127 62 l 793 62 "
        "m 793 388 l 1127 388 l 1127 392 l 793 392 "
        "m 793 58 l 797 58 l 797 392 l 793 392 "
        "m 1123 58 l 1127 58 l 1127 392 l 1123 392"
    )

    for idx, p_t in enumerate(active_pulses):
        p_dur = 0.44 if is_climax else 0.38
        p_end = min(end_t, p_t + p_dur)
        if p_end <= p_t:
            continue

        dur_ms = max(120, int(round((p_end - p_t) * 1000)))
        fade_in = min(75, dur_ms // 4)
        fade_out = max(120, int(dur_ms * 0.65))

        for side_idx, (side_name, geom) in enumerate(edges_geom.items()):
            if is_police:
                # Police strobe: Smooth transition between Red and Blue across phases
                phase_even = (idx % 2 == 0)
                is_red_side = "left" in side_name
                if phase_even:
                    c1 = "&H000000FF&" if is_red_side else "&H00FF3300&"
                    c2 = "&H00FF3300&" if is_red_side else "&H000000FF&"
                else:
                    c1 = "&H00FF3300&" if is_red_side else "&H000000FF&"
                    c2 = "&H000000FF&" if is_red_side else "&H00FF3300&"
            elif edge_color_mode == "cover_colors":
                c1 = cov_colors.get(side_name, "&H0000D7FF&")
                adj_side = ("right" if side_name == "top" else "bottom" if side_name == "right" else "left" if side_name == "bottom" else "top")
                c2 = cov_colors.get(adj_side, c1)
            else:
                c1 = neon_palette[(idx + side_idx) % len(neon_palette)]
                c2 = neon_palette[(idx + side_idx + 2) % len(neon_palette)]

            # 1) Outer neon aura around full 1920x1080 side
            aura_tag = (
                f"{{\\an7\\pos(0,0)\\p1\\1c{c1}\\3c{c1}\\1a&H60&\\3a&H35&"
                f"\\bord{outer_bord}\\blur{outer_blur}\\fad({fade_in},{fade_out})"
                f"\\t(0,{dur_ms},\\1c{c2}\\3c{c2})}}{geom}{{\\p0}}"
            )
            events.append(
                f"Dialogue: 0,{format_ass_time(p_t)},{format_ass_time(p_end)},FX_EdgePulse,,0,0,0,,{aura_tag}"
            )

            # 2) Bright inner neon core along the edge
            core_tag = (
                f"{{\\an7\\pos(0,0)\\p1\\1c&H00FFFFFF&\\3c{c1}\\1a&H20&\\3a&H10&"
                f"\\bord{inner_bord}\\blur{inner_blur}\\fad({fade_in},{fade_out})"
                f"\\t(0,{dur_ms},\\3c{c2})}}{geom}{{\\p0}}"
            )
            events.append(
                f"Dialogue: 0,{format_ass_time(p_t)},{format_ass_time(p_end)},FX_EdgePulse,,0,0,0,,{core_tag}"
            )

        # Also pulse the 330x330 cover art square border in sync with the frame perimeter
        if has_cover_card:
            if edge_color_mode == "cover_colors":
                cc1 = cov_colors.get("top", "&H00FFFF00&")
                cc2 = cov_colors.get("bottom", "&H00FF00FF&")
            else:
                cc1 = neon_palette[idx % len(neon_palette)]
                cc2 = neon_palette[(idx + 3) % len(neon_palette)]

            cov_bord = max(10, outer_bord // 2)
            cov_blur = max(8, outer_blur // 2)
            card_glow_tag = (
                f"{{\\an7\\pos(0,0)\\p1\\1c{cc1}\\3c{cc1}\\1a&H50&\\3a&H25&"
                f"\\bord{cov_bord}\\blur{cov_blur}\\fad({fade_in},{fade_out})"
                f"\\t(0,{dur_ms},\\1c{cc2}\\3c{cc2})}}{cover_box_geom}{{\\p0}}"
            )
            events.append(
                f"Dialogue: 0,{format_ass_time(p_t)},{format_ass_time(p_end)},FX_EdgePulse,,0,0,0,,{card_glow_tag}"
            )

    return events


def _perimeter_point(s: float) -> Tuple[int, int]:
    """Maps perimeter distance s (0..6000) clockwise around 1920x1080 frame."""
    s = s % 6000.0
    if s < 1920.0:
        return int(round(s)), 6
    elif s < 3000.0:
        return 1914, int(round(s - 1920.0))
    elif s < 4920.0:
        return int(round(1920.0 - (s - 3000.0))), 1074
    else:
        return 6, int(round(1080.0 - (s - 4920.0)))


def _generate_police_migrating_dots_events(
    start_t: float,
    end_t: float,
    intensity: float = 0.85,
) -> List[str]:
    """
    Renders moving red & blue LED beacon dots that smoothly travel along
    the 1920x1080 frame perimeter (6000px total length) using ASS \\move.
    """
    if end_t <= start_t:
        return []

    events = []
    speed = 950.0  # px per second (~6.3s per complete perimeter lap)
    num_dots = int(round(16 * intensity))
    num_dots = max(8, min(24, num_dots))
    step_dur = 0.4  # sub-slice duration in seconds

    cur_t = start_t
    while cur_t < end_t:
        slice_end = min(end_t, cur_t + step_dur)
        dt = slice_end - cur_t
        if dt < 0.05:
            break

        for k in range(num_dots):
            base_s = k * (6000.0 / num_dots)
            s1 = (base_s + (cur_t - start_t) * speed) % 6000.0
            s2 = (s1 + dt * speed) % 6000.0

            x1, y1 = _perimeter_point(s1)
            x2, y2 = _perimeter_point(s2)

            if k % 4 == 0:
                col = "&H00FFFFFF&"  # White strobe accent
                aura_col = "&H000000FF&" if (k % 2 == 0) else "&H00FF3300&"
            elif k % 2 == 0:
                col = "&H000000FF&"  # Police Red
                aura_col = "&H000022FF&"
            else:
                col = "&H00FF3300&"  # Police Blue
                aura_col = "&H00FFAA00&"

            # 1) Soft outer aura
            tag_aura = (
                f"{{\\an5\\move({x1},{y1},{x2},{y2})\\p1\\1c{aura_col}\\3c{aura_col}"
                f"\\1a&H35&\\3a&H15&\\bord4\\blur8}}m -8 -8 l 8 -8 l 8 8 l -8 8{{\\p0}}"
            )
            events.append(
                f"Dialogue: 0,{format_ass_time(cur_t)},{format_ass_time(slice_end)},FX_BeaconDot,,0,0,0,,{tag_aura}"
            )

            # 2) Sharp glowing core
            tag_core = (
                f"{{\\an5\\move({x1},{y1},{x2},{y2})\\p1\\1c{col}\\3c&H00FFFFFF&"
                f"\\1a&H00&\\3a&H20&\\bord2\\blur3}}m -3 -3 l 3 -3 l 3 3 l -3 3{{\\p0}}"
            )
            events.append(
                f"Dialogue: 0,{format_ass_time(cur_t)},{format_ass_time(slice_end)},FX_BeaconDot,,0,0,0,,{tag_core}"
            )

        cur_t = slice_end

    return events


SPARKLE_EFFECTS = ("sparkles", "sparkles_pulse", "climax", "police_strobe", "green_neon")
PULSE_EFFECTS = ("pulse", "sparkles_pulse", "climax", "emoji_pulse", "emoji_burst", "police_strobe", "green_neon")
EMOJI_EFFECTS = ("emoji_burst", "emoji_pulse")


def generate_ass_from_lines(
    lines: List[List[Dict[str, Any]]],
    output_path: Path,
    title: str = "Karaoke",
    num_lines: int = 4,
    visual_effects: str = "sparkles_pulse",
    fx_intervals: Optional[List[Dict[str, Any]]] = None,
    audio_for_pulse: Optional[Path] = None,
    edge_color_mode: str = "cyberpunk",
    cover_edge_colors: Optional[Dict[str, str]] = None,
    has_cover_card: bool = True,
    emoji_events_out: Optional[List[Dict[str, Any]]] = None,
    font_size_mode: str = "large",
    highlight_color: str = "gold_neon",
    watermark_text: Optional[str] = None,
) -> Path:
    """
    Generates an Advanced SubStation Alpha (.ass) file with:
    1. Centered Rolling Teleprompter layout (4 or 3 lines, safe vertical margins).
    2. Optional visual effects: floating sparkles/bokeh, full-perimeter 1920x1080 beat pulses, and climax mode.
    3. Timeline-based FX intervals (e.g. sparkles & beat pulses on choruses/emotional moments).
    4. Customizable font sizes (standard, large, huge), high-contrast sweep color, and deep black outline.
    If `emoji_events_out` is a list, it is filled with on-screen positions of Apple emoji found in lyrics
    ({'start', 'end', 'emoji', 'x', 'y', 'size'}) for the native emoji overlay layer.
    """
    validate_karaoke_lines(lines)
    num_lines = 3 if num_lines == 3 else 4
    has_explicit_timeline_fx = fx_intervals is not None
    fx_intervals = list(fx_intervals) if fx_intervals is not None else []

    # Typography & contrast configuration
    cfg = FONT_SIZE_MODES.get(font_size_mode, FONT_SIZE_MODES["large"]).get(num_lines, FONT_SIZE_MODES["large"][4])
    f_active = cfg["active"]
    f_next = cfg["next"]
    f_prev = cfg["prev"]
    mv_active = cfg["mv_active"]
    mv_next = cfg["mv_next"]
    mv_prev = cfg["mv_prev"]

    sweep_color = HIGHLIGHT_COLORS.get(highlight_color, highlight_color if highlight_color.startswith("&H") else HIGHLIGHT_COLORS["gold_neon"])
    clean_sweep = sweep_color.rstrip("&")

    # High-contrast outline & drop-shadow: Outline 4.5, Shadow 2.8, pitch-black outline &H00000000
    style_active = (
        f"Style: KaraokeActive,Arial,{f_active},{clean_sweep},&H00FFFFFF,&H00000000,&H90000000,"
        f"-1,0,0,0,100,100,0.5,0,1,4.5,2.8,2,70,70,{mv_active},1"
    )
    style_prev = (
        f"Style: KaraokePrev,Arial,{f_prev},&H00999999,&H00999999,&H00000000,&H90000000,"
        f"0,0,0,0,100,100,0.5,0,1,3.2,1.8,2,70,70,{mv_prev},1"
    )
    style_next = (
        f"Style: KaraokeNext,Arial,{f_next},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,"
        f"0,0,0,0,100,100,0.5,0,1,3.8,2.2,2,70,70,{mv_next},1"
    )

    if num_lines == 4:
        f_next2 = cfg["next2"]
        mv_next2 = cfg["mv_next2"]
        style_next2 = (
            f"Style: KaraokeNextNext,Arial,{f_next2},&H00CCCCCC,&H00CCCCCC,&H00000000,&H90000000,"
            f"0,0,0,0,100,100,0.5,0,1,3.2,1.8,2,70,70,{mv_next2},1"
        )
        countdown_margin = mv_prev + 105
        styles_list = [style_prev, style_active, style_next, style_next2]
        style_meta = {
            "KaraokePrev": (f_prev, False, mv_prev),
            "KaraokeActive": (f_active, True, mv_active),
            "KaraokeNext": (f_next, False, mv_next),
            "KaraokeNextNext": (f_next2, False, mv_next2),
        }
    else:
        countdown_margin = mv_prev + 100
        styles_list = [style_prev, style_active, style_next]
        style_meta = {
            "KaraokePrev": (f_prev, False, mv_prev),
            "KaraokeActive": (f_active, True, mv_active),
            "KaraokeNext": (f_next, False, mv_next),
        }

    style_countdown = (
        f"Style: Countdown,Arial,{f_next},{clean_sweep},&H00666666,&H00000000,&H90000000,"
        f"-1,0,0,0,100,100,2.0,0,1,3.6,1.8,2,70,70,{countdown_margin},1"
    )
    styles_list.append(style_countdown)

    # Styles for Visual Effects (Layer 0)
    styles_list.append(
        f"Style: FX_Sparkle,Arial,36,{clean_sweep},&H00FFFFFF,&H00141414,&H80000000,0,0,0,0,100,100,0,0,1,1.5,0.8,5,10,10,10,1"
    )
    styles_list.append(
        f"Style: FX_EdgePulse,Arial,20,{clean_sweep},&H00FFFFFF,{clean_sweep},&H00000000,0,0,0,0,100,100,0,0,1,10.0,0.0,7,0,0,0,1"
    )
    styles_list.append(
        "Style: DJWatermark,Arial,28,&H30FFFFFF,&H30FFFFFF,&H50000000,&H80000000,-1,0,0,0,100,100,0.8,0,1,2.6,1.6,9,42,42,36,1"
    )

    styles_block = "\n".join(styles_list)

    ass_header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles_block}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_entries: List[str] = []

    # 1. Generate Visual Effects (Layer 0)
    total_song_end = lines[-1][-1]["end"] + 2.0 if lines else 30.0
    needs_pulse = visual_effects in PULSE_EFFECTS or any(x.get("effect", "") in PULSE_EFFECTS for x in fx_intervals)
    pulse_times = _extract_audio_pulse_times(audio_for_pulse) if needs_pulse else []

    # A) Timeline-based FX intervals (respected even when user explicitly clears timeline to [])
    if visual_effects == "none":
        pass
    elif fx_intervals:
        for itv in fx_intervals:
            s_t = max(0.0, float(itv.get("start", 0.0)))
            e_t = min(total_song_end, float(itv.get("end", total_song_end)))
            if e_t <= s_t:
                continue
            fx_mode = itv.get("effect", "sparkles_pulse")
            intensity = max(0.1, min(1.0, float(itv.get("intensity", 0.85))))
            is_climax = (fx_mode == "climax")

            itv_edge_mode = "police" if fx_mode == "police_strobe" else ("green_neon" if fx_mode == "green_neon" else edge_color_mode)
            if fx_mode in SPARKLE_EFFECTS:
                dialogue_entries.extend(
                    _generate_sparkles_events(
                        s_t, e_t,
                        intensity=intensity,
                        is_climax=is_climax,
                        edge_color_mode=itv_edge_mode,
                        cover_edge_colors=cover_edge_colors,
                    )
                )
            if fx_mode in PULSE_EFFECTS:
                dialogue_entries.extend(
                    _generate_edge_pulse_events(
                        s_t, e_t,
                        pulse_times=pulse_times,
                        intensity=intensity,
                        is_climax=is_climax,
                        edge_color_mode=itv_edge_mode,
                        cover_edge_colors=cover_edge_colors,
                        has_cover_card=has_cover_card,
                    )
                )
            if fx_mode == "police_strobe" or itv_edge_mode == "police":
                dialogue_entries.extend(
                    _generate_police_migrating_dots_events(
                        s_t, e_t,
                        intensity=intensity,
                    )
                )

    # B) Global fallback effects ONLY when fx_intervals was not provided (None)
    elif not has_explicit_timeline_fx and visual_effects not in ("none", "timeline_only"):
        is_climax = (visual_effects == "climax")
        eff_edge_mode = "police" if visual_effects == "police_strobe" else ("green_neon" if visual_effects == "green_neon" else edge_color_mode)
        if visual_effects in SPARKLE_EFFECTS:
            dialogue_entries.extend(
                _generate_sparkles_events(
                    0.0, total_song_end,
                    intensity=0.80,
                    is_climax=is_climax,
                    edge_color_mode=eff_edge_mode,
                    cover_edge_colors=cover_edge_colors,
                )
            )
        if visual_effects in PULSE_EFFECTS:
            dialogue_entries.extend(
                _generate_edge_pulse_events(
                    0.0, total_song_end,
                    pulse_times=pulse_times,
                    intensity=0.85,
                    is_climax=is_climax,
                    edge_color_mode=eff_edge_mode,
                    cover_edge_colors=cover_edge_colors,
                    has_cover_card=has_cover_card,
                )
            )
        if visual_effects == "police_strobe" or eff_edge_mode == "police":
            dialogue_entries.extend(
                _generate_police_migrating_dots_events(
                    0.0, total_song_end,
                    intensity=0.85,
                )
            )

    # 2. Group lyrics lines into stanzas
    stanzas: List[List[List[Dict[str, Any]]]] = []
    current_stanza: List[List[Dict[str, Any]]] = []
    for line in lines:
        if not line:
            continue
        if current_stanza:
            gap = line[0]["start"] - current_stanza[-1][-1]["end"]
            if gap > 4.0:
                stanzas.append(current_stanza)
                current_stanza = []
        current_stanza.append(line)
    if current_stanza:
        stanzas.append(current_stanza)

    prev_stanza_end = 0.0

    for s_num, stanza in enumerate(stanzas):
        if not stanza:
            continue
        n_lines = len(stanza)
        stanza_first_start = stanza[0][0]["start"]
        stanza_last_end = stanza[-1][-1]["end"]

        next_stanza_start = (
            stanzas[s_num + 1][0][0]["start"] if s_num + 1 < len(stanzas) else None
        )

        lead_start = max(
            prev_stanza_end + 0.3 if prev_stanza_end > 0 else 0.0,
            stanza_first_start - 3.2
        )

        # 3-dot countdown (●  ●  ●)
        if (stanza_first_start - prev_stanza_end >= 2.8) or (s_num == 0 and stanza_first_start >= 2.0):
            cd_dur = min(3.0, max(1.5, stanza_first_start - lead_start))
            cd_start = stanza_first_start - cd_dur
            dot_cs = max(20, int(round((cd_dur / 3.0) * 100)))
            cd_text = f"{{\\kf{dot_cs}}}●   {{\\kf{dot_cs}}}●   {{\\kf{dot_cs}}}●"
            dialogue_entries.append(
                f"Dialogue: 2,{format_ass_time(cd_start)},{format_ass_time(stanza_first_start)},"
                f"Countdown,,0,0,0,,{cd_text}"
            )

        step_start = [0.0] * n_lines
        step_end = [0.0] * n_lines

        step_start[0] = lead_start
        for i in range(n_lines - 1):
            e_curr = stanza[i][-1]["end"]
            s_next = stanza[i + 1][0]["start"]
            if s_next <= e_curr:
                roll_t = s_next
            else:
                gap = s_next - e_curr
                hold = min(0.35, max(0.08, gap / 2.0))
                roll_t = min(e_curr + hold, s_next - 0.05)
                roll_t = max(e_curr + 0.05, roll_t)
            step_end[i] = roll_t
            step_start[i + 1] = roll_t

        last_hold = min(1.6, max(0.8, (next_stanza_start - stanza_last_end - 0.5) if next_stanza_start else 1.8))
        step_end[-1] = stanza_last_end + last_hold

        # Teleprompter rows (Layer 1)
        def _emit(style: str, layer: int, t_s: float, t_e: float, line_words, karaoke: bool):
            fs, bold, mv = style_meta[style]
            if karaoke:
                text_tags = build_karaoke_line_tags(line_words, t_s, font_size=fs)
                plain, _ = _plain_text_and_scale(line_words)
                scale = _karaoke_scale(line_words)
            else:
                text_tags = get_plain_line_text(line_words, font_size=fs)
                plain, scale = _plain_text_and_scale(line_words)
            dialogue_entries.append(
                f"Dialogue: {layer},{format_ass_time(t_s)},{format_ass_time(t_e)},"
                f"{style},,0,0,0,,{text_tags}"
            )
            if emoji_events_out is not None:
                for em in layout_line_emoji(plain, fs, bold, mv, scale_pct=scale):
                    em.update({"start": round(t_s, 3), "end": round(t_e, 3)})
                    emoji_events_out.append(em)

        for i in range(n_lines):
            t_s = step_start[i]
            t_e = step_end[i]
            if t_e <= t_s:
                continue

            # 1. Slot 1 (ACTIVE line with gold sweep)
            _emit("KaraokeActive", 1, t_s, t_e, stanza[i], karaoke=True)

            # 2. Slot 0 (PREVIOUS sung line, dimmed)
            if i > 0:
                _emit("KaraokePrev", 0, t_s, t_e, stanza[i - 1], karaoke=False)

            # 3. Slot 2 (NEXT line, crisp white)
            if i + 1 < n_lines:
                _emit("KaraokeNext", 0, t_s, t_e, stanza[i + 1], karaoke=False)

            # 4. Slot 3 (NEXT+1 line, soft silver) - only in 4-line layout
            if num_lines == 4 and i + 2 < n_lines:
                _emit("KaraokeNextNext", 0, t_s, t_e, stanza[i + 2], karaoke=False)

        prev_stanza_end = step_end[-1]

    if watermark_text and watermark_text.strip():
        raw_wm = watermark_text.replace("\n", " ").replace("{", "(").replace("}", ")").strip()
        wm_segs = split_text_emoji(raw_wm)
        clean_wm = "".join(seg if kind == "t" else "✦ " for kind, seg in wm_segs).strip()
        if clean_wm:
            dialogue_entries.append(
                f"Dialogue: 3,{format_ass_time(0.0)},{format_ass_time(total_song_end)},"
                f"DJWatermark,,0,0,0,,{clean_wm}"
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogue_entries) + "\n")

    print(f"[Karaoke] Создан ASS файл ({num_lines} строк телесуфлер, FX={visual_effects}, зон FX={len(fx_intervals)}): {output_path}")
    return output_path


def generate_ass_file(
    transcription_result: Dict[str, Any],
    output_path: Path,
    title: str = "Karaoke",
    num_lines: int = 4,
    reference_lyrics: Optional[str] = None,
    visual_effects: str = "sparkles_pulse",
    fx_intervals: Optional[List[Dict[str, Any]]] = None,
    audio_for_pulse: Optional[Path] = None,
    edge_color_mode: str = "cyberpunk",
    cover_edge_colors: Optional[Dict[str, str]] = None,
    has_cover_card: bool = True,
    font_size_mode: str = "large",
    highlight_color: str = "gold_neon",
    watermark_text: Optional[str] = None,
) -> Path:
    """
    High-level helper that splits a transcription result into verse-aware lines
    and writes the multi-line .ass karaoke file with visual effects.
    """
    segments = transcription_result.get("segments", [])
    lines = split_into_karaoke_lines(segments, reference_lyrics=reference_lyrics)
    return generate_ass_from_lines(
        lines,
        output_path,
        title=title,
        num_lines=num_lines,
        visual_effects=visual_effects,
        fx_intervals=fx_intervals,
        audio_for_pulse=audio_for_pulse,
        edge_color_mode=edge_color_mode,
        cover_edge_colors=cover_edge_colors,
        has_cover_card=has_cover_card,
        font_size_mode=font_size_mode,
        highlight_color=highlight_color,
        watermark_text=watermark_text,
    )
