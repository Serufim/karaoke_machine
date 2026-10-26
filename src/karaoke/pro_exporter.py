"""
Professional KJ / DJ and Karaoke Hardware Exporter.

Generates industry-standard karaoke formats from AI Karaoke Studio project state:
1. KaraFun / EnCore! (.kfn) binary container with multi-track audio (instrumental + guide vocal),
   background image, and syllable/word-synced song.ini.
2. Classic MP3+G (.cdg + .mp3 in .zip) with Cyrillic/Latin bitmap tile rendering and XOR sweep
   for VirtualDJ, OpenKJ, Siglos, and hardware CD+G players.
3. Enhanced LRC (.lrc) with word-level <mm:ss.xx> tags for EnCore!, AIMP, Poweramp, and mobile apps.
4. UltraStar Deluxe / Play (.txt) with FFT vocal pitch detection (MIDI notes) for singing battles.
5. Complete DJ Master Pack (.zip) bundling all formats and 320kbps MP3 stems.
"""
import io
import math
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

from karaoke.aligner import clean_word_token, editor_text_to_lines, validate_karaoke_lines
from karaoke.cancel_manager import check_cancelled, run_cancellable_command
from karaoke.emoji_layer import ARIAL_BOLD, split_text_emoji
from karaoke.mixer import mix_guide_vocals
from karaoke.video import create_default_background, find_ffmpeg


def _strip_emoji_for_legacy(text: str) -> str:
    """Strips color emoji for legacy formats (CD+G / KFN / LRC) while preserving Cyrillic/Latin text."""
    segs = split_text_emoji(text)
    cleaned = "".join(seg for kind, seg in segs if kind == "t")
    return " ".join(cleaned.split())


def format_lrc_time(seconds: float) -> str:
    """Formats seconds as MM:SS.xx for LRC / Enhanced LRC."""
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))
    minutes = total_cs // 6000
    rem = total_cs % 6000
    secs = rem // 100
    centis = rem % 100
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"


def export_enhanced_lrc(
    lines: List[List[Dict[str, Any]]],
    output_path: Path,
    title: str = "Karaoke",
    artist: str = "AI Karaoke Studio",
) -> Path:
    """
    Exports an Enhanced LRC (.lrc) file with both line timestamps [mm:ss.xx]
    and word-level karaoke sweep tags <mm:ss.xx>.
    Compatible with EnCore! Karaoke, AIMP, Poweramp, Foobar2000, and mobile players.
    """
    validate_karaoke_lines(lines)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lrc_lines = [
        f"[ti:{title}]",
        f"[ar:{artist}]",
        "[by:AI Karaoke Studio]",
        "[re:AI Karaoke Studio]",
        "",
    ]

    for line in lines:
        if not line:
            continue
        words_tagged: List[str] = []
        first_start: Optional[float] = None
        last_end: float = 0.0
        for w in line:
            w_text = _strip_emoji_for_legacy(clean_word_token(w.get("text", "")))
            if not w_text:
                continue
            w_start = max(0.0, float(w.get("start", 0.0)))
            w_end = max(w_start + 0.05, float(w.get("end", w_start + 0.25)))
            if first_start is None:
                first_start = w_start
            last_end = w_end
            words_tagged.append(f"<{format_lrc_time(w_start)}>{w_text}")

        if words_tagged and first_start is not None:
            joined = " ".join(words_tagged) + f"<{format_lrc_time(last_end)}>"
            lrc_lines.append(f"[{format_lrc_time(first_start)}]{joined}")

    output_path.write_text("\n".join(lrc_lines) + "\n", encoding="utf-8")
    return output_path


def _encode_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "256k") -> Path:
    """Encodes a WAV file into a CBR MP3 file using FFmpeg."""
    check_cancelled()
    mp3_path = Path(mp3_path)
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    if mp3_path.exists() and mp3_path.stat().st_size > 1024:
        if mp3_path.stat().st_mtime >= wav_path.stat().st_mtime:
            return mp3_path

    ffmpeg_bin = find_ffmpeg()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(Path(wav_path).resolve()),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-ar",
        "44100",
        str(mp3_path.resolve()),
    ]
    run_cancellable_command(cmd, prefix="FFmpeg-MP3")
    return mp3_path


def _prepare_kfn_cover(cover_path: Optional[Path], target_jpg: Path) -> Path:
    """Prepares a 1280x720 JPEG background image for the KFN container."""
    target_jpg.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1280, 720
    if cover_path and Path(cover_path).exists():
        try:
            img = Image.open(cover_path).convert("RGB")
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            img.save(target_jpg, "JPEG", quality=88)
            return target_jpg
        except Exception:
            pass

    tmp_png = target_jpg.with_suffix(".png")
    create_default_background(tmp_png, width=width, height=height)
    Image.open(tmp_png).convert("RGB").save(target_jpg, "JPEG", quality=88)
    tmp_png.unlink(missing_ok=True)
    return target_jpg


def _build_kfn_song_ini(
    lines: List[List[Dict[str, Any]]],
    title: str,
    artist: str,
    duration_sec: float,
    has_vocals_track: bool,
) -> str:
    """
    Builds the KaraFun / EnCore! `song.ini` configuration with word-level centisecond Sync tags.
    """
    sync_cs: List[int] = []
    text_lines: List[str] = []

    for line in lines:
        if not line:
            continue
        word_chunks: List[str] = []
        for idx, w in enumerate(line):
            w_text = _strip_emoji_for_legacy(clean_word_token(w.get("text", "")))
            if not w_text:
                continue
            w_start_cs = max(0, int(round(float(w.get("start", 0.0)) * 100)))
            sync_cs.append(w_start_cs)
            # In KaraFun song.ini, words on the same line after the first are prefixed with " "
            # and separated by "/" when multiple sync points exist on a line.
            if idx == 0 or not word_chunks:
                word_chunks.append(w_text)
            else:
                word_chunks.append(" " + w_text)
        if word_chunks:
            text_lines.append("/".join(word_chunks))

    # Split sync_cs into chunks of 60 values per SyncN entry (KaraFun standard)
    sync_entries: List[str] = []
    chunk_size = 60
    for i in range(0, max(1, len(sync_cs)), chunk_size):
        chunk = sync_cs[i : i + chunk_size]
        sync_entries.append(f"Sync{len(sync_entries)}=" + ",".join(str(v) for v in chunk))

    length_ms = max(1000, int(round(duration_sec * 1000)))
    ini_lines = [
        "[General]",
        f"Title={title}",
        f"Artist={artist}",
        "Year=2026",
        "Genre=-1",
        "Explicit=0",
        "Comment=Generated by AI Karaoke Studio",
        "Source=1,I,instrumental.mp3",
    ]
    if has_vocals_track:
        ini_lines.extend([
            "TrackCount=1",
            "Track0=1,0,0,V,vocals.mp3",
        ])
    else:
        ini_lines.append("TrackCount=0")

    ini_lines.extend([
        "",
        "[Marks]",
        "Count=0",
        "",
        "[MP3Music]",
        "File=instrumental.mp3",
        f"Length={length_ms}",
        "",
        "[Background]",
        "File=cover.jpg",
        "",
        "[Lyrics]",
        "Type=1",
        "FontName=Arial",
        "FontSize=28",
        "ActiveColor=#FFD700",
        "InactiveColor=#FFFFFF",
        "FrameColor=#000000",
        "FrameType=2",
        "LineCount=4",
        f"SyncCount={len(sync_entries)}",
    ])
    ini_lines.extend(sync_entries)
    ini_lines.append(f"TextCount={len(text_lines)}")
    for idx, tl in enumerate(text_lines):
        ini_lines.append(f"Text{idx}={tl}")

    return "\r\n".join(ini_lines) + "\r\n"


def export_kfn_package(
    lines: List[List[Dict[str, Any]]],
    instrumental_wav: Path,
    output_path: Path,
    title: str = "Karaoke",
    artist: str = "AI Karaoke Studio",
    vocals_wav: Optional[Path] = None,
    cover_path: Optional[Path] = None,
) -> Path:
    """
    Packages an unencrypted KaraFun / EnCore! `.kfn` binary container (`KFNB`)
    containing `instrumental.mp3`, optional `vocals.mp3` (for independent guide vocal fader
    in EnCore! and KaraFun Player), `cover.jpg`, and synchronized `song.ini`.
    """
    validate_karaoke_lines(lines)
    check_cancelled()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    info = sf.info(str(instrumental_wav))
    duration_sec = float(info.duration) if info.duration else (lines[-1][-1]["end"] + 2.0 if lines else 60.0)

    with tempfile.TemporaryDirectory(prefix="kfn_pack_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        inst_mp3 = _encode_mp3(instrumental_wav, tmp_dir / "instrumental.mp3", bitrate="256k")

        has_vocals = bool(vocals_wav and Path(vocals_wav).exists())
        voc_mp3 = None
        if has_vocals and vocals_wav is not None:
            voc_mp3 = _encode_mp3(vocals_wav, tmp_dir / "vocals.mp3", bitrate="192k")

        cover_jpg = _prepare_kfn_cover(cover_path, tmp_dir / "cover.jpg")
        song_ini_text = _build_kfn_song_ini(
            lines=lines,
            title=title,
            artist=artist,
            duration_sec=duration_sec,
            has_vocals_track=has_vocals,
        )
        song_ini_bytes = song_ini_text.encode("utf-8")

        # Subfile types in KFN spec: 1 = Text/INI, 2 = Audio, 3 = Image
        subfiles: List[Tuple[str, int, bytes]] = [
            ("instrumental.mp3", 2, inst_mp3.read_bytes()),
        ]
        if voc_mp3 is not None and voc_mp3.exists():
            subfiles.append(("vocals.mp3", 2, voc_mp3.read_bytes()))
        subfiles.append(("cover.jpg", 3, cover_jpg.read_bytes()))
        subfiles.append(("song.ini", 1, song_ini_bytes))

        with open(output_path, "wb") as f:
            # 1. File signature
            f.write(b"KFNB")

            # 2. Header fields
            def write_int_header(tag: str, val: int):
                f.write(tag.encode("ascii")[:4])
                f.write(b"\x01")
                f.write(int(val).to_bytes(4, "little", signed=False))

            def write_bytes_header(tag: str, payload: bytes):
                f.write(tag.encode("ascii")[:4])
                f.write(b"\x02")
                f.write(len(payload).to_bytes(4, "little", signed=False))
                f.write(payload)

            write_int_header("DIFF", 0)
            write_int_header("FTYP", 0)
            write_bytes_header("FLID", b"\x00" * 16)  # Unencrypted flag
            write_bytes_header("SORC", b"AI Karaoke Studio")

            # Header end marker
            f.write(b"ENDH\x01\xff\xff\xff\xff")

            # 3. Subfile directory table
            # Notice: offsets in KFN are relative to the start of the payload section
            f.write(len(subfiles).to_bytes(4, "little", signed=False))
            rel_offset = 0
            for name, ftype, data in subfiles:
                name_b = name.encode("utf-8")
                sz = len(data)
                f.write(len(name_b).to_bytes(4, "little", signed=False))
                f.write(name_b)
                f.write(int(ftype).to_bytes(4, "little", signed=False))
                f.write(sz.to_bytes(4, "little", signed=False))
                f.write(rel_offset.to_bytes(4, "little", signed=False))
                f.write(sz.to_bytes(4, "little", signed=False))
                f.write((0).to_bytes(4, "little", signed=False))  # unencrypted = 0
                rel_offset += sz

            # 4. Raw payload blocks
            for _name, _ftype, data in subfiles:
                f.write(data)

    return output_path


def inspect_kfn_package(kfn_path: Path) -> Dict[str, Any]:
    """
    Reads and validates a `.kfn` container file, returning its headers, subfile metadata,
    and decoded `song.ini` content. Useful for verification and diagnostics.
    """
    raw = Path(kfn_path).read_bytes()
    if len(raw) < 16 or raw[:4] != b"KFNB":
        raise ValueError("Invalid KFN signature (expected KFNB)")

    pos = 4
    headers: Dict[str, Any] = {}
    while pos + 5 <= len(raw):
        tag = raw[pos : pos + 4].decode("ascii", errors="replace")
        dtype = raw[pos + 4]
        pos += 5
        if tag == "ENDH":
            pos += 4
            break
        if dtype == 1:
            val = int.from_bytes(raw[pos : pos + 4], "little")
            headers[tag] = val
            pos += 4
        elif dtype == 2:
            ln = int.from_bytes(raw[pos : pos + 4], "little")
            pos += 4
            headers[tag] = raw[pos : pos + ln]
            pos += ln
        else:
            raise ValueError(f"Unknown KFN header type {dtype} for tag {tag}")

    num_files = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4
    entries: List[Dict[str, Any]] = []
    for _ in range(num_files):
        name_len = int.from_bytes(raw[pos : pos + 4], "little")
        pos += 4
        name = raw[pos : pos + name_len].decode("utf-8", errors="replace")
        pos += name_len
        ftype = int.from_bytes(raw[pos : pos + 4], "little")
        length_out = int.from_bytes(raw[pos + 4 : pos + 8], "little")
        offset = int.from_bytes(raw[pos + 8 : pos + 12], "little")
        length_in = int.from_bytes(raw[pos + 12 : pos + 16], "little")
        flags = int.from_bytes(raw[pos + 16 : pos + 20], "little")
        pos += 20
        entries.append({
            "name": name,
            "type": ftype,
            "length": length_out,
            "offset": offset,
            "length_in": length_in,
            "flags": flags,
        })

    data_base = pos
    song_ini = ""
    for e in entries:
        start = data_base + e["offset"]
        end = start + e["length_in"]
        e["size_valid"] = (end <= len(raw))
        if e["name"].lower() == "song.ini" and end <= len(raw):
            song_ini = raw[start:end].decode("utf-8", errors="replace")

    return {
        "headers": headers,
        "files": entries,
        "song_ini": song_ini,
    }


# ==============================================================================
# Classic CD+G (MP3+G) Binary Packet Generator (300 packets/sec, 24 bytes/packet)
# ==============================================================================

CDG_COMMAND = 0x09
CDG_INST_MEMORY_PRESET = 1
CDG_INST_BORDER_PRESET = 2
CDG_INST_TILE_BLOCK = 6
CDG_INST_LOAD_CLUT_LOW = 30
CDG_INST_LOAD_CLUT_HIGH = 31
CDG_INST_TILE_BLOCK_XOR = 38


def _make_cdg_packet(instruction: int, data_16: bytes) -> bytes:
    """Builds a 24-byte CD+G subcode packet."""
    assert len(data_16) == 16
    pkt = bytearray(24)
    pkt[0] = CDG_COMMAND
    pkt[1] = instruction & 0x3F
    pkt[4:20] = data_16
    return bytes(pkt)


def _encode_cdg_color(r: int, g: int, b: int) -> Tuple[int, int]:
    """Encodes 8-bit RGB (0..255) into 4-bit CD+G subcode color bytes (high_byte, low_byte)."""
    r4 = (r >> 4) & 0x0F
    g4 = (g >> 4) & 0x0F
    b4 = (b >> 4) & 0x0F
    high = (r4 << 2) | (g4 >> 2)
    low = ((g4 & 0x03) << 4) | b4
    return high & 0x3F, low & 0x3F


def _cdg_clut_packets() -> List[bytes]:
    """
    Creates the CD+G Color Lookup Table (CLUT) packets.
    Color 0: Deep Club Navy background (12, 14, 24)
    Color 1: Crisp White unsung text (255, 255, 255)
    Color 2: XOR difference mask
    Color 3: Gold Neon sung text (255, 215, 0) -> Note: 1 ^ 2 == 3!
             Applying XOR with color1=2 flips Color 1 (White) into Color 3 (Gold)
             while leaving Color 0 (Background) untouched (0 ^ 0 == 0).
    """
    palette_low = [
        (12, 14, 24),     # 0: Background
        (255, 255, 255),  # 1: Unsung text (White)
        (255, 215, 0),    # 2: Secondary Gold
        (255, 215, 0),    # 3: Sung text via 1 ^ 2 = 3 (Gold Neon)
        (160, 175, 205),  # 4: Preview / title accent
        (0, 240, 255),    # 5: Cyan accent
        (255, 20, 147),   # 6: Magenta accent
        (0, 0, 0),        # 7: Black
    ]
    data_low = bytearray(16)
    for idx, (r, g, b) in enumerate(palette_low):
        hi, lo = _encode_cdg_color(r, g, b)
        data_low[idx * 2] = hi
        data_low[idx * 2 + 1] = lo

    data_high = bytearray(16)
    return [
        _make_cdg_packet(CDG_INST_LOAD_CLUT_LOW, bytes(data_low)),
        _make_cdg_packet(CDG_INST_LOAD_CLUT_HIGH, bytes(data_high)),
    ]


def _cdg_clear_screen_packets(bg_color: int = 0) -> List[bytes]:
    """Generates Memory Preset + Border Preset packets to clear the CD+G screen."""
    pkts: List[bytes] = []
    for repeat in range(16):
        data = bytearray(16)
        data[0] = bg_color & 0x0F
        data[1] = repeat & 0x0F
        pkts.append(_make_cdg_packet(CDG_INST_MEMORY_PRESET, bytes(data)))
    b_data = bytearray(16)
    b_data[0] = bg_color & 0x0F
    pkts.append(_make_cdg_packet(CDG_INST_BORDER_PRESET, bytes(b_data)))
    return pkts


def _cdg_tile_packet(row: int, col: int, color0: int, color1: int, pixels_12x6: List[int], xor: bool = False) -> bytes:
    """Builds a CDG_TILE_BLOCK or CDG_TILE_BLOCK_XOR packet for a 6x12 pixel tile."""
    data = bytearray(16)
    data[0] = color0 & 0x0F
    data[1] = color1 & 0x0F
    data[2] = row & 0x1F
    data[3] = col & 0x3F
    for r_idx in range(12):
        data[4 + r_idx] = pixels_12x6[r_idx] & 0x3F
    instr = CDG_INST_TILE_BLOCK_XOR if xor else CDG_INST_TILE_BLOCK
    return _make_cdg_packet(instr, bytes(data))


def _render_line_tiles_24px(text: str) -> Tuple[List[Tuple[int, int, List[int]]], int, int]:
    """
    Renders a single line of Cyrillic/Latin text onto a 288x24 bitmap (48 columns x 2 tile rows of 6x12),
    returning:
    - list of non-empty tiles: (rel_row 0..1, col 1..48, 12-byte bitmask)
    - start_col (1..48)
    - end_col (1..48)
    """
    width, height = 288, 24
    img = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(img)

    font_size = 16 if len(text) <= 26 else max(11, int(26 * 16 / max(1, len(text))))
    try:
        font = ImageFont.truetype(str(ARIAL_BOLD), font_size) if ARIAL_BOLD.exists() else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = max(2, (width - tw) // 2)
    y = max(1, (height - th) // 2 - bbox[1])
    draw.text((x, y), text, fill=255, font=font)

    px = img.load()
    tiles: List[Tuple[int, int, List[int]]] = []
    min_col = 49
    max_col = 0

    for t_row in range(2):
        for t_col in range(48):
            rows_bits: List[int] = []
            has_fg = False
            for py in range(12):
                y_coord = t_row * 12 + py
                bits = 0
                for px_i in range(6):
                    x_coord = t_col * 6 + px_i
                    val = px[x_coord, y_coord] if px is not None else 0
                    if val > 96:
                        bits |= (1 << (5 - px_i))
                        has_fg = True
                rows_bits.append(bits)
            if has_fg:
                col_idx = t_col + 1  # Visible CD+G columns are 1..48
                tiles.append((t_row, col_idx, rows_bits))
                min_col = min(min_col, col_idx)
                max_col = max(max_col, col_idx)

    if min_col > max_col:
        min_col, max_col = 1, 1
    return tiles, min_col, max_col


def export_cdg_zip(
    lines: List[List[Dict[str, Any]]],
    instrumental_wav: Path,
    output_zip_path: Path,
    title: str = "Karaoke",
) -> Path:
    """
    Generates a standard MP3+G karaoke archive (`{title}_cdg.zip` containing `{title}.mp3` and `{title}.cdg`)
    compatible with OpenKJ, VirtualDJ, KaraFun, and Siglos Karaoke Professional.
    """
    validate_karaoke_lines(lines)
    check_cancelled()
    output_zip_path = Path(output_zip_path)
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)

    info = sf.info(str(instrumental_wav))
    duration_sec = float(info.duration) if info.duration else (lines[-1][-1]["end"] + 2.0 if lines else 60.0)
    total_packets = max(300, int(math.ceil((duration_sec + 1.0) * 300)))

    empty_pkt = bytes(24)
    stream: List[bytes] = [empty_pkt] * total_packets
    cursor = 0

    def place_packets(start_pkt: int, pkts: List[bytes]) -> int:
        idx = max(0, start_pkt)
        for p in pkts:
            while idx < total_packets and stream[idx] != empty_pkt:
                idx += 1
            if idx >= total_packets:
                break
            stream[idx] = p
            idx += 1
        return idx

    # Initialize CLUT and clear screen at t=0.0s
    cursor = place_packets(0, _cdg_clut_packets() + _cdg_clear_screen_packets(0))

    # Group lines into pages of 4 lines (rows on screen: 2..3, 6..7, 10..11, 14..15)
    slot_base_rows = [2, 6, 10, 14]
    non_empty_lines = [ln for ln in lines if ln]

    for page_idx in range(0, len(non_empty_lines), 4):
        page_lines = non_empty_lines[page_idx : page_idx + 4]
        if not page_lines:
            continue
        page_start_sec = max(0.0, float(page_lines[0][0].get("start", 0.0)) - 1.5)
        draw_pkt_idx = max(cursor, int(page_start_sec * 300))

        # Clear previous page and load palette
        page_init_pkts = _cdg_clut_packets() + _cdg_clear_screen_packets(0)
        cursor = place_packets(draw_pkt_idx, page_init_pkts)

        for slot_i, line in enumerate(page_lines):
            base_row = slot_base_rows[slot_i]
            words_clean = [
                _strip_emoji_for_legacy(clean_word_token(w.get("text", "")))
                for w in line
            ]
            words_clean = [w for w in words_clean if w]
            full_text = " ".join(words_clean)
            if not full_text:
                continue

            tiles, min_col, max_col = _render_line_tiles_24px(full_text)
            # Draw unsung white text (color0=0, color1=1)
            draw_tiles = [
                _cdg_tile_packet(base_row + r_off, col, 0, 1, bits, xor=False)
                for (r_off, col, bits) in tiles
            ]
            cursor = place_packets(cursor, draw_tiles)

            # Calculate column span for each word to sweep with XOR (color0=0, color1=2 -> 1^2 = 3 Gold)
            total_chars = max(1, len(full_text))
            col_span = max(1, max_col - min_col + 1)
            char_cursor = 0
            swept_cols = set()

            for w_obj in line:
                w_str = _strip_emoji_for_legacy(clean_word_token(w_obj.get("text", "")))
                if not w_str:
                    continue
                w_start = max(0.0, float(w_obj.get("start", 0.0)))
                w_end = max(w_start + 0.08, float(w_obj.get("end", w_start + 0.25)))

                c_start = min_col + int(round((char_cursor / total_chars) * col_span))
                char_cursor += len(w_str) + 1
                c_end = min_col + int(round((min(total_chars, char_cursor) / total_chars) * col_span))

                word_cols = [c for c in range(c_start, max(c_start + 1, c_end + 1)) if c not in swept_cols and min_col <= c <= max_col]
                if not word_cols:
                    continue

                dur = max(0.06, w_end - w_start)
                for step_i, col_val in enumerate(word_cols):
                    swept_cols.add(col_val)
                    col_time = w_start + (step_i / max(1, len(word_cols))) * dur
                    pkt_pos = int(col_time * 300)
                    xor_pkts = [
                        _cdg_tile_packet(base_row, col_val, 0, 2, [0x3F] * 12, xor=True),
                        _cdg_tile_packet(base_row + 1, col_val, 0, 2, [0x3F] * 12, xor=True),
                    ]
                    place_packets(pkt_pos, xor_pkts)

    safe_stem = "".join(c if c.isalnum() or c in " -_()" else "_" for c in title).strip() or "karaoke"
    with tempfile.TemporaryDirectory(prefix="cdg_pack_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        mp3_file = _encode_mp3(instrumental_wav, tmp_dir / f"{safe_stem}.mp3", bitrate="256k")
        cdg_file = tmp_dir / f"{safe_stem}.cdg"
        cdg_file.write_bytes(b"".join(stream))

        with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(mp3_file, arcname=f"{safe_stem}.mp3")
            zf.write(cdg_file, arcname=f"{safe_stem}.cdg")

    return output_zip_path


# ==============================================================================
# UltraStar Deluxe / Play (.txt) Generator with Vocal Pitch Estimation
# ==============================================================================

def _estimate_midi_pitch(samples: np.ndarray, sr: int) -> int:
    """
    Estimates the dominant vocal fundamental frequency (85..800 Hz) using
    windowed FFT magnitude spectrum and converts it to UltraStar relative MIDI pitch
    (MIDI note - 48, where C4=60 -> 12, A4=69 -> 21).
    """
    if len(samples) < 512 or sr <= 0:
        return 12
    mono = samples[:, 0] if samples.ndim > 1 else samples
    rms = float(np.sqrt(np.mean(mono ** 2)))
    if rms < 1e-4:
        return 12

    # Take up to 4096 samples from the center of the word
    n = min(len(mono), 4096)
    mid = len(mono) // 2
    seg = mono[max(0, mid - n // 2) : max(0, mid - n // 2) + n]
    windowed = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(windowed), d=1.0 / sr)

    mask = (freqs >= 85.0) & (freqs <= 800.0)
    if not np.any(mask):
        return 12
    sub_spec = spec[mask]
    sub_freqs = freqs[mask]
    peak_idx = int(np.argmax(sub_spec))
    f0 = float(sub_freqs[peak_idx])
    if f0 <= 0:
        return 12

    midi_note = int(round(69.0 + 12.0 * math.log2(f0 / 440.0)))
    return max(0, min(36, midi_note - 48))


def export_ultrastar_txt(
    lines: List[List[Dict[str, Any]]],
    output_path: Path,
    title: str = "Karaoke",
    artist: str = "AI Karaoke Studio",
    audio_filename: str = "instrumental.mp3",
    vocals_wav: Optional[Path] = None,
    cover_filename: Optional[str] = None,
) -> Path:
    """
    Exports an UltraStar Deluxe / UltraStar Play song file (`.txt`) with automatic
    MIDI vocal pitch targets extracted from `vocals_wav`.
    Uses BPM=300 (so 1 UltraStar beat = 1/20th of a second = 50ms resolution).
    """
    validate_karaoke_lines(lines)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    voc_data: Optional[np.ndarray] = None
    sr_voc: int = 44100
    if vocals_wav and Path(vocals_wav).exists():
        try:
            voc_data, sr_voc = sf.read(str(vocals_wav), dtype="float32", always_2d=True)
        except Exception:
            voc_data = None

    # BPM=300 in UltraStar means 4 * 300 / 60 = 20 beats per second (50ms per beat)
    beats_per_sec = 20.0

    header = [
        f"#TITLE:{title}",
        f"#ARTIST:{artist}",
        f"#MP3:{audio_filename}",
        "#BPM:300",
        "#GAP:0",
        "#CREATOR:AI Karaoke Studio",
    ]
    if cover_filename:
        header.append(f"#COVER:{cover_filename}")

    body: List[str] = []
    prev_beat_end = 0

    for line_idx, line in enumerate(lines):
        if not line:
            continue
        line_has_words = False
        for w in line:
            w_text = _strip_emoji_for_legacy(clean_word_token(w.get("text", "")))
            if not w_text:
                continue
            w_start = max(0.0, float(w.get("start", 0.0)))
            w_end = max(w_start + 0.05, float(w.get("end", w_start + 0.25)))

            b_start = max(prev_beat_end, int(round(w_start * beats_per_sec)))
            b_dur = max(1, int(round((w_end - w_start) * beats_per_sec)))

            pitch = 12
            if voc_data is not None and len(voc_data) > 0:
                s_idx = max(0, min(len(voc_data), int(w_start * sr_voc)))
                e_idx = max(s_idx, min(len(voc_data), int(w_end * sr_voc)))
                pitch = _estimate_midi_pitch(voc_data[s_idx:e_idx], sr_voc)

            body.append(f": {b_start} {b_dur} {pitch} {w_text} ")
            prev_beat_end = b_start + b_dur
            line_has_words = True

        if line_has_words and line_idx < len(lines) - 1:
            body.append(f"- {prev_beat_end}")

    body.append("E")
    output_path.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    return output_path


def export_dj_master_pack(
    state_data: Dict[str, Any],
    output_dir: Path,
    editor_text: Optional[str] = None,
    vocal_volume: float = 0.0,
    vocal_intervals: Optional[List[Dict[str, Any]]] = None,
    progress_callback=None,
) -> Tuple[Path, Path]:
    """
    Builds the universal DJ / KJ Master Pack from current project state without re-running AI models:
    1. `{title}.kfn` (for EnCore! Karaoke & KaraFun Player with independent vocal fader)
    2. `{title}_DJ_Pack.zip` containing:
       - `{title}.kfn`
       - `{title}_cdg.zip` (MP3+G for VirtualDJ / OpenKJ / Siglos)
       - `{title}.lrc` (Enhanced word-level LRC)
       - `{title}_ultrastar.txt` (UltraStar Deluxe / Play singing game format)
       - `{title}_instrumental.mp3` (backing track with vocal automation)
       - `{title}_vocals.mp3` (isolated vocal stem for DJ live mixing)
    Returns `(dj_pack_zip_path, kfn_path)`.
    """
    def log(msg: str, frac: float):
        check_cancelled()
        print(f"[DJ Export] {msg}")
        if progress_callback:
            progress_callback(msg, frac)

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    title = state_data["title"]
    vocals_wav = Path(state_data["vocals_wav"])
    no_vocals_wav = Path(state_data["no_vocals_wav"])
    cover_image = Path(state_data["cover_image"]) if state_data.get("cover_image") else None
    original_lines = state_data.get("lines", [])

    if editor_text and editor_text.strip():
        lines = editor_text_to_lines(editor_text, original_lines=original_lines)
    else:
        lines = original_lines
    validate_karaoke_lines(lines)

    active_vocal_intervals = (
        vocal_intervals if vocal_intervals is not None else state_data.get("vocal_intervals", [])
    )

    log("Шаг 1/5: Подготовка аудиодорожек минуса и вокала...", 0.15)
    vol_pct = int(round(vocal_volume * 100))
    mixed_wav_path = work_dir / f"{title}_mix_{vol_pct}pct.wav"
    backing_audio = mix_guide_vocals(
        instrumental_path=no_vocals_wav,
        vocals_path=vocals_wav,
        output_path=mixed_wav_path,
        vocal_volume=vocal_volume,
        vocal_intervals=active_vocal_intervals,
    )

    log("Шаг 2/5: Сборка контейнера .KFN (EnCore! / KaraFun)...", 0.35)
    kfn_path = output_dir / f"{title}.kfn"
    export_kfn_package(
        lines=lines,
        instrumental_wav=backing_audio,
        output_path=kfn_path,
        title=title,
        vocals_wav=vocals_wav if vocals_wav.exists() else None,
        cover_path=cover_image if (cover_image and cover_image.exists()) else None,
    )

    log("Шаг 3/5: Генерация пакета MP3+G (.CDG + .MP3) для VirtualDJ / OpenKJ...", 0.55)
    cdg_zip_path = work_dir / f"{title}_cdg.zip"
    export_cdg_zip(
        lines=lines,
        instrumental_wav=backing_audio,
        output_zip_path=cdg_zip_path,
        title=title,
    )

    log("Шаг 4/5: Генерация Enhanced .LRC и UltraStar .TXT (с анализом нот)...", 0.75)
    lrc_path = output_dir / f"{title}.lrc"
    export_enhanced_lrc(lines=lines, output_path=lrc_path, title=title)

    ultrastar_path = output_dir / f"{title}_ultrastar.txt"
    export_ultrastar_txt(
        lines=lines,
        output_path=ultrastar_path,
        title=title,
        audio_filename=f"{title}_instrumental.mp3",
        vocals_wav=vocals_wav if vocals_wav.exists() else None,
    )

    log("Шаг 5/5: Упаковка полного архива DJ Master Pack (.zip)...", 0.90)
    inst_mp3 = _encode_mp3(backing_audio, work_dir / f"{title}_instrumental.mp3", bitrate="320k")
    voc_mp3 = (
        _encode_mp3(vocals_wav, work_dir / f"{title}_vocals.mp3", bitrate="256k")
        if vocals_wav.exists()
        else None
    )

    dj_zip_path = output_dir / f"{title}_DJ_Pack.zip"
    with zipfile.ZipFile(dj_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(kfn_path, arcname=kfn_path.name)
        zf.write(cdg_zip_path, arcname=cdg_zip_path.name)
        zf.write(lrc_path, arcname=lrc_path.name)
        zf.write(ultrastar_path, arcname=ultrastar_path.name)
        zf.write(inst_mp3, arcname=f"{title}_instrumental.mp3")
        if voc_mp3 and voc_mp3.exists():
            zf.write(voc_mp3, arcname=f"{title}_vocals.mp3")
        ass_candidate = output_dir / f"{title}_karaoke.ass"
        if ass_candidate.exists():
            zf.write(ass_candidate, arcname=ass_candidate.name)

    log(f"DJ-пак готов: {dj_zip_path.name} и {kfn_path.name}", 1.0)
    return dj_zip_path, kfn_path
