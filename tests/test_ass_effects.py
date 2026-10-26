import tempfile
from pathlib import Path
from karaoke.ass_writer import (
    generate_ass_from_lines,
    _generate_police_migrating_dots_events,
    NEON_PALETTES,
    HIGHLIGHT_COLORS,
)


def test_green_neon_palette_and_highlight():
    assert "green_neon" in NEON_PALETTES
    assert len(NEON_PALETTES["green_neon"]) >= 4
    assert "green_neon" in HIGHLIGHT_COLORS
    assert "emerald" in HIGHLIGHT_COLORS


def test_police_migrating_dots_events():
    events = _generate_police_migrating_dots_events(0.0, 2.0, intensity=1.0)
    assert len(events) > 0
    # Check that events contain \move and neon police colors
    assert any("\\move(" in ev for ev in events)
    assert any("&H000000FF&" in ev for ev in events)  # Police red
    assert any("&H00FF3300&" in ev for ev in events)  # Police blue


def test_generate_ass_with_police_strobe():
    sample_lines = [[
        {"text": "Тест", "start": 1.0, "end": 2.0, "syllables": 1},
        {"text": "мигалки", "start": 2.0, "end": 3.0, "syllables": 2},
    ]]
    with tempfile.TemporaryDirectory() as td:
        out_ass = Path(td) / "test.ass"
        generate_ass_from_lines(
            lines=sample_lines,
            output_path=out_ass,
            title="Test Police",
            visual_effects="police_strobe",
            highlight_color="green_neon",
        )
        assert out_ass.exists()
        content = out_ass.read_text(encoding="utf-8")
        assert "FX_BeaconDot" in content
        assert "FX_EdgePulse" in content
