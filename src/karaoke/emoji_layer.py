"""
Native Apple Color Emoji layer for karaoke videos.

libass (FFmpeg `subtitles` filter) cannot rasterize color bitmap fonts such as
`Apple Color Emoji.ttc`, so emoji inside ASS text become empty "tofu" squares.

This module:
1. Splits lyric text into text / emoji segments and builds invisible ASS placeholders
   of the exact emoji width (so the text layout keeps a gap for the emoji).
2. Measures the line layout with the same Arial metrics libass uses, to compute
   the on-screen center of every emoji.
3. Renders the emoji with Pillow (`embedded_color=True`) and produces:
   - an ffconcat image sequence (full-frame transparent PNGs) for lyric emoji,
   - small PNG sprites + motion paths for flying "emoji burst" FX particles.
"""
import hashlib
import json
import random
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

APPLE_EMOJI_FONT = Path("/System/Library/Fonts/Apple Color Emoji.ttc")
ARIAL_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
ARIAL_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

# Arial: (winAscent + winDescent) / unitsPerEm = (1854 + 434) / 2048.
# libass (VSFilter-compatible) maps ASS Fontsize to that full height, not to the em.
ARIAL_EM_RATIO = 2048.0 / 2288.0
ARIAL_DESCENT_RATIO = 434.0 / 2288.0

# Emoji relative size vs ASS font size and side padding of the invisible placeholder
EMOJI_SIZE_RATIO = 0.92
EMOJI_PAD_RATIO = 0.10

DEFAULT_FX_EMOJIS = "🔥✨🎤👑"

_EMOJI_CLUSTER_RE = re.compile(
    r"(?:[\U0001F1E6-\U0001F1FF]{2})"
    r"|(?:[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u2460-\u24FF\u25A0-\u27BF\u2900-\u297F\u2B00-\u2BFF\u3030\u303D\u3297\u3299]"
    r"\uFE0F?[\U0001F3FB-\U0001F3FF]?"
    r"(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF]\uFE0F?[\U0001F3FB-\U0001F3FF]?)*)"
)


def apple_emoji_available() -> bool:
    return APPLE_EMOJI_FONT.exists()


@lru_cache(maxsize=8)
def _emoji_font(strike: int = 160) -> Optional[ImageFont.FreeTypeFont]:
    if not apple_emoji_available():
        return None
    try:
        return ImageFont.truetype(str(APPLE_EMOJI_FONT), strike)
    except Exception:
        return None


def _render_base(cluster: str) -> str:
    """Pillow has no raqm here, so ZWJ sequences can't be shaped: keep base emoji (+skin tone)."""
    base = cluster.split("\u200D")[0].replace("\uFE0F", "")
    if len(base) >= 2 and "\U0001F1E6" <= base[0] <= "\U0001F1FF":
        return base  # flags are rendered via ligature only with raqm; try anyway
    return base


@lru_cache(maxsize=1024)
def _render_emoji_rgba(cluster: str) -> Optional[Image.Image]:
    """Renders a single emoji at the 160px strike and crops it to its visible bounding box."""
    font = _emoji_font(160)
    if font is None:
        return None
    text = _render_base(cluster)
    canvas = Image.new("RGBA", (220 * max(1, len(text)), 220), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((10, 10), text, font=font, embedded_color=True)
    except Exception:
        return None
    bbox = canvas.getbbox()
    if not bbox:
        return None
    img = canvas.crop(bbox)
    # Square it so every emoji is centered the same way
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.size[0]) // 2, (side - img.size[1]) // 2), img)
    return square


def is_renderable_emoji(cluster: str) -> bool:
    return _render_emoji_rgba(cluster) is not None


def emoji_sprite(cluster: str, size_px: int) -> Optional[Image.Image]:
    base = _render_emoji_rgba(cluster)
    if base is None:
        return None
    size_px = max(8, int(size_px))
    return base.resize((size_px, size_px), Image.Resampling.LANCZOS)


def split_text_emoji(text: str) -> List[Tuple[str, str]]:
    """Splits text into [('t', text) | ('e', emoji)] segments (only renderable Apple emoji)."""
    segments: List[Tuple[str, str]] = []
    pos = 0
    for m in _EMOJI_CLUSTER_RE.finditer(text):
        cluster = m.group(0)
        if not is_renderable_emoji(cluster):
            continue
        if m.start() > pos:
            segments.append(("t", text[pos:m.start()]))
        segments.append(("e", cluster))
        pos = m.end()
    if pos < len(text):
        segments.append(("t", text[pos:]))
    return segments


def split_text_with_emoji(text: str) -> List[Dict[str, Any]]:
    """Convenience helper returning [{'text': s, 'is_emoji': bool}]."""
    return [{"text": seg, "is_emoji": (kind == "e")} for kind, seg in split_text_emoji(text)]


def has_emoji(text: str) -> bool:
    return any(kind == "e" for kind, _ in split_text_emoji(text))


def parse_emoji_set(text: Optional[str]) -> List[str]:
    """Extracts a list of renderable emoji from a free-form string (e.g. '🔥 🚀👑')."""
    if not text:
        return []
    return [seg for kind, seg in split_text_emoji(text) if kind == "e"]


def emoji_box_width(font_size: float) -> float:
    """Width (in ASS script pixels, before \\fscx) reserved for one emoji."""
    return font_size * (EMOJI_SIZE_RATIO + 2 * EMOJI_PAD_RATIO)


def ass_placeholder(font_size: float, restore_alpha: str) -> str:
    """
    Invisible inline ASS drawing of the emoji width. Drawings in libass behave like a glyph,
    so the following text is pushed right exactly as if the emoji were there.
    """
    w = int(round(emoji_box_width(font_size)))
    h = max(2, int(round(font_size * 0.2)))
    return (
        "{\\alpha&HFF&\\p1}"
        f"m 0 0 l {w} 0 l {w} {h} l 0 {h}"
        "{\\p0" + restore_alpha + "}"
    )


@lru_cache(maxsize=16)
def _arial(size_px: float, bold: bool) -> Optional[ImageFont.FreeTypeFont]:
    path = ARIAL_BOLD if bold else ARIAL_REGULAR
    if not path.exists():
        return None
    try:
        return ImageFont.truetype(str(path), max(1, int(round(size_px))))
    except Exception:
        return None


def _text_width(text: str, font_size: float, bold: bool, spacing: float) -> float:
    font = _arial(font_size * ARIAL_EM_RATIO, bold)
    if font is None:
        return len(text) * font_size * 0.5
    return float(font.getlength(text)) + spacing * len(text)


def layout_line_emoji(
    text: str,
    font_size: float,
    bold: bool,
    margin_v: int,
    scale_pct: int = 100,
    spacing: float = 0.5,
    play_res: Tuple[int, int] = (1920, 1080),
    center_x: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Computes the screen position of every emoji in a bottom-center aligned (\\an2) ASS line.
    Returns [{'emoji', 'x', 'y', 'size'}] where x/y is the emoji center.
    """
    segments = split_text_emoji(text)
    if not any(k == "e" for k, _ in segments):
        return []
    scale = scale_pct / 100.0
    res_x, res_y = play_res
    cx = center_x if center_x is not None else res_x / 2.0

    widths = []
    for kind, seg in segments:
        if kind == "e":
            widths.append(emoji_box_width(font_size) * scale)
        else:
            widths.append(_text_width(seg, font_size, bold, spacing) * scale)
    total_w = sum(widths)
    x = cx - total_w / 2.0

    line_bottom = res_y - margin_v
    baseline = line_bottom - font_size * ARIAL_DESCENT_RATIO * scale
    emoji_size = font_size * EMOJI_SIZE_RATIO * scale
    # Apple emoji visually span from slightly below baseline to ~cap height
    y_center = baseline - font_size * 0.34 * scale

    out = []
    for (kind, seg), w in zip(segments, widths):
        if kind == "e":
            out.append({
                "emoji": seg,
                "x": round(x + w / 2.0, 1),
                "y": round(y_center, 1),
                "size": int(round(emoji_size)),
            })
        x += w
    return out


# ---------------------------------------------------------------------------
# Lyric emoji: ffconcat full-frame transparent image sequence
# ---------------------------------------------------------------------------

def build_lyric_emoji_sequence(
    events: List[Dict[str, Any]],
    work_dir: Path,
    total_duration: float,
    size: Tuple[int, int] = (1920, 1080),
) -> Optional[Path]:
    """
    events: [{'start', 'end', 'emoji', 'x', 'y', 'size'}].
    Produces an ffconcat file of transparent PNG frames covering [0, total_duration].
    """
    events = [e for e in events if e["end"] > e["start"]]
    if not events:
        return None

    seq_dir = work_dir / "emoji_frames"
    seq_dir.mkdir(parents=True, exist_ok=True)

    boundaries = sorted({0.0, float(total_duration)} | {round(e["start"], 3) for e in events} | {round(e["end"], 3) for e in events})
    boundaries = [b for b in boundaries if 0.0 <= b <= total_duration]

    empty_path = seq_dir / "empty.png"
    if not empty_path.exists():
        Image.new("RGBA", size, (0, 0, 0, 0)).save(empty_path)

    entries: List[Tuple[Path, float]] = []
    for i in range(len(boundaries) - 1):
        a, b = boundaries[i], boundaries[i + 1]
        if b - a <= 0.0005:
            continue
        mid = (a + b) / 2.0
        active = [e for e in events if e["start"] <= mid < e["end"]]
        if not active:
            frame_path = empty_path
        else:
            key = json.dumps(sorted([(e["emoji"], e["x"], e["y"], e["size"]) for e in active]), ensure_ascii=False)
            digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
            frame_path = seq_dir / f"f_{digest}.png"
            if not frame_path.exists():
                frame = Image.new("RGBA", size, (0, 0, 0, 0))
                for e in active:
                    sprite = emoji_sprite(e["emoji"], e["size"])
                    if sprite is None:
                        continue
                    px = int(round(e["x"] - sprite.size[0] / 2.0))
                    py = int(round(e["y"] - sprite.size[1] / 2.0))
                    frame.alpha_composite(sprite, (max(0, px), max(0, py)))
                frame.save(frame_path)
        # merge consecutive identical frames
        if entries and entries[-1][0] == frame_path:
            entries[-1] = (frame_path, entries[-1][1] + (b - a))
        else:
            entries.append((frame_path, b - a))

    if not entries:
        return None

    concat_path = work_dir / "emoji_lyrics.ffconcat"
    lines = ["ffconcat version 1.0"]
    for path, dur in entries:
        lines.append(f"file '{path.resolve().as_posix()}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{entries[-1][0].resolve().as_posix()}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat_path


# ---------------------------------------------------------------------------
# Flying emoji FX particles (rendered with FFmpeg overlay expressions)
# ---------------------------------------------------------------------------

SPRITE_SIZES = (64, 88, 120)
MAX_PARTICLES_TOTAL = 140


def generate_emoji_particles(
    intervals: List[Dict[str, Any]],
    default_emojis: Optional[str] = None,
    seed: int = 7,
) -> List[Dict[str, Any]]:
    """
    intervals: [{'start', 'end', 'intensity', 'emojis'}].
    Returns particles: [{'emoji', 'size', 'start', 'end', 'x1', 'y1', 'x2', 'y2', 'wobble', 'phase'}]
    Particles float upward along the left/right columns and the top banner (never over lyrics).
    """
    fallback = parse_emoji_set(default_emojis) or parse_emoji_set(DEFAULT_FX_EMOJIS)
    particles: List[Dict[str, Any]] = []
    total_dur = sum(max(0.0, float(i["end"]) - float(i["start"])) for i in intervals) or 1.0

    for itv in intervals:
        s, e = float(itv["start"]), float(itv["end"])
        dur = e - s
        if dur <= 0.4:
            continue
        emojis = parse_emoji_set(itv.get("emojis")) or fallback
        if not emojis:
            continue
        intensity = max(0.1, min(1.0, float(itv.get("intensity", 0.85))))
        is_climax = itv.get("climax", False)
        share = MAX_PARTICLES_TOTAL * dur / total_dur
        n = int(min(share, dur * (2.2 if is_climax else 1.5) * intensity))
        n = max(2, n)
        rng = random.Random(int(s * 100) + seed)
        for _ in range(n):
            p_start = s + rng.uniform(0.0, max(0.05, dur - 1.0))
            p_dur = rng.uniform(2.0, 3.4)
            p_end = min(e + 0.6, p_start + p_dur)
            if p_end - p_start < 0.8:
                continue
            size = rng.choice(SPRITE_SIZES)
            zone = rng.random()
            if zone < 0.42:
                x1 = rng.randint(40, 330)
                y1 = rng.randint(620, 1000)
            elif zone < 0.84:
                x1 = rng.randint(1590 - size, 1880 - size)
                y1 = rng.randint(620, 1000)
            else:
                x1 = rng.choice([rng.randint(380, 700), rng.randint(1220, 1540)])
                y1 = rng.randint(260, 420)
            x2 = x1 + rng.randint(-60, 60)
            y2 = y1 - rng.randint(260, 520) if zone < 0.84 else y1 - rng.randint(120, 240)
            particles.append({
                "emoji": rng.choice(emojis),
                "size": size,
                "start": round(p_start, 3),
                "end": round(p_end, 3),
                "x1": x1, "y1": y1, "x2": x2, "y2": max(-size, y2),
                "wobble": rng.randint(10, 34),
                "phase": round(rng.uniform(0, 6.28), 2),
            })
    particles.sort(key=lambda p: p["start"])
    return particles[:MAX_PARTICLES_TOTAL]


def save_particle_sprites(particles: List[Dict[str, Any]], work_dir: Path) -> Dict[Tuple[str, int], Path]:
    sprite_dir = work_dir / "emoji_sprites"
    sprite_dir.mkdir(parents=True, exist_ok=True)
    out: Dict[Tuple[str, int], Path] = {}
    for p in particles:
        key = (p["emoji"], p["size"])
        if key in out:
            continue
        name = "_".join(f"{ord(c):x}" for c in p["emoji"]) + f"_{p['size']}.png"
        path = sprite_dir / name
        if not path.exists():
            sprite = emoji_sprite(p["emoji"], p["size"])
            if sprite is None:
                continue
            sprite.save(path)
        out[key] = path
    return out
