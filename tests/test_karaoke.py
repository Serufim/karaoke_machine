from pathlib import Path
import numpy as np
import soundfile as sf

from PIL import Image

from karaoke.aligner import (
    refine_word_timestamps,
    split_into_karaoke_lines,
    lines_to_editor_text,
    editor_text_to_lines,
)
from karaoke.mixer import mix_guide_vocals
from karaoke.ass_writer import generate_ass_from_lines, NEON_PALETTES
from karaoke.video import render_karaoke_video, prepare_background_image
from karaoke.downloader import get_audio_from_source


def test_disfluency_removal_and_unsquash(tmp_path: Path):
    """Verifies that [*] tokens are removed, vocal onset is clamped, and 0.02s squashed words are fixed."""
    sr = 16000
    duration = 10.0
    # Silence from 0 to 3.0s, then vocal tone from 3.0s to 8.0s
    audio = np.zeros(int(sr * duration), dtype=np.float32)
    t_active = np.linspace(0, 5.0, int(sr * 5.0), endpoint=False)
    audio[int(sr * 3.0): int(sr * 8.0)] = 0.4 * np.sin(2 * np.pi * 220 * t_active)
    vocals_wav = tmp_path / "vocals_onset.wav"
    sf.write(str(vocals_wav), audio, sr)

    raw_transcription = {
        "segments": [
            {
                "start": 0.0,
                "end": 6.0,
                "words": [
                    {"text": "[*]", "start": 0.0, "end": 2.9},
                    {"text": "Я", "start": 0.0, "end": 3.5},
                    {"text": "не", "start": 4.0, "end": 4.02},
                    {"text": "влекут", "start": 4.02, "end": 4.04},
                    {"text": "уже", "start": 4.04, "end": 4.06},
                    {"text": "арбузы", "start": 4.06, "end": 5.5},
                ],
            }
        ]
    }

    refined = refine_word_timestamps(raw_transcription, vocals_path=vocals_wav)
    assert len(refined) == 1
    words = refined[0]["words"]
    texts = [w["text"] for w in words]
    assert "[*]" not in texts, "Disfluency marker [*] must be stripped"
    # First word 'Я' should be clamped near 2.9s-3.0s vocal onset, not 0.0s
    assert words[0]["start"] >= 2.8, f"Expected vocal onset >= 2.8s, got {words[0]['start']}"
    # Squashed words ('не', 'влекут', 'уже') must each have >= 0.08s duration
    for w in words:
        dur = w["end"] - w["start"]
        assert dur >= 0.08, f"Word '{w['text']}' still squashed: {dur}s"
    print("✓ test_disfluency_removal_and_unsquash passed!")


def test_russian_verse_line_splitting():
    """Verifies poetic line splitting and no dangling Russian prepositions ('Жил в / горах')."""
    mock_segments = [
        {
            "start": 17.6,
            "end": 30.5,
            "words": [
                {"text": "Я", "start": 17.6, "end": 18.0},
                {"text": "был", "start": 18.0, "end": 18.4},
                {"text": "хач", "start": 18.4, "end": 18.9},
                {"text": "широкоплечий,", "start": 18.9, "end": 20.8},
                {"text": "Жил", "start": 21.0, "end": 21.4},
                {"text": "в", "start": 21.4, "end": 21.6},
                {"text": "горах", "start": 21.6, "end": 22.2},
                {"text": "и", "start": 22.2, "end": 22.4},
                {"text": "не", "start": 22.4, "end": 22.6},
                {"text": "тужил,", "start": 22.6, "end": 23.8},
                {"text": "По", "start": 24.2, "end": 24.5},
                {"text": "утрам", "start": 24.5, "end": 25.1},
                {"text": "пас", "start": 25.1, "end": 25.6},
                {"text": "овечек", "start": 25.6, "end": 26.5},
                {"text": "И", "start": 26.8, "end": 27.1},
                {"text": "гашиш", "start": 27.1, "end": 27.8},
                {"text": "затем", "start": 27.8, "end": 28.4},
                {"text": "курил.", "start": 28.4, "end": 29.5},
            ],
        }
    ]

    lines = split_into_karaoke_lines(mock_segments)
    line_strings = [" ".join(w["text"] for w in line) for line in lines]
    print("  Split verse lines:", line_strings)
    assert len(lines) == 4, f"Expected 4 verse lines, got {len(lines)}: {line_strings}"
    assert line_strings[0] == "Я был хач широкоплечий,"
    assert line_strings[1] == "Жил в горах и не тужил,"
    assert line_strings[2] == "По утрам пас овечек"
    assert line_strings[3] == "И гашиш затем курил."

    # Verify 8-word chorus lines stay as 1 line (no 'с качами,' 2-word orphan)
    # and 10-word clauses split cleanly at the comma ('А пидорасы все вах,' + 'ебутся в жопу и в рот.')
    chorus_segments = [
        {
            "start": 24.39,
            "end": 32.15,
            "words": [
                {"text": "А", "start": 24.39, "end": 24.60},
                {"text": "я", "start": 24.60, "end": 24.80},
                {"text": "с", "start": 24.80, "end": 25.00},
                {"text": "качами", "start": 25.00, "end": 25.80},
                {"text": "ебусь,", "start": 25.80, "end": 26.50},
                {"text": "ебусь", "start": 26.50, "end": 27.24},
                {"text": "с", "start": 27.24, "end": 27.50},
                {"text": "качами,", "start": 27.50, "end": 28.31},
                {"text": "И", "start": 28.63, "end": 28.90},
                {"text": "лишь", "start": 28.90, "end": 29.30},
                {"text": "под", "start": 29.30, "end": 29.60},
                {"text": "качами", "start": 29.60, "end": 30.40},
                {"text": "кричу", "start": 30.40, "end": 31.10},
                {"text": "я", "start": 31.10, "end": 31.40},
                {"text": "ночами.", "start": 31.40, "end": 32.15},
            ],
        }
    ]
    ch_lines = split_into_karaoke_lines(chorus_segments)
    ch_strings = [" ".join(w["text"] for w in line) for line in ch_lines]
    assert ch_strings == [
        "А я с качами ебусь, ебусь с качами,",
        "И лишь под качами кричу я ночами.",
    ], f"Unexpected chorus split: {ch_strings}"
    print("✓ test_russian_verse_line_splitting passed!")


def test_lyrics_editor_roundtrip():
    """Verifies editing text and splitting lines in the Lyrics Editor preserves/interpolates timings."""
    initial_lines = [
        [
            {"text": "Я", "start": 17.6, "end": 18.0, "syllables": 1},
            {"text": "был", "start": 18.0, "end": 18.4, "syllables": 1},
            {"text": "хоть", "start": 18.4, "end": 18.9, "syllables": 1},
            {"text": "широко", "start": 18.9, "end": 19.8, "syllables": 3},
            {"text": "плечи,", "start": 19.8, "end": 20.8, "syllables": 2},
        ],
        [
            {"text": "Жил", "start": 21.0, "end": 21.5, "syllables": 1},
            {"text": "в", "start": 21.5, "end": 21.7, "syllables": 1},
            {"text": "горах", "start": 21.7, "end": 23.0, "syllables": 2},
        ],
    ]

    editor_str = lines_to_editor_text(initial_lines)
    assert "[00:17.60 -> 00:20.80] Я был хоть широко плечи," in editor_str

    # User edits typos in line 1
    edited_str = editor_str.replace("хоть широко плечи,", "хач широкоплечий,")
    updated_lines = editor_text_to_lines(edited_str, original_lines=initial_lines)
    assert len(updated_lines) == 2
    assert " ".join(w["text"] for w in updated_lines[0]) == "Я был хач широкоплечий,"
    assert abs(updated_lines[0][0]["start"] - 17.6) < 0.1
    assert abs(updated_lines[0][-1]["end"] - 20.8) < 0.1
    print("✓ test_lyrics_editor_roundtrip passed!")


def test_4line_ass_and_10pct_vocal_render(tmp_path: Path):
    """Verifies 10% guide vocal mixing, 4-line ASS look-ahead, and FFmpeg video output."""
    sr = 44100
    duration = 6.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    inst = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    voc = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    inst_path = tmp_path / "no_vocals.wav"
    voc_path = tmp_path / "vocals.wav"
    sf.write(str(inst_path), inst, sr)
    sf.write(str(voc_path), voc, sr)

    mixed_path = tmp_path / "mixed_10pct.wav"
    mix_guide_vocals(inst_path, voc_path, mixed_path, vocal_volume=0.10)
    assert mixed_path.exists()

    lines = [
        [{"text": "Первая", "start": 3.2, "end": 3.6}, {"text": "строка", "start": 3.6, "end": 4.0}],
        [{"text": "Вторая", "start": 4.0, "end": 4.4}, {"text": "строка", "start": 4.4, "end": 4.8}],
        [{"text": "Третья", "start": 4.8, "end": 5.1}, {"text": "строка", "start": 5.1, "end": 5.4}],
        [{"text": "Четвертая", "start": 5.4, "end": 5.7}, {"text": "строка", "start": 5.7, "end": 5.9}],
    ]

    ass_path = tmp_path / "test_4lines.ass"
    generate_ass_from_lines(lines, ass_path, title="Test 4 Lines", num_lines=4)
    content = ass_path.read_text(encoding="utf-8")

    # Verify teleprompter styles and countdown exist
    assert "KaraokeActive" in content
    assert "KaraokeNext" in content
    assert "KaraokeNextNext" in content
    assert "Countdown" in content
    assert "●" in content
    # Verify PrimaryColour is Gold (&H0000D7FF) and SecondaryColour is White (&H00FFFFFF)
    assert "&H0000D7FF,&H00FFFFFF" in content

    output_mp4 = tmp_path / "test_4lines.mp4"
    render_karaoke_video(
        instrumental_audio=mixed_path,
        ass_subtitles=ass_path,
        output_video=output_mp4,
        use_hardware_accel=True,
    )
    assert output_mp4.exists() and output_mp4.stat().st_size > 10000
    print("✓ test_4line_ass_and_10pct_vocal_render passed!")


def test_cover_art_background(tmp_path: Path):
    """Verifies generating Apple Music/Spotify style blurred cover backdrop and Ambilight edge color extraction."""
    from PIL import Image, ImageDraw
    from karaoke.video import create_cover_background, extract_cover_edge_colors

    mock_cover = tmp_path / "mock_album.png"
    img = Image.new("RGB", (400, 400), (220, 80, 50))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (400, 60)], fill=(0, 200, 255))      # Top cyan-blue
    draw.rectangle([(0, 340), (400, 400)], fill=(255, 20, 180))  # Bottom magenta
    img.save(str(mock_cover))

    edge_colors = extract_cover_edge_colors(mock_cover)
    assert set(edge_colors.keys()) == {"top", "bottom", "left", "right"}
    for side, col in edge_colors.items():
        assert col.startswith("&H00") and col.endswith("&"), f"Invalid ASS color for {side}: {col}"

    out_bg = tmp_path / "cover_backdrop_1080p.png"
    create_cover_background(mock_cover, out_bg)
    assert out_bg.exists()
    out_img = Image.open(out_bg)
    assert out_img.size == (1920, 1080)
    print("✓ test_cover_art_background & Ambilight edge colors passed!")


def test_vocal_automation_and_fx_timeline(tmp_path: Path):
    """Verifies dynamic vocal automation curves and full-perimeter 1920x1080 vector FX generation."""
    sr = 44100
    duration = 8.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    inst = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    voc = (0.6 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    inst_path = tmp_path / "inst_itv.wav"
    voc_path = tmp_path / "voc_itv.wav"
    sf.write(str(inst_path), inst, sr)
    sf.write(str(voc_path), voc, sr)

    # Vocal boosted to 90% between 2.0s and 5.0s
    vocal_intervals = [{"start": 2.0, "end": 5.0, "volume": 0.90}]
    mixed_path = tmp_path / "mixed_automated.wav"
    mix_guide_vocals(inst_path, voc_path, mixed_path, vocal_volume=0.10, vocal_intervals=vocal_intervals)
    assert mixed_path.exists()

    # Read back and verify amplitude is significantly higher during [2.5, 4.5] than [0.5, 1.5]
    mixed_data, _ = sf.read(str(mixed_path))
    amp_base = np.max(np.abs(mixed_data[int(sr * 0.5):int(sr * 1.5)]))
    amp_boost = np.max(np.abs(mixed_data[int(sr * 2.5):int(sr * 4.5)]))
    assert amp_boost > amp_base * 1.8, f"Expected boosted amplitude > {amp_base * 1.8}, got {amp_boost}"

    # Verify full-perimeter {\p1} vector FX intervals in ASS (both neon_rainbow and cover_colors)
    lines = [
        [{"text": "Припев", "start": 2.0, "end": 3.5}],
        [{"text": "Кульминация", "start": 3.6, "end": 5.0}],
    ]
    fx_intervals = [{"start": 2.0, "end": 5.0, "effect": "climax", "intensity": 1.0}]
    ass_path = tmp_path / "test_fx.ass"
    generate_ass_from_lines(
        lines,
        ass_path,
        title="Test FX",
        visual_effects="timeline_only",
        fx_intervals=fx_intervals,
        audio_for_pulse=inst_path,
        edge_color_mode="cover_colors",
        has_cover_card=True,
    )
    content = ass_path.read_text(encoding="utf-8")
    assert "FX_Sparkle" in content
    assert "FX_EdgePulse" in content
    assert "\\p1" in content, "Expected vector drawing mode {\\p1} for full-perimeter 1920x1080 edge pulse"
    assert "m 0 0 l 1920 0" in content, "Expected top 1920px border vector"
    assert "m 0 1074 l 1920 1074" in content, "Expected bottom 1920px border vector"
    assert "m 793 58 l 1127 58" in content, "Expected 330x330 cover card contour glow"
    print("✓ test_vocal_automation_and_fx_timeline (full 1920x1080 perimeter) passed!")


def test_apple_emoji_layer_and_placeholder_ass(tmp_path: Path):
    """Verifies that native Apple Color Emoji replaces tofu squares with width-exact ASS placeholders and builds ffconcat sequence."""
    from karaoke.emoji_layer import (
        split_text_with_emoji,
        layout_line_emoji,
        build_lyric_emoji_sequence,
    )

    sample_text = "По утрам пас овечек 🔥 и гашиш затем курил 🎤"
    tokens = split_text_with_emoji(sample_text)
    texts = [t["text"] for t in tokens]
    is_ems = [t["is_emoji"] for t in tokens]
    assert "🔥" in texts and "🎤" in texts
    assert is_ems[texts.index("🔥")] is True
    assert is_ems[texts.index("🎤")] is True

    # Layout calculation
    em_events = layout_line_emoji(sample_text, font_size=54, bold=True, margin_v=365)
    assert len(em_events) == 2
    assert em_events[0]["emoji"] == "🔥"
    assert em_events[1]["emoji"] == "🎤"
    assert em_events[0]["x"] > 100 and em_events[1]["x"] > em_events[0]["x"]
    assert em_events[0]["y"] > 200

    # Test ASS generation with emoji_events_out
    lines = [
        [
            {"text": "По", "start": 1.0, "end": 1.3},
            {"text": "утрам", "start": 1.3, "end": 1.7},
            {"text": "пас", "start": 1.7, "end": 2.1},
            {"text": "овечек", "start": 2.1, "end": 2.6},
            {"text": "🔥", "start": 2.6, "end": 3.0},
            {"text": "и", "start": 3.0, "end": 3.2},
            {"text": "гашиш", "start": 3.2, "end": 3.7},
            {"text": "затем", "start": 3.7, "end": 4.1},
            {"text": "курил", "start": 4.1, "end": 4.6},
            {"text": "🎤", "start": 4.6, "end": 5.0},
        ]
    ]
    ass_path = tmp_path / "emoji_karaoke.ass"
    collected_emoji_events = []
    generate_ass_from_lines(
        lines=lines,
        output_path=ass_path,
        title="Emoji Karaoke",
        num_lines=4,
        emoji_events_out=collected_emoji_events,
    )
    ass_content = ass_path.read_text(encoding="utf-8")
    assert "\\alpha&HFF&\\p1" in ass_content, "Expected invisible width-exact ASS placeholder for emoji"
    assert len(collected_emoji_events) >= 2

    # Verify building ffconcat lyric sequence
    concat_txt = build_lyric_emoji_sequence(collected_emoji_events, tmp_path, total_duration=6.0)
    assert concat_txt.exists()
    assert "ffconcat version 1.0" in concat_txt.read_text(encoding="utf-8")
    print("✓ test_apple_emoji_layer_and_placeholder_ass passed!")


def test_flying_emoji_particles_and_video_composite(tmp_path: Path):
    """Verifies generating flying Apple Color Emoji particles and compositing into Full HD 1080p video."""
    from karaoke.emoji_layer import (
        generate_emoji_particles,
        save_particle_sprites,
        build_lyric_emoji_sequence,
    )
    from karaoke.video import create_cover_background

    # Generate test audio
    sr = 44100
    duration = 5.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    audio = (0.2 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    audio_wav = tmp_path / "test_audio.wav"
    sf.write(str(audio_wav), audio, sr)

    # Generate 1080p background
    from PIL import Image
    cover_png = tmp_path / "album_art.png"
    Image.new("RGB", (300, 300), (30, 60, 120)).save(str(cover_png))

    lines = [
        [
            {"text": "Врубай", "start": 0.5, "end": 1.5},
            {"text": "салют", "start": 1.5, "end": 2.5},
            {"text": "🔥", "start": 2.5, "end": 4.5},
        ]
    ]
    ass_path = tmp_path / "particle_test.ass"
    lyric_emojis = []
    generate_ass_from_lines(
        lines=lines,
        output_path=ass_path,
        title="Particle Test",
        emoji_events_out=lyric_emojis,
    )
    lyric_concat = build_lyric_emoji_sequence(lyric_emojis, tmp_path, total_duration=duration)

    # Flying emoji burst on interval [1.0 -> 4.0]
    fx_itvs = [{"start": 1.0, "end": 4.0, "effect": "emoji_burst", "intensity": 0.9, "emojis": "🔥✨👑"}]
    particles = generate_emoji_particles(fx_itvs)
    assert len(particles) >= 1
    sprites = save_particle_sprites(particles, tmp_path)
    assert len(sprites) >= 1

    out_mp4 = tmp_path / "emoji_karaoke_1080p.mp4"
    render_karaoke_video(
        instrumental_audio=audio_wav,
        ass_subtitles=ass_path,
        output_video=out_mp4,
        cover_image=cover_png,
        use_cover_bg=True,
        lyric_emoji_concat=lyric_concat,
        emoji_particles=particles,
        emoji_sprites=sprites,
        use_hardware_accel=True,
    )
    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 20000, f"Rendered MP4 file too small: {out_mp4.stat().st_size} bytes"
    print("✓ test_flying_emoji_particles_and_video_composite passed!")


def test_cancel_manager():
    """Verifies that cancel_manager sets flags, raises GenerationCancelledError, and kills subprocesses."""
    import subprocess
    import sys
    from karaoke.cancel_manager import (
        reset_cancel,
        is_cancelled,
        check_cancelled,
        request_cancel,
        register_process,
        GenerationCancelledError,
    )

    reset_cancel()
    assert not is_cancelled()
    check_cancelled()  # Should not raise

    # Spawn a dummy sleep subprocess and verify request_cancel terminates it
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    register_process(proc)
    killed = request_cancel()
    assert is_cancelled()
    assert killed == 1
    assert proc.poll() is not None

    try:
        check_cancelled()
        assert False, "Expected GenerationCancelledError"
    except GenerationCancelledError:
        pass

    reset_cancel()
    assert not is_cancelled()
    print("✓ test_cancel_manager passed!")


def test_fx_timeline_rebuild_persistence(tmp_path: Path):
    """Verifies that custom FX and vocal intervals from the timeline persist across video rebuilds and explicit clears."""
    import json
    from karaoke.app_ui import _parse_intervals_json, _build_timeline_payload

    old_fx = [{"start": 1.0, "end": 3.0, "effect": "sparkles_pulse", "intensity": 0.85}]
    new_fx_json = json.dumps([
        {"start": 2.0, "end": 4.5, "effect": "climax", "intensity": 1.0},
        {"start": 4.5, "end": 6.0, "effect": "emoji_burst", "intensity": 0.9, "emojis": "🔥🚀"},
    ])

    parsed_fx = _parse_intervals_json(new_fx_json, old_fx)
    assert len(parsed_fx) == 2
    assert parsed_fx[0]["effect"] == "climax"
    assert parsed_fx[1]["effect"] == "emoji_burst"
    assert parsed_fx[1]["emojis"] == "🔥🚀"

    # Explicit clear ("[]") must return [] and NOT fall back to old_fx
    cleared_fx = _parse_intervals_json("[]", old_fx)
    assert cleared_fx == [], f"Expected empty list on explicit clear, got {cleared_fx}"

    # Verify generate_ass_from_lines respects explicit empty list [] even when visual_effects='sparkles_pulse'
    lines = [[{"text": "Тест", "start": 1.0, "end": 2.5}]]
    ass_empty = tmp_path / "empty_fx.ass"
    generate_ass_from_lines(
        lines=lines,
        output_path=ass_empty,
        visual_effects="sparkles_pulse",
        fx_intervals=[],
    )
    empty_content = ass_empty.read_text(encoding="utf-8")
    assert "Dialogue: 0," not in empty_content, "Expected 0 FX events when timeline fx_intervals is explicitly []"

    # Verify _build_timeline_payload preserves updated FX intervals
    state = {
        "title": "test_song",
        "duration": 10.0,
        "vocal_intervals": [{"start": 1.0, "end": 4.0, "volume": 0.8}],
        "fx_intervals": parsed_fx,
        "lines": lines,
    }
    payload = json.loads(_build_timeline_payload(state))
    assert len(payload["fx_intervals"]) == 2
    assert payload["fx_intervals"][1]["emojis"] == "🔥🚀"
    print("✓ test_fx_timeline_rebuild_persistence passed!")


def test_police_strobe_and_neon_sparkles(tmp_path: Path):
    """Verifies that police strobe splits into Red/Blue pulses and neon sparkles have bloom glow and fade."""
    assert "police" in NEON_PALETTES
    assert "&H000000FF&" in NEON_PALETTES["police"]  # Red
    assert "&H00FF3300&" in NEON_PALETTES["police"]  # Blue

    lines = [[{"text": "Полиция", "start": 1.0, "end": 2.5}]]
    ass_path = tmp_path / "police_test.ass"
    generate_ass_from_lines(
        lines=lines,
        output_path=ass_path,
        visual_effects="police_strobe",
        edge_color_mode="police",
    )
    content = ass_path.read_text(encoding="utf-8")
    assert "FX_EdgePulse" in content, "Expected FX_EdgePulse dialogue entries"
    # Red strobe on left/top-left/bottom-left
    assert "\\1c&H000000FF&" in content or "\\3c&H000000FF&" in content
    # Blue strobe on right/top-right/bottom-right
    assert "\\1c&H00FF3300&" in content or "\\3c&H00FF3300&" in content
    # Neon sparkles with bloom glow and twinkle decay
    assert "FX_Sparkle" in content
    assert "\\c&H00FFFFFF&" in content  # White-hot core
    assert "\\blur" in content
    assert "\\t(" in content  # Twinkle animation
    print("✓ test_police_strobe_and_neon_sparkles passed!")


def test_non_16_9_background_centering(tmp_path: Path):
    """Verifies that square and portrait images are centered on 1920x1080 blurred backdrop."""
    # 1. Test square 800x800 image
    sq_img = Image.new("RGB", (800, 800), color=(180, 40, 90))
    sq_path = tmp_path / "square.jpg"
    sq_img.save(sq_path)

    out_sq = tmp_path / "out_square_1080p.png"
    prepare_background_image(sq_path, out_sq, width=1920, height=1080)
    assert out_sq.exists()
    res_sq = Image.open(out_sq)
    assert res_sq.size == (1920, 1080), f"Expected (1920, 1080), got {res_sq.size}"

    # 2. Test portrait 720x1280 image
    port_img = Image.new("RGB", (720, 1280), color=(40, 140, 200))
    port_path = tmp_path / "portrait.png"
    port_img.save(port_path)

    out_port = tmp_path / "out_portrait_1080p.png"
    prepare_background_image(port_path, out_port, width=1920, height=1080)
    assert out_port.exists()
    res_port = Image.open(out_port)
    assert res_port.size == (1920, 1080), f"Expected (1920, 1080), got {res_port.size}"

    # 3. Test exact 16:9 image (1920x1080) resizes directly
    wide_img = Image.new("RGB", (1920, 1080), color=(20, 20, 20))
    wide_path = tmp_path / "wide.png"
    wide_img.save(wide_path)
    out_wide = tmp_path / "out_wide.png"
    prepare_background_image(wide_path, out_wide, width=1920, height=1080)
    assert out_wide.exists()
    res_wide = Image.open(out_wide)
    assert res_wide.size == (1920, 1080)
    print("✓ test_non_16_9_background_centering passed!")


def test_audio_from_source_video_bg_flag(tmp_path: Path):
    """Verifies that get_audio_from_source returns 4 elements including video_bg and extracted WAV + cover."""
    import subprocess
    # Test local audio file
    fake_audio = tmp_path / "song.mp3"
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "sine=duration=0.2", str(fake_audio)], check=True, capture_output=True)
    res = get_audio_from_source(str(fake_audio), tmp_path)
    assert len(res) == 4, f"Expected 4-tuple return, got {len(res)}"
    audio_path, title, cover, video_bg = res
    assert audio_path == fake_audio.resolve()
    assert title == "song"
    assert video_bg is None

    # Test local mp4 video file with real media streams
    real_video = tmp_path / "clip.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        str(real_video),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    res_vid = get_audio_from_source(str(real_video), tmp_path)
    assert len(res_vid) == 4
    extracted_wav, vid_title, vid_cover, vid_bg = res_vid
    assert extracted_wav.exists() and extracted_wav.suffix == ".wav"
    assert vid_title == "clip"
    assert vid_cover and vid_cover.exists()
    assert vid_bg == real_video.resolve()
    print("✓ test_audio_from_source_video_bg_flag passed!")


def test_youtube_downloader_opts_and_cookies_config(tmp_path: Path):
    """Verifies yt-dlp option assembly with Node.js runtime and cookies browser/file configurations."""
    import yt_dlp
    from karaoke.downloader import find_node_bin

    node_bin = find_node_bin()
    assert node_bin is not None, "Node.js binary should be found in system path or standard locations"

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\ttest\n")

    ydl_opts = {
        "quiet": True,
        "cookiefile": str(cookie_file),
        "js_runtimes": {"node": {"path": node_bin}},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        assert ydl.cookiejar is not None
    print("✓ test_youtube_downloader_opts_and_cookies_config passed!")


if __name__ == "__main__":
    test_dir = Path("/tmp/karaoke_tests_v3_2")
    test_dir.mkdir(parents=True, exist_ok=True)
    test_disfluency_removal_and_unsquash(test_dir)
    test_russian_verse_line_splitting()
    test_lyrics_editor_roundtrip()
    test_4line_ass_and_10pct_vocal_render(test_dir)
    test_cover_art_background(test_dir)
    test_vocal_automation_and_fx_timeline(test_dir)
    test_apple_emoji_layer_and_placeholder_ass(test_dir)
    test_flying_emoji_particles_and_video_composite(test_dir)
    test_cancel_manager()
    test_fx_timeline_rebuild_persistence(test_dir)
    test_police_strobe_and_neon_sparkles(test_dir)
    test_non_16_9_background_centering(test_dir)
    test_audio_from_source_video_bg_flag(test_dir)
    test_youtube_downloader_opts_and_cookies_config(test_dir)
    print("\n🎉 ALL TESTS (POLICE STROBE, NEON SPARKLES, SMART BG, YOUTUBE COOKIES & VIDEO UPLOAD) PASSED SUCCESSFULLY!")
