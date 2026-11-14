import tempfile
import re
from pathlib import Path
from karaoke.ass_writer import (
    generate_ass_from_lines,
    _generate_police_migrating_dots_events,
    NEON_PALETTES,
    HIGHLIGHT_COLORS,
    split_word_into_syllables,
    allocate_syllable_durations,
    build_karaoke_line_tags,
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


def test_split_word_into_syllables_and_invariants():
    test_cases = [
        ("пополняет", ["по", "пол", "ня", "ет"]),
        ("баланс,", ["ба", "ланс,"]),
        ("стрипухе", ["стри", "пу", "хе"]),
        ("делают", ["де", "ла", "ют"]),
        ("сиськи", ["сись", "ки"]),
        ("подъезд", ["подъ", "езд"]),
        ("ванна", ["ван", "на"]),
        ("кто-то", ["кто", "-то"]),
        ("в", ["в"]),
        ("с", ["с"]),
        ("Я", ["Я"]),
        ("был", ["был"]),
        ("house", ["house"]),
        ("bounce", ["bounce"]),
        ("superstar", ["su", "per", "star"]),
        ("baby", ["ba", "by"]),
    ]

    for word, expected in test_cases:
        sylls = split_word_into_syllables(word)
        assert "".join(sylls) == word, f"Invariant broken: {''.join(sylls)} != {word}"
        assert sylls == expected, f"Expected {expected} for '{word}', got {sylls}"


def test_allocate_syllable_durations():
    # Various syllable lists and durations
    cases = [
        (["по", "пол", "ня", "ет"], 140),
        (["ба", "ланс,"], 60),
        (["стри", "пу", "хе"], 70),
        (["де", "ла", "ют"], 90),
        (["су", "пер"], 8),
        (["о", "дин"], 3),
        (["дом"], 45),
    ]

    for sylls, dur in cases:
        durs = allocate_syllable_durations(sylls, dur)
        assert len(durs) == len(sylls)
        assert sum(durs) == dur, f"Sum {sum(durs)} != {dur} for {sylls}"
        assert all(d >= 1 for d in durs), f"Found non-positive duration in {durs}"

    # Stretched ending words allocate extended musical hold to final syllable
    stretched_cases = [
        (["боль", "ша", "я"], 106),
        (["по", "и", "гра", "ю"], 158),
        (["му", "жи", "ком"], 165),
    ]
    for sylls, dur in stretched_cases:
        durs = allocate_syllable_durations(sylls, dur)
        assert sum(durs) == dur
        assert durs[-1] > durs[0], f"Sustained hold was not allocated to final syllable in {sylls}: {durs}"


def test_build_karaoke_line_tags_syllables():
    line_words = [
        {"text": "Лишь", "start": 1.0, "end": 1.2},
        {"text": "бы", "start": 1.2, "end": 1.4},
        {"text": "баланс", "start": 1.4, "end": 2.0},
        {"text": "пополняли", "start": 2.0, "end": 3.4},
    ]

    tag_str = build_karaoke_line_tags(line_words, display_start=0.5)

    # Duration for "баланс" is 0.6s -> 60cs, split into 2 syllables: "ба", "ланс"
    # Duration for "пополняли" is 1.4s -> 140cs, split into 4 syllables: "по", "пол", "ня", "ли"
    assert "{\\kf" in tag_str
    # Syllables should appear sequentially inside tags
    assert "{\\kf" in tag_str and "ба" in tag_str and "ланс" in tag_str
    assert "по" in tag_str and "пол" in tag_str and "ня" in tag_str and "ли" in tag_str

    # Extract all \kf durations and check total duration matches words
    kf_durations = [int(m) for m in re.findall(r"\\kf(\d+)", tag_str)]
    # 20 + 20 + 60 + 140 = 240 cs
    assert sum(kf_durations) == 240
