import copy

import pytest

from karaoke.aligner import (
    TimingAlignmentError, align_words_to_reference_lines, editor_text_to_lines,
    lines_to_editor_text, split_into_karaoke_lines, validate_karaoke_lines,
    split_long_editor_lines, split_single_long_line, realign_editor_timings,
    sanitize_reference_lyrics, refine_unaligned_vocal_slices,
)
from karaoke.ass_writer import generate_ass_from_lines


def words(text, start, step=0.3):
    return [{"text": token, "start": round(start + i * step, 3),
             "end": round(start + (i + 1) * step, 3)} for i, token in enumerate(text.split())]


def test_repeated_choruses_keep_their_own_acoustic_anchors():
    # A recognizer merges two syllables into one word on every repetition.
    recognized = []
    for start in (96.4, 102.0, 107.6, 113.2):
        recognized += words("Бань парилка ёблей горилка водка и пивас полный расколбас", start)
    reference = ["Банька парилка", "Ёбля и горилка", "Водка и пивас", "Полный расколбас"] * 4
    aligned = align_words_to_reference_lines(recognized, reference)
    assert len(aligned) == 16
    assert [aligned[i][0]["start"] for i in (0, 4, 8, 12)] == [96.4, 102.0, 107.6, 113.2]
    validate_karaoke_lines(aligned)


def test_extra_reference_repeats_are_not_squeezed_before_next_anchor():
    chorus = "Водка и пивас полный расколбас"
    recognized = words(chorus, 110) + words("Дальше новый куплет", 112)
    reference = [chorus] * 4 + ["Дальше новый куплет"]

    # When strict_repeats is True ("как сейчас"): mismatched repeats throw TimingAlignmentError and fallback to Whisper
    with pytest.raises(TimingAlignmentError):
        align_words_to_reference_lines(recognized, reference, strict_repeats=True)
    warnings = []
    lines_strict = split_into_karaoke_lines([{"words": recognized}],
                                    reference_lyrics="\n".join(reference), warnings_out=warnings, strict_repeats=True)
    assert warnings
    assert [w["text"] for line in lines_strict for w in line] == [w["text"] for w in recognized]
    validate_karaoke_lines(lines_strict)

    # When strict_repeats is False (default, "как было"): reference lyrics are NEVER discarded
    lines_classic = split_into_karaoke_lines([{"words": recognized}],
                                    reference_lyrics="\n".join(reference), strict_repeats=False)
    assert len(lines_classic) == len(reference)
    validate_karaoke_lines(lines_classic)


def test_short_editor_windows_do_not_grow_into_next_line():
    lines = editor_text_to_lines(
        "[01:56.08 -> 01:56.44] Водка и пивас\n"
        "[01:56.44 -> 01:56.80] Полный расколбас"
    )
    assert lines[0][-1]["end"] == 116.44
    assert lines[1][-1]["end"] == 116.80
    validate_karaoke_lines(lines)


def test_unchanged_repeated_rows_are_stable_across_rebuilds():
    original = [words("Снова и снова", 10, 0.1), words("Снова и снова", 10.3, 0.1)]
    lines = copy.deepcopy(original)
    for _ in range(4):
        lines = editor_text_to_lines(lines_to_editor_text(lines), original_lines=lines)
    assert [[(w["start"], w["end"]) for w in row] for row in lines] == [
        [(w["start"], w["end"]) for w in row] for row in original]


def test_manually_moved_repetition_uses_original_row_not_neighbor():
    original = [words("Снова и снова", 10, 0.1), words("Снова и снова", 12, 0.2)]
    lines = editor_text_to_lines(
        "[00:11.00 -> 00:11.30] Снова и снова\n[00:12.00 -> 00:12.60] Снова и снова", original)
    assert lines[0][0]["start"] == 11
    assert lines[0][-1]["end"] == 11.3
    validate_karaoke_lines(lines)


@pytest.mark.parametrize("editor", [
    "[01:59.09 -> 01:57.06] Водка и пивас",
    "[01:59.09 -> 01:59.54] Водка и пивас\n[01:57.26 -> 01:58.46] Полный расколбас",
])
def test_invalid_editor_timestamps_are_rejected(editor):
    with pytest.raises(TimingAlignmentError):
        editor_text_to_lines(editor)


def test_subtitles_reject_backwards_words_before_writing(tmp_path):
    output = tmp_path / "invalid.ass"
    malformed = [[{"text": "Водка", "start": 119.09, "end": 119.23},
                  {"text": "и", "start": 116.46, "end": 116.60}]]
    with pytest.raises(TimingAlignmentError):
        generate_ass_from_lines(malformed, output)
    assert not output.exists()


def test_enter_split_stays_inside_original_row():
    original = [words("Раз два три четыре", 10, 0.2), words("Следующая строка", 10.8, 0.2)]
    result = editor_text_to_lines(
        "[00:10.00 -> 00:10.80] Раз два\nтри четыре\n[00:10.80 -> 00:11.20] Следующая строка",
        original,
    )
    assert result[1][-1]["end"] == 10.8
    validate_karaoke_lines(result)


def test_recognition_segment_boundary_overlap_is_reconciled_without_mutation():
    segments = [
        {'words': [{'text': 'Предыдущая', 'start': 148.7, 'end': 149.25}]},
        {'words': [{'text': 'Трахнемся', 'start': 149.13, 'end': 149.9}]},
    ]
    original = copy.deepcopy(segments)
    lines = split_into_karaoke_lines(segments)
    validate_karaoke_lines(lines)
    flat = [word for line in lines for word in line]
    assert flat[0]['end'] == flat[1]['start'] == 149.19
    assert flat[0]['start'] == 148.7 and flat[1]['end'] == 149.9
    assert segments == original


def test_recognition_boundary_repair_does_not_hide_reversed_chorus():
    segments = [{'words': [
        {'text': 'Водка', 'start': 119.09, 'end': 119.23},
        {'text': 'и', 'start': 116.46, 'end': 116.6},
    ]}]
    with pytest.raises(TimingAlignmentError):
        validate_karaoke_lines(split_into_karaoke_lines(segments))


def test_split_long_editor_lines_leaves_short_lines_intact():
    short_line = words("Привет как дела", 10.0, 0.3)
    lines = [short_line]
    result = split_long_editor_lines(lines, max_chars=38, max_words=8)
    assert len(result) == 1
    assert [w["text"] for w in result[0]] == ["Привет", "как", "дела"]


def test_split_long_editor_lines_splits_and_avoids_dangling_prepositions():
    long_line = words("Мы летим над облаками и не знаем что нас ждет впереди", 10.0, 0.3)
    lines = [long_line]
    result = split_long_editor_lines(lines, max_chars=30, max_words=6)
    assert len(result) > 1
    from karaoke.aligner import RUSSIAN_NO_DANGLE
    for subline in result:
        last_word_bare = subline[-1]["text"].strip().lower()
        assert last_word_bare not in RUSSIAN_NO_DANGLE
    flat = [w for subline in result for w in subline]
    assert [w["text"] for w in flat] == [w["text"] for w in long_line]
    assert flat[0]["start"] == long_line[0]["start"]
    assert flat[-1]["end"] == long_line[-1]["end"]
    validate_karaoke_lines(result)


def test_reference_lyrics_with_dashes_and_whisper_substitutions_aligns_cleanly():
    # User provides clean lyrics with dashes and rapid lines
    reference = [
        "От Урала до Байкала — лишнего мне мало",
        "Транш из двух столиц,",
        "Ещё айс-блонд...",
        "Льётся спритц,",
        "Как Блиц — Без границ.",
    ]
    # Recognizer produced garbled/mumbled words with fewer tokens
    recognized = words("От Урала до Байкала лишнего мне мало", 10.0, 0.3)
    recognized += words("Транш столетий я из блога", 12.5, 0.45)
    recognized += words("Льется как блиц без границ", 14.5, 0.4)

    aligned = align_words_to_reference_lines(recognized, reference)
    assert len(aligned) == len(reference)
    # Check that punctuation is attached and all lines are strictly monotonic
    assert "Байкала —" in [w["text"] for w in aligned[0]]
    validate_karaoke_lines(aligned)


def test_find_vocal_offset_clamps_before_silence():
    from karaoke.aligner import find_vocal_offset
    import numpy as np
    # 10s audio envelope: 0-3s active singing, 3-10s silent
    hop_s = 0.01
    rms = np.zeros(1000, dtype=np.float32)
    rms[0:300] = 0.1  # active vocal
    rms[300:1000] = 0.0001  # silence
    offset = find_vocal_offset(rms, hop_s, search_start=1.0, search_end=9.5)
    # Offset should clamp near 3.0s (+ 0.15s buffer), not stretch to 9.5s
    assert 3.0 <= offset <= 3.3


def test_long_instrumental_gap_does_not_stretch_interpolated_words():
    # Gap between 12.0s and 45.0s (33 seconds of silence/solo)
    recognized = [
        {"text": "начало", "start": 10.0, "end": 12.0},
        {"text": "конец", "start": 45.0, "end": 47.0}
    ]
    reference = [
        "начало",
        "пропущенная строка текста",
        "конец"
    ]
    aligned = align_words_to_reference_lines(recognized, reference)
    validate_karaoke_lines(aligned)
    # The interpolated middle line must not stretch across all 33 seconds
    mid_line = aligned[1]
    mid_dur = mid_line[-1]["end"] - mid_line[0]["start"]
    assert mid_dur < 10.0  # bounded by natural singing duration, not 33s


def test_instrumental_intro_preserved_when_reference_lyrics_provided(tmp_path):
    from karaoke.aligner import find_first_vocal_onset, refine_word_timestamps
    import numpy as np
    import soundfile as sf

    sr = 16000
    # 15s instrumental intro (silence in vocals stem) + 5s active vocal
    audio = np.zeros(sr * 20, dtype=np.float32)
    audio[sr * 15:] = 0.2
    vocals_file = tmp_path / "vocals.wav"
    sf.write(str(vocals_file), audio, sr)

    # 1. find_first_vocal_onset detects intro
    from karaoke.aligner import compute_vocal_rms_envelope
    rms, hop_s = compute_vocal_rms_envelope(vocals_file)
    first_onset = find_first_vocal_onset(rms, hop_s)
    assert first_onset is not None
    assert 14.8 <= first_onset <= 15.1

    # 2. refine_word_timestamps drops Whisper hallucinations in intro
    fake_whisper = {
        "segments": [
            # Hallucinated tokens during instrumental intro
            {"start": 0.0, "end": 1.2, "text": "какой-то шум", "words": [{"text": "какой-то", "start": 0.0, "end": 0.6}, {"text": "шум", "start": 0.6, "end": 1.2}]},
            {"start": 5.0, "end": 6.0, "text": "галлюцинация", "words": [{"text": "галлюцинация", "start": 5.0, "end": 6.0}]},
            # Real singing starting at 15.0s
            {"start": 14.5, "end": 18.0, "text": "настоящий куплет", "words": [{"text": "настоящий", "start": 14.5, "end": 16.0}, {"text": "куплет", "start": 16.0, "end": 18.0}]},
        ]
    }
    refined = refine_word_timestamps(fake_whisper, vocals_path=vocals_file)
    # The hallucinated segments during 0..14.8s must be purged
    assert len(refined) == 1
    assert refined[0]["words"][0]["text"] == "настоящий"
    assert refined[0]["words"][0]["start"] >= 14.8

    # 3. align_words_to_reference_lines preserves intro even if reference lyrics have extra lines
    reference = [
        "Вступительная строка из текста песни",
        "Настоящий куплет",
    ]
    recognized = [{"text": "настоящий", "start": 15.0, "end": 16.0}, {"text": "куплет", "start": 16.0, "end": 18.0}]
    aligned = align_words_to_reference_lines(recognized, reference, vocals_path=vocals_file)
    validate_karaoke_lines(aligned)
    # First line must NOT start at 0.0s during the intro
    assert aligned[0][0]["start"] >= 14.8


def test_repeated_chorus_places_omitted_repeats_into_audio_gap():
    """
    When a chorus repeats the same line 4 times (e.g. 23.2s..39.4s) and Whisper only outputs
    the 1st repetition (23.2s..27.2s) before jumping to the next verse at 39.4s (which also starts with 'Я'),
    the 3 omitted repetitions must be placed evenly inside the 27.2s..39.4s gap rather than squished before 24s.
    """
    recognized = (
        words("Я пришел домой и опять лёг спать", 19.2, 0.55)
        + words("Но я сегодня забыл повеситься", 23.23, 0.79)
        + words("Я сходил в магазин и купил там пиво", 39.44, 0.46)
    )
    reference = [
        "Я пришел домой и опять лёг спать",
        "Но я сегодня забыл повеситься",
        "Я сегодня забыл повеситься",
        "Я сегодня забыл повеситься",
        "Я сегодня забыл повеситься",
        "Я сходил в магазин и купил там пиво",
    ]
    aligned = align_words_to_reference_lines(recognized, reference)
    validate_karaoke_lines(aligned)
    # Line 1 (first chorus line) matches 23.23..27.18
    assert 23.0 <= aligned[1][0]["start"] <= 23.5
    assert 26.8 <= aligned[1][-1]["end"] <= 27.5
    # Lines 2, 3, 4 (omitted chorus repeats) fill the 27.18..39.44 gap (~4s each), NOT squished < 0.5s
    for idx in (2, 3, 4):
        dur = aligned[idx][-1]["end"] - aligned[idx][0]["start"]
        assert dur >= 3.0, f"Chorus repeat {idx} was squished to {dur:.2f}s"
    # Line 5 (next verse) starts at 39.44
    assert aligned[5][0]["start"] >= 39.0


def test_enter_split_with_subsequent_gap_uses_acoustic_boundary():
    """
    When user splits a line with Enter and there is a pause before the next line,
    the split lines stay strictly within the original line's acoustic boundaries
    and do not bleed into the instrumental gap.
    """
    original = [
        words("Раз два три четыре", 10.0, 0.4),  # 10.0 .. 11.6
        words("Следующая строка", 13.0, 0.5),   # 13.0 .. 14.0 (1.4s gap)
    ]
    editor = (
        "[00:10.00 -> 00:11.60] Раз два\n"
        "три четыре\n"
        "[00:13.00 -> 00:14.00] Следующая строка"
    )
    result = editor_text_to_lines(editor, original)
    validate_karaoke_lines(result)
    assert len(result) == 3
    assert result[0][0]["start"] == 10.0
    assert result[0][-1]["end"] == 10.8
    assert result[1][0]["start"] == 10.8
    assert result[1][-1]["end"] == 11.6
    assert result[2][0]["start"] == 13.0


def test_split_with_duplicate_timestamps_resolves_cleanly():
    """
    When user splits a line keeping or copying the same timestamp onto both parts,
    it should resolve into strictly monotonic split lines instead of failing.
    """
    original = [
        words("Раз два три четыре", 10.0, 0.4),
        words("Следующая строка", 13.0, 0.5),
    ]
    editor = (
        "[00:10.00 -> 00:11.60] Раз два\n"
        "[00:10.00 -> 00:11.60] три четыре\n"
        "[00:13.00 -> 00:14.00] Следующая строка"
    )
    result = editor_text_to_lines(editor, original)
    validate_karaoke_lines(result)
    assert len(result) == 3
    assert result[0][-1]["end"] <= result[1][0]["start"] + 0.01
    assert result[1][-1]["end"] <= 11.65


def test_hh_mm_ss_and_various_timestamp_formats():
    """
    Tests parsing of [HH:MM:SS->HH:MM:SS], comma decimals, and different arrows.
    """
    editor = (
        "[00:00:10->00:00:15] Первая строка песни\n"
        "[00:00:16,50 --> 00:00:20,00] Вторая строка песни\n"
        "[00:01:00 — 00:01:05] Третья строка песни"
    )
    result = editor_text_to_lines(editor)
    validate_karaoke_lines(result)
    assert len(result) == 3
    assert result[0][0]["start"] == 10.0
    assert result[0][-1]["end"] == 15.0
    assert result[1][0]["start"] == 16.5
    assert result[1][-1]["end"] == 20.0
    assert result[2][0]["start"] == 60.0
    assert result[2][-1]["end"] == 65.0


def test_realign_editor_timings():
    """
    Tests the realign_editor_timings function which reconstructs timestamps for all lines.
    """
    original = [
        words("Я помню чудное мгновенье", 10.0, 0.5),  # 10.0..12.0
        words("передо мной явилась ты", 13.0, 0.5),    # 13.0..15.0
    ]
    edited_text = (
        "Я помню\n"
        "чудное мгновение\n"
        "передо мной явилась ты"
    )
    new_editor = realign_editor_timings(edited_text, original)
    lines = [line.strip() for line in new_editor.splitlines() if line.strip()]
    assert len(lines) == 3
    assert "[00:10.00 ->" in lines[0]
    assert "Я помню" in lines[0]
    assert "чудное мгновение" in lines[1]
    assert "[00:13.00 -> 00:15.00] передо мной явилась ты" in lines[2]


def test_fuzzy_russian_word_similarity_and_alignment():
    """
    Tests that morphological variants (повеситься/повесится, девчонка/девченка)
    match acoustically rather than being treated as deleted/replaced words.
    """
    from karaoke.aligner import _word_similarity
    assert _word_similarity("повеситься", "повесится") >= 0.90
    assert _word_similarity("девчонка", "девченка") >= 0.85
    assert _word_similarity("широкоплечий", "широкоплечи") >= 0.80

    recognized = words("но я сегодня забыл повесится", 20.0, 0.5)
    reference = ["Но я сегодня забыл повеситься"]
    aligned = align_words_to_reference_lines(recognized, reference)
    validate_karaoke_lines(aligned)
    assert len(aligned) == 1
    assert aligned[0][-1]["text"] == "повеситься"
    assert abs(aligned[0][-1]["end"] - recognized[-1]["end"]) < 0.1


def test_outlier_short_word_does_not_jump_across_gap():
    """
    Tests that a stray single short word ('Ты') across a 10s gap does not stretch
    the entire line across the gap (case from qopp0ucy L39).
    """
    recognized = (
        words("Предыдущая строка куплета", 140.0, 0.5)  # 140.0..141.5
        + [{"text": "ты", "start": 152.0, "end": 152.4}]  # stray short word before long pause
        + words("тяни ручонки к мылу и верёвке", 163.0, 0.6)  # 163.0..166.0
    )
    reference = [
        "Предыдущая строка куплета",
        "Ты тяни ручонки к мылу и верёвке",
    ]
    aligned = align_words_to_reference_lines(recognized, reference)
    validate_karaoke_lines(aligned)
    line2 = aligned[1]
    # Line 2 duration must NOT be 14-18 seconds long
    line2_dur = line2[-1]["end"] - line2[0]["start"]
    assert line2_dur < 6.0
    # The word "Ты" must be placed adjacent to the rest of the phrase
    assert line2[0]["end"] >= line2[1]["start"] - 0.2


def test_unaligned_line_prefix_anchored_to_right_line_end():
    """
    When the first words of a line are unaligned and the last word is aligned,
    the missing prefix must be anchored backwards from the line's end rather than
    glued forward to the previous line across an instrumental pause (case from qopp0ucy L13).
    """
    recognized = (
        words("Строка один перед проигрышем", 50.0, 0.5)  # 50.0..52.0
        # 15 seconds instrumental break between 52s and 67s
        + [{"text": "сообразим", "start": 67.0, "end": 67.8}]
    )
    reference = [
        "Строка один перед проигрышем",
        "На свиданку к десяти по пути сообразим",
    ]
    aligned = align_words_to_reference_lines(recognized, reference)
    validate_karaoke_lines(aligned)
    line2 = aligned[1]
    # The line must start close to 67.0, NOT at 52.0!
    assert line2[0]["start"] >= 62.0
    line2_dur = line2[-1]["end"] - line2[0]["start"]
    assert line2_dur <= 5.8


def test_realign_editor_timings_recalculates_existing_bracket_timestamps():
    """
    Tests that realign_editor_timings actually updates line start/end timestamps
    even when lines already contain existing [MM:SS.cc -> MM:SS.cc] brackets.
    """
    original = [
        words("Первая строка песни", 10.0, 0.5),  # 10.0..11.5
        words("Вторая строка песни", 25.0, 0.5),  # 25.0..26.5
    ]
    # User had broken timestamps or merged/split lines with old timestamps
    stale_editor_text = (
        "[00:05.00 -> 00:20.00] Первая строка песни\n"
        "[00:20.00 -> 00:30.00] Вторая строка песни"
    )
    fresh_editor_text = realign_editor_timings(stale_editor_text, original_lines=original)
    lines = [l.strip() for l in fresh_editor_text.splitlines() if l.strip()]
    assert len(lines) == 2
    # Timestamps must be recalculated to real speech times (~10s and ~25s), not the old 05.00/20.00
    assert "[00:10.00 ->" in lines[0]
    assert "[00:25.00 ->" in lines[1]


def test_align_words_in_line_window_anti_stretching():
    """
    Verifies that words inside a line window retain their acoustic duration and cadence,
    and are NOT stretched 2.5x to fill trailing silence up to line_end.
    """
    from karaoke.aligner import align_words_in_line_window
    cached = words("Мама пополняет баланс", 10.0, 0.35)  # 10.0 .. 11.05
    # Window spans from 10.00 to 15.00 (4 seconds of trailing silence)
    res = align_words_in_line_window(["Мама", "пополняет", "баланс"], 10.0, 15.0, cached)
    # The words must finish near 11.05s, NOT be stretched across all 15 seconds!
    assert res[-1]["end"] <= 11.5
    assert res[0]["start"] == 10.0
    for w in res:
        dur = w["end"] - w["start"]
        assert dur < 0.8


def test_distribute_words_punctuation_pauses():
    """
    Verifies that _distribute_words reserves breath pauses after commas/dashes
    and period pauses, rather than zero-gap contiguous placement.
    """
    from karaoke.aligner import _distribute_words
    tokens = ["Привет,", "мой", "друг!"]
    res = _distribute_words(tokens, 10.0, 14.0)
    assert len(res) == 3
    # Breath pause after comma (between word 0 and word 1)
    gap_after_comma = res[1]["start"] - res[0]["end"]
    assert gap_after_comma >= 0.12
    # End of word 0
    assert res[0]["text"] == "Привет,"
    assert res[-1]["end"] == 14.0


def test_sequence_opcodes_skips_hallucinations_without_corrupting_reference():
    """
    Verifies that unrecognized or hallucinated Whisper words are marked as insert/delete
    rather than replacing completely unrelated reference lyrics.
    """
    from karaoke.aligner import _sequence_opcodes
    reference = ["мама", "пополняет", "баланс", "сегодня", "вечером"]
    recognized = ["мама", "пополняет", "баланс", "какой-то", "левый", "шум", "сегодня", "вечером"]
    opcodes = list(_sequence_opcodes(reference, recognized))
    # Must contain insert for the extra tokens, and equal for the rest
    tags = [op[0] for op in opcodes]
    assert "replace" not in tags
    assert "insert" in tags
    assert "equal" in tags


def test_punctuation_adlib_interpolation_does_not_stretch_across_gap():
    """
    Verifies that missing ad-libs/punctuated words like '(Е),' in a 2.5s gap
    are anchored with natural singing duration (~0.4-0.5s) instead of stretching
    across the entire 2.5s audio pause.
    """
    recognized = (
        words("Я сорю баблом на сцене", 81.0, 0.3)  # 81.0 .. 82.5
        + words("дайте шлюхам веник", 85.0, 0.3)   # 85.0 .. 85.9 (2.5s gap)
    )
    reference = [
        "Я сорю баблом на сцене (Е), дайте шлюхам веник"
    ]
    aligned = align_words_to_reference_lines(recognized, reference)
    validate_karaoke_lines(aligned)
    line = aligned[0]
    adlib = next(w for w in line if "(Е)," in w["text"])
    dur = adlib["end"] - adlib["start"]
    assert dur <= 0.65, f"Adlib was stretched to {dur:.2f}s!"
    assert adlib["start"] >= 82.4
    assert adlib["end"] <= 83.2


def test_split_whisper_compound_words_merged_cleanly():
    """
    Verifies that when Whisper splits a compound Russian word into two pieces
    (e.g. 'стрипухе' -> 'три' + 'пуфи'), the aligner merges the recognized tokens
    and gives the reference word the exact acoustic duration, ending early before the pause.
    """
    rec_words = [
        {"text": "Я", "start": 47.40, "end": 47.62},
        {"text": "кидаю", "start": 47.62, "end": 48.12},
        {"text": "бабки", "start": 48.12, "end": 48.56},
        {"text": "в", "start": 48.56, "end": 48.82},
        {"text": "эти", "start": 48.82, "end": 49.06},
        {"text": "три", "start": 49.06, "end": 49.28},
        {"text": "пуфи.", "start": 49.28, "end": 49.76},
        {"text": "What's", "start": 51.29, "end": 51.59},
    ]
    reference = [
        "Bitch, я кидаю бабки в этой стрипухе",
        "What's going on, bitch?",
    ]
    aligned = align_words_to_reference_lines(rec_words, reference)
    validate_karaoke_lines(aligned)
    line1 = aligned[0]
    stripukha = line1[-1]
    assert stripukha["text"] == "стрипухе"
    # Must finish near 49.76s when voice ends, not stretch into the 51.29s gap!
    assert stripukha["end"] <= 49.85
    assert stripukha["start"] <= 49.15


def test_sanitize_reference_lyrics_filters_watermarks_and_structures():
    raw_lyrics = """
    [Куплет 1]
    Эй, смотри, зай
    Желание загадай
    Источник: txtsong.ru
    ---
    (Припев)
    Ты неси меня, река (х2)
    Да так, чтоб наверняка
    [x3]
    Куплет 2:
    NFT из нефти
    Текст взят с сайта genius.com
    """
    cleaned = sanitize_reference_lyrics(raw_lyrics)
    assert "Эй, смотри, зай" in cleaned
    assert "Желание загадай" in cleaned
    assert "Ты неси меня, река" in cleaned
    assert "Да так, чтоб наверняка" in cleaned
    assert "NFT из нефти" in cleaned
    # Ensure watermarks, structural markers, and repetition artifacts are purged
    assert not any("txtsong" in line for line in cleaned)
    assert not any("Куплет" in line for line in cleaned)
    assert not any("Припев" in line for line in cleaned)
    assert not any("genius.com" in line for line in cleaned)
    assert not any("---" in line for line in cleaned)
    assert not any("[x3]" in line for line in cleaned)


def test_density_sanity_guard_rejects_spurious_isolated_anchor():
    # Spurious anchor 'Душа' at 0.23s should not crush 10 preceding words into 0.23s
    rec_words = [
        {"text": "Душа", "start": 0.23, "end": 1.20},
        {"text": "NFT", "start": 33.34, "end": 33.77},
        {"text": "из", "start": 33.80, "end": 34.24},
        {"text": "нефти", "start": 34.24, "end": 34.76},
    ]
    reference = [
        "Эй смотри зай желание загадай",
        "Пока спутник над тайгою взлетает куда-то вдаль",
        "Вся душа поет",
        "NFT из нефти",
    ]
    aligned = align_words_to_reference_lines(rec_words, reference)
    validate_karaoke_lines(aligned)
    assert len(aligned) == 4
    # First line must NOT be squeezed into 0.0..0.23s!
    first_word = aligned[0][0]
    assert first_word["start"] >= 5.0  # Spaced naturally before 33.34s


def test_refine_unaligned_vocal_slices_synthetic():
    raw_words = [
        {"text": "куплет", "start": 15.0, "end": 16.0},
    ]
    # When no vocals file provided, gracefully returns original words
    res = refine_unaligned_vocal_slices(raw_words, "строка 1\nстрока 2", vocals_path=None)
    assert res == raw_words


def test_omitted_outro_vocal_repetitions_do_not_hijack_line_timing():
    """
    Verifies that when vocals have trailing repetitions / ad-libs in the outro
    (e.g., 'умею целоваться' followed by repeated 'целоваться' in outro audio),
    and the reference lyrics omit those outro repetitions, the aligner binds
    the line's last word to the first acoustic occurrence immediately following
    the preceding words, rather than jumping to trailing repetitions and squashing
    the word duration.
    """
    recognized = [
        {"text": "умею", "start": 217.90, "end": 218.56},
        {"text": "целоваться", "start": 218.56, "end": 219.82},
        # Trailing outro vocal ad-libs not present in lyrics
        {"text": "Целоваться", "start": 221.00, "end": 222.50},
        {"text": "Целоваться", "start": 225.00, "end": 226.50},
        {"text": "Целоваться", "start": 230.94, "end": 232.98},
    ]
    reference = [
        "Я в классе лучше всех умею целоваться"
    ]
    # Recognizer before "умею"
    prefix = [
        {"text": "Я", "start": 216.46, "end": 216.64},
        {"text": "в", "start": 216.64, "end": 216.78},
        {"text": "классе", "start": 216.78, "end": 217.24},
        {"text": "лучше", "start": 217.24, "end": 217.64},
        {"text": "всех", "start": 217.64, "end": 217.90},
    ]
    full_recognized = prefix + recognized
    aligned = align_words_to_reference_lines(full_recognized, reference)
    validate_karaoke_lines(aligned)

    last_line = aligned[0]
    last_word = last_line[-1]
    assert last_word["text"] == "целоваться"
    # Must bind to the first occurrence at 218.56..219.82, not the outro jump at 230s+
    assert last_word["start"] == 218.56
    assert last_word["end"] == 219.82


def _parse_ass_time_seconds(ts: str) -> float:
    h, m, s = ts.strip().split(":")
    return int(h) * 3600.0 + int(m) * 60.0 + float(s)


def test_ass_tight_line_transitions_never_overlap_or_start_late(tmp_path):
    from karaoke.ass_writer import generate_ass_from_lines

    lines = [
        [{"text": "Первая", "start": 3.00, "end": 4.00, "syllables": 3}, {"text": "строка", "start": 4.05, "end": 5.00, "syllables": 3}],
        [{"text": "Вторая", "start": 5.02, "end": 5.60, "syllables": 3}, {"text": "строка", "start": 5.62, "end": 6.20, "syllables": 3}],
        [{"text": "Третья", "start": 6.80, "end": 7.30, "syllables": 2}, {"text": "строка", "start": 7.35, "end": 8.00, "syllables": 3}],
    ]
    out_ass = tmp_path / "tight.ass"
    generate_ass_from_lines(lines, out_ass, visual_effects="none")

    active_events = []
    for raw in out_ass.read_text(encoding="utf-8").splitlines():
        if raw.startswith("Dialogue:") and ",KaraokeActive," in raw:
            parts = raw.split(",", 9)
            active_events.append((_parse_ass_time_seconds(parts[1]), _parse_ass_time_seconds(parts[2])))

    assert len(active_events) == 3
    # Line 1 must finish by Line 2's first word start (5.02s), and Line 2 must start <= 5.02s
    assert active_events[0][1] <= 5.02 + 1e-6
    assert active_events[1][0] <= 5.02 + 1e-6
    # No two active lines overlap
    for (s1, e1), (s2, e2) in zip(active_events, active_events[1:]):
        assert e1 <= s2 + 1e-6


def test_build_karaoke_line_tags_uses_syllable_timings_for_sustained_first_syllable():
    from karaoke.ass_writer import build_karaoke_line_tags

    word = {
        "text": "море",
        "start": 1.0,
        "end": 2.2,
        "syllables": 2,
        "syllable_timings": [
            {"text": "мо", "start": 1.0, "end": 2.0},
            {"text": "ре", "start": 2.0, "end": 2.2},
        ],
    }
    tags = build_karaoke_line_tags([word], display_start=1.0, display_end=2.5)
    assert "{\\kf100}мо{\\kf20}ре" in tags


def test_adaptive_vocal_offset_handles_quiet_verse_and_loud_chorus():
    import numpy as np
    from karaoke.aligner import find_vocal_offset

    hop_s = 0.01
    rms = np.zeros(1000, dtype=np.float32)  # 10.0s
    rms[100:400] = 0.04   # quiet verse: 1.0s - 4.0s
    rms[500:900] = 0.50   # loud chorus: 5.0s - 9.0s
    rms[900:980] = 0.035  # quiet reverb tail: 9.0s - 9.8s

    verse_off = find_vocal_offset(rms, hop_s, 1.0, 4.5, min_silence_s=0.20)
    assert 3.95 <= verse_off <= 4.15

    chorus_off = find_vocal_offset(rms, hop_s, 6.0, 10.0, min_silence_s=0.20)
    assert 8.95 <= chorus_off <= 9.15


def test_mms_fa_transliteration_and_syllable_onsets():
    import torchaudio
    from karaoke.aligner import _word_syllables_to_mms_tokens, _build_syllable_timings_from_onsets, split_word_into_syllables

    vocab = torchaudio.pipelines.MMS_FA.get_dict()
    sylls = split_word_into_syllables("свобода")
    assert sylls == ["сво", "бо", "да"]

    mapped = _word_syllables_to_mms_tokens("свобода", vocab)
    assert len(mapped) == 3
    assert all(len(tids) >= 2 for _, tids in mapped)

    # Sustained middle syllable ("бо" from 1.2s to 2.2s)
    timings = _build_syllable_timings_from_onsets(sylls, [1.0, 1.2, 2.2], 1.0, 2.4)
    assert [t["text"] for t in timings] == ["сво", "бо", "да"]
    assert timings[1]["end"] - timings[1]["start"] == pytest.approx(1.0, abs=0.01)


def test_editor_text_to_lines_honors_manual_stretch_and_slight_overlap():
    original = [
        words("Лучше я поиграю", 10.0, 0.5),  # 10.0 .. 11.5
        words("Вон с тем мужиком", 12.5, 0.4),  # 12.5 .. 14.1
    ]
    # 1. User stretches line 0 earlier (9.40) and later (12.20)
    edited_stretch = "[00:09.40 -> 00:12.20] Лучше я поиграю\n[00:12.50 -> 00:14.10] Вон с тем мужиком"
    res1 = editor_text_to_lines(edited_stretch, original_lines=original)
    validate_karaoke_lines(res1)
    assert res1[0][0]["start"] == pytest.approx(9.40, abs=0.02)
    assert res1[0][-1]["end"] == pytest.approx(12.20, abs=0.02)

    # 2. User extends line 0 slightly past line 1's start (12.70 > 12.50)
    edited_overlap = "[00:09.40 -> 00:12.70] Лучше я поиграю\n[00:12.50 -> 00:14.10] Вон с тем мужиком"
    res2 = editor_text_to_lines(edited_overlap, original_lines=original)
    validate_karaoke_lines(res2)
    assert res2[0][0]["start"] == pytest.approx(9.40, abs=0.02)
    assert res2[0][-1]["end"] == pytest.approx(12.50, abs=0.02)
    assert res2[1][0]["start"] == pytest.approx(12.50, abs=0.02)










