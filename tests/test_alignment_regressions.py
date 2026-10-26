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
    with pytest.raises(TimingAlignmentError):
        align_words_to_reference_lines(recognized, reference)
    warnings = []
    lines = split_into_karaoke_lines([{"words": recognized}],
                                    reference_lyrics="\n".join(reference), warnings_out=warnings)
    assert warnings
    assert [w["text"] for line in lines for w in line] == [w["text"] for w in recognized]
    validate_karaoke_lines(lines)


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
