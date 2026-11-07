import copy

import pytest

from karaoke.aligner import (
    TimingAlignmentError, align_words_to_reference_lines, editor_text_to_lines,
    lines_to_editor_text, split_into_karaoke_lines, validate_karaoke_lines,
    split_long_editor_lines, split_single_long_line,
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



