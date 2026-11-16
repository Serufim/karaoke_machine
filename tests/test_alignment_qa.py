import numpy as np
import soundfile as sf

from karaoke.aligner import validate_karaoke_lines
from karaoke.alignment_qa import (
    evaluate_alignment_quality,
    format_alignment_report_summary,
    optimize_alignment_to_target,
)


def _write_synthetic_vocals(path, duration_s: float = 8.0, active_ranges=None, sr: int = 16000):
    audio = np.zeros(int(duration_s * sr), dtype=np.float32)
    t = np.arange(len(audio)) / sr
    tone = 0.25 * np.sin(2 * np.pi * 220.0 * t).astype(np.float32)
    for s, e in (active_ranges or []):
        i_s = max(0, int(s * sr))
        i_e = min(len(audio), int(e * sr))
        audio[i_s:i_e] = tone[i_s:i_e]
    sf.write(str(path), audio, sr)


def test_evaluate_alignment_quality_scores_clean_high_and_detects_issues(tmp_path):
    vocals = tmp_path / "vocals.wav"
    # Singing from 1.0..3.0 and 3.5..5.5
    _write_synthetic_vocals(vocals, duration_s=7.0, active_ranges=[(1.0, 3.0), (3.5, 5.5)])

    clean_lines = [
        [
            {"text": "Моя", "start": 1.00, "end": 1.60, "syllables": 2},
            {"text": "вторая", "start": 1.60, "end": 2.30, "syllables": 3},
            {"text": "песня", "start": 2.30, "end": 3.00, "syllables": 2},
        ],
        [
            {"text": "Покурю", "start": 3.50, "end": 4.50, "syllables": 3},
            {"text": "сиги", "start": 4.50, "end": 5.50, "syllables": 2},
        ],
    ]
    clean_rep = evaluate_alignment_quality(clean_lines, vocals)
    assert clean_rep["overall_score"] >= 92.0
    assert "🎯 Точность таймингов:" in format_alignment_report_summary(clean_rep)

    # Degraded: late onset on line 0 (+0.5s), mid_gap on line 1 (4.0 -> 4.6), squashed word (0.06s)
    bad_lines = [
        [
            {"text": "Моя", "start": 1.50, "end": 1.80, "syllables": 2},
            {"text": "вторая", "start": 1.80, "end": 1.86, "syllables": 3},
            {"text": "песня", "start": 1.86, "end": 3.00, "syllables": 2},
        ],
        [
            {"text": "Покурю", "start": 3.50, "end": 4.00, "syllables": 3},
            {"text": "сиги", "start": 4.65, "end": 6.20, "syllables": 2},
        ],
    ]
    bad_rep = evaluate_alignment_quality(bad_lines, vocals)
    assert bad_rep["overall_score"] < 85.0
    assert bad_rep["overall_score"] < clean_rep["overall_score"] - 10.0
    all_issues = {iss for pl in bad_rep["problem_lines"] for iss in pl["issues"]}
    assert "late_onset" in all_issues
    assert "squashed_word" in all_issues
    assert "mid_gap" in all_issues
    assert "trailing_silence" in all_issues


def test_optimize_alignment_to_target_recovers_above_90_percent(tmp_path):
    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=7.0, active_ranges=[(1.0, 3.0), (3.5, 5.5)])

    degraded_lines = [
        [
            {"text": "Моя", "start": 1.50, "end": 1.80, "syllables": 2},
            {"text": "вторая", "start": 1.80, "end": 1.86, "syllables": 3},
            {"text": "песня", "start": 1.86, "end": 3.40, "syllables": 2},
        ],
        [
            {"text": "Покурю", "start": 3.90, "end": 4.20, "syllables": 3},
            {"text": "сиги", "start": 4.70, "end": 6.10, "syllables": 2},
        ],
    ]
    before = evaluate_alignment_quality(degraded_lines, vocals)
    assert before["overall_score"] < 80.0

    opt_lines, after = optimize_alignment_to_target(degraded_lines, vocals, target_score=90.0)
    validate_karaoke_lines(opt_lines)
    assert after["overall_score"] >= 90.0
    assert opt_lines[0][0]["start"] <= 1.10
    assert opt_lines[1][0]["start"] <= 3.60


def test_optimize_rejects_worse_ctc_candidate_per_line(tmp_path):
    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=5.0, active_ranges=[(1.0, 3.0)])

    good_base = [
        [
            {"text": "Моя", "start": 1.00, "end": 1.60, "syllables": 2},
            {"text": "вторая", "start": 1.60, "end": 2.30, "syllables": 3},
            {"text": "эсса", "start": 2.30, "end": 3.00, "syllables": 2},
        ]
    ]
    bad_ctc = [
        [
            {"text": "Моя", "start": 1.55, "end": 1.70, "syllables": 2},
            {"text": "вторая", "start": 2.25, "end": 2.40, "syllables": 3},
            {"text": "эсса", "start": 2.40, "end": 3.00, "syllables": 2},
        ]
    ]
    opt_lines, rep = optimize_alignment_to_target(good_base, vocals, ctc_lines=bad_ctc, target_score=90.0)
    assert rep["overall_score"] >= 92.0
    assert opt_lines[0][0]["start"] == 1.00


def test_whisper_anchor_blocks_drifted_ctc_and_repairs_drifted_line(tmp_path):
    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=6.0, active_ranges=[(1.0, 4.0)])

    recognized = [
        {"text": "Но", "start": 1.50, "end": 1.80},
        {"text": "это", "start": 1.80, "end": 2.20},
        {"text": "план", "start": 2.20, "end": 2.80},
    ]
    base_lines = [
        [
            {"text": "Но", "start": 1.50, "end": 1.80, "syllables": 1},
            {"text": "это", "start": 1.80, "end": 2.20, "syllables": 2},
            {"text": "план", "start": 2.20, "end": 2.80, "syllables": 1},
        ]
    ]
    # CTC drifts +0.54s later even though vocals are active at 1.50s -> anchor guard rejects it
    drifted_ctc = [
        [
            {"text": "Но", "start": 2.04, "end": 2.24, "syllables": 1},
            {"text": "это", "start": 2.24, "end": 2.50, "syllables": 2},
            {"text": "план", "start": 2.50, "end": 2.90, "syllables": 1},
        ]
    ]
    opt_lines, _ = optimize_alignment_to_target(
        base_lines, vocals, ctc_lines=drifted_ctc, target_score=90.0, recognized_words=recognized
    )
    assert opt_lines[0][0]["start"] == 1.50

    # If base_lines itself already drifted +0.54s, anchor repair restores raw Whisper timings
    opt_repaired, rep = optimize_alignment_to_target(
        drifted_ctc, vocals, target_score=90.0, recognized_words=recognized
    )
    assert opt_repaired[0][0]["start"] == 1.50
    assert 0 in rep["anchor_repaired_lines"]


def test_locked_good_and_bad_line_constraints(tmp_path):
    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=6.0, active_ranges=[(0.5, 2.0), (2.5, 4.5)])

    good_saved = [
        {"text": "Хорошая", "start": 0.55, "end": 1.25, "syllables": 4},
        {"text": "строка", "start": 1.25, "end": 1.95, "syllables": 2},
    ]
    bad_saved = [
        {"text": "Плохая", "start": 2.95, "end": 3.55, "syllables": 3},
        {"text": "строка", "start": 3.55, "end": 4.45, "syllables": 2},
    ]
    new_lines = [
        [
            {"text": "Хорошая", "start": 0.80, "end": 1.40, "syllables": 4},
            {"text": "строка", "start": 1.40, "end": 2.00, "syllables": 2},
        ],
        [
            {"text": "Плохая", "start": 2.95, "end": 3.55, "syllables": 3},
            {"text": "строка", "start": 3.55, "end": 4.45, "syllables": 2},
        ],
    ]
    opt_lines, rep = optimize_alignment_to_target(
        new_lines,
        vocals,
        target_score=90.0,
        locked_lines={0: good_saved},
        bad_lines={1: bad_saved},
    )
    assert opt_lines[0][0]["start"] == 0.55
    assert opt_lines[1][0]["start"] != 2.95
    assert 0 in rep["locked_lines"]
    assert 1 in rep["changed_bad_lines"]


def test_timing_history_snapshots_marks_and_diff(tmp_path):
    from karaoke import timing_history

    lines_v1 = [
        [{"text": "Первая", "start": 1.00, "end": 1.50}, {"text": "строка", "start": 1.50, "end": 2.00}],
        [{"text": "Вторая", "start": 2.50, "end": 3.00}, {"text": "строка", "start": 3.00, "end": 3.60}],
    ]
    marks = timing_history.set_line_mark(lines_v1, [], 0, "good")
    marks = timing_history.set_line_mark(lines_v1, marks, 1, "bad")
    state_v1 = {"lines": lines_v1, "editor_text": "", "alignment_report": {"overall_score": 88.0}, "line_marks": marks}
    meta = timing_history.save_snapshot(tmp_path, "proj", state_v1, reason="regenerate")
    assert meta is not None
    assert meta["marks_summary"] == {"good": 1, "bad": 1}

    snaps = timing_history.list_snapshots(tmp_path, "proj")
    assert len(snaps) == 1

    # Regeneration inserts an extra line before line 1 -> marks still match by text + time
    lines_v2 = [
        [{"text": "Первая", "start": 1.00, "end": 1.50}, {"text": "строка", "start": 1.50, "end": 2.00}],
        [{"text": "Вставка", "start": 2.05, "end": 2.40}],
        [{"text": "Вторая", "start": 2.75, "end": 3.15}, {"text": "строка", "start": 3.15, "end": 3.60}],
    ]
    locked, bad = timing_history.marks_to_constraints(lines_v2, marks)
    assert 0 in locked
    assert 2 in bad
    diffs = timing_history.diff_lines(lines_v1, lines_v2)
    assert diffs[0]["start_shift"] == 0.0
    assert diffs[1] is None
    assert diffs[2]["start_shift"] == 0.25


def test_word_syllables_to_mms_tokens_handles_digits():
    from karaoke.aligner import _word_syllables_to_mms_tokens

    vocab = {ch: idx + 1 for idx, ch in enumerate("abcdefghijklmnopqrstuvwxyz'")}
    toks = _word_syllables_to_mms_tokens("18", vocab)
    assert len(toks) == 1
    assert len(toks[0][1]) >= 6


def test_editor_text_to_lines_preserves_and_rescales_syllable_timings():
    from karaoke.aligner import editor_text_to_lines, lines_to_editor_text

    original_lines = [
        [
            {
                "text": "Лучше",
                "start": 92.85,
                "end": 94.68,
                "syllables": 2,
                "syllable_timings": [
                    {"text": "Лу", "start": 92.85, "end": 93.75},
                    {"text": "чше", "start": 93.75, "end": 94.68},
                ],
            },
            {"text": "я", "start": 94.75, "end": 95.08, "syllables": 1},
            {
                "text": "поиграю",
                "start": 95.08,
                "end": 96.58,
                "syllables": 4,
                "syllable_timings": [
                    {"text": "по", "start": 95.08, "end": 95.35},
                    {"text": "и", "start": 95.35, "end": 95.68},
                    {"text": "гра", "start": 95.68, "end": 96.18},
                    {"text": "ю", "start": 96.18, "end": 96.58},
                ],
            },
        ]
    ]
    editor_text = lines_to_editor_text(original_lines)
    rebuilt = editor_text_to_lines(editor_text, original_lines=original_lines)
    assert "syllable_timings" in rebuilt[0][0]
    assert rebuilt[0][0]["syllable_timings"][0]["end"] == 93.75
    assert "syllable_timings" in rebuilt[0][2]
    assert len(rebuilt[0][2]["syllable_timings"]) == 4


def test_mcp_fine_grained_timing_tools(tmp_path, monkeypatch):
    import json
    from karaoke import mcp_server

    monkeypatch.setattr(mcp_server, "WORK_DIR", tmp_path)
    monkeypatch.setattr(mcp_server, "notify_studio_ui", lambda *a, **kw: None)

    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=12.0, active_ranges=[(1.0, 2.5), (3.0, 5.0)])
    state = {
        "title": "mcp_demo",
        "vocals_wav": str(vocals),
        "lines": [
            [{"text": "Да", "start": 1.0, "end": 1.4}, {"text": "игрушки", "start": 1.4, "end": 2.4}],
            [{"text": "Я", "start": 3.0, "end": 3.6}, {"text": "большая", "start": 3.6, "end": 4.8}],
        ],
        "recognized_words": [
            {"text": "Да", "start": 1.05, "end": 1.35},
            {"text": "игрушки", "start": 1.38, "end": 2.45},
        ],
    }
    (tmp_path / "mcp_demo_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    info = mcp_server.get_lines("mcp_demo", 0.5, 5.5)
    assert info["status"] == "success"
    assert len(info["lines"]) == 2

    win = mcp_server.analyze_vocal_window("mcp_demo", 0.5, 5.5, 0.05)
    assert win["status"] == "success"
    assert len(win["profile"]) > 10

    r_words = mcp_server.set_word_timings(
        "mcp_demo",
        0,
        [
            {"text": "Да", "start": 1.02, "end": 1.36},
            {
                "text": "игрушки",
                "start": 1.38,
                "end": 2.42,
                "syllables": [
                    {"text": "и", "start": 1.38, "end": 1.70},
                    {"text": "гру", "start": 1.70, "end": 2.10},
                    {"text": "шки", "start": 2.10, "end": 2.42},
                ],
            },
        ],
    )
    assert r_words["status"] == "success"
    assert len(r_words["line"]["words"][1]["syllables"]) == 3

    r_shift = mcp_server.shift_lines("mcp_demo", 1, 1, 0.25)
    assert r_shift["status"] == "success"
    assert r_shift["lines"][0]["start"] == 3.25

    hist = mcp_server.list_timing_history("mcp_demo")
    assert len(hist["snapshots"]) >= 2
    res_restore = mcp_server.restore_timing_snapshot("mcp_demo", hist["snapshots"][-1]["id"])
    assert res_restore["status"] == "success"


def test_realign_lines_by_vocals_preserves_stretched_bounds_and_trims_overlap(tmp_path):
    from karaoke.aligner import realign_lines_by_vocals

    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=10.0, active_ranges=[(1.0, 5.2), (5.5, 7.5)])

    # User stretched line 0 to [1.0, 5.2], slightly overlapping line 1 which started at 4.8
    lines = [
        [
            {"text": "Лучше", "start": 1.0, "end": 2.4},
            {"text": "я", "start": 2.4, "end": 3.2},
            {"text": "поиграю", "start": 3.2, "end": 5.2},
        ],
        [
            {"text": "Вон", "start": 4.8, "end": 5.6},
            {"text": "мужиком", "start": 5.6, "end": 7.5},
        ],
    ]
    out_lines, updated = realign_lines_by_vocals(lines, vocals, [0])
    assert 0 in updated
    assert out_lines[0][0]["start"] == 1.0
    assert out_lines[0][-1]["end"] == 5.2
    # Neighbour line 1 was trimmed so it starts >= 5.2 without overlap
    assert out_lines[1][0]["start"] >= 5.2
    # No word is squashed
    for w in out_lines[0]:
        assert (w["end"] - w["start"]) >= 0.25


def test_expand_recognized_words_splits_hyphenated_and_compound_words():
    from karaoke.aligner import align_words_to_reference_lines

    rec_words = [
        {"text": "На", "start": 1.0, "end": 1.2},
        {"text": "Граустрите", "start": 1.2, "end": 2.2},
        {"text": "в", "start": 2.2, "end": 2.3},
        {"text": "Лос-Сантос", "start": 2.3, "end": 3.3},
    ]
    lines = align_words_to_reference_lines(
        rec_words,
        ["На Гроув Стрите в Лос Сантос"],
        vocals_path=None,
    )
    assert len(lines) == 1
    words = lines[0]
    assert [w["text"] for w in words] == ["На", "Гроув", "Стрите", "в", "Лос", "Сантос"]
    # Compound "Граустрите" (1.2-2.2) splits into Гроув + Стрите without crushing either
    assert 1.15 <= words[1]["start"] <= 1.25
    assert words[1]["end"] - words[1]["start"] >= 0.25
    assert words[2]["end"] - words[2]["start"] >= 0.40
    # Hyphenated "Лос-Сантос" (2.3-3.3) splits cleanly into Лос + Сантос
    assert 2.25 <= words[4]["start"] <= 2.35
    assert words[4]["end"] - words[4]["start"] >= 0.25
    assert words[5]["end"] >= 3.25


def test_realign_lines_by_vocals_anchors_whisper_words_and_clamps_proclitics(tmp_path):
    from karaoke.aligner import realign_lines_by_vocals

    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=8.0, active_ranges=[(1.0, 5.2)])

    # Line has smeared words (в stretched to 0.45s, много stretched to 1.2s)
    lines = [[
        {"text": "Так", "start": 1.0, "end": 1.25},
        {"text": "много", "start": 1.25, "end": 2.65},
        {"text": "в", "start": 2.65, "end": 3.15},
        {"text": "городе", "start": 3.15, "end": 5.2},
    ]]
    rec_words = [
        {"text": "Так", "start": 1.0, "end": 1.20},
        {"text": "много", "start": 1.20, "end": 1.75},
        {"text": "в", "start": 2.95, "end": 3.10},
        {"text": "городе", "start": 3.10, "end": 5.15},
    ]
    out_lines, updated = realign_lines_by_vocals(
        lines, vocals, [0], recognized_words=rec_words
    )
    assert 0 in updated
    w_out = out_lines[0]
    # Matched Whisper anchor for "много" keeps it near [1.20, 1.75] instead of 1.2s smear
    assert abs(w_out[1]["end"] - 1.75) <= 0.15
    # Vowelless proclitic "в" is clamped <= 0.16s
    assert (w_out[2]["end"] - w_out[2]["start"]) <= 0.16
    # Syllable timings populated for multi-syllable words
    assert len(w_out[3].get("syllable_timings", [])) == 3


def test_optimize_alignment_to_target_99_tracks_history_and_fixes_proclitic(tmp_path):
    from karaoke.alignment_qa import optimize_alignment_to_target

    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=7.0, active_ranges=[(1.0, 4.5)])

    lines = [[
        {"text": "Вернуться", "start": 1.0, "end": 2.2},
        {"text": "в", "start": 2.2, "end": 2.85},  # stretched proclitic (0.65s!)
        {"text": "городок", "start": 2.85, "end": 4.5},
    ]]
    opt, report = optimize_alignment_to_target(lines, vocals, target_score=99.0, max_iters=6)
    assert "iterations_history" in report
    assert len(report["iterations_history"]) >= 1
    # Proclitic "в" should be clamped <= 0.16s and score should improve
    assert (opt[0][1]["end"] - opt[0][1]["start"]) <= 0.16
    assert report["overall_score"] >= 95.0


def test_parse_reference_lyrics_directives_pegs_repeats_voices_and_shown():
    from karaoke.aligner import parse_reference_lyrics_directives

    raw = """
    [Соло 0:00-0:15]
    [0:16.50] Первая строка
    Припев x3
    2: Бэк вокал строка
    [voice 2]
    Второй голос
    [voice 1]
    Натуральные числа | ℕ
    фо=то=гра=фи=я
    """
    res = parse_reference_lyrics_directives(raw)
    assert res["no_words_ranges"] == [(0.0, 15.0)]
    lines = res["lines"]
    assert lines[0]["sung_text"] == "Первая строка"
    assert lines[0]["peg_start"] == 16.5
    assert [l["sung_text"] for l in lines[1:4]] == ["Припев", "Припев", "Припев"]
    assert lines[4]["voice"] == 2 and lines[4]["sung_text"] == "Бэк вокал строка"
    assert lines[5]["voice"] == 2 and lines[5]["sung_text"] == "Второй голос"
    assert lines[6]["voice"] == 1 and lines[6]["sung_text"] == "Натуральные числа" and lines[6]["shown_text"] == "ℕ"
    assert lines[7]["sung_text"] == "фо=то=гра=фи=я"


def test_align_words_respects_sparse_pegs_and_no_words_zones():
    from karaoke.aligner import align_words_to_reference_lines

    rec_words = [
        {"text": "ааа", "start": 2.0, "end": 4.0},   # inside [no words 0:00-0:05]
        {"text": "Первая", "start": 10.0, "end": 10.5},
        {"text": "строка", "start": 10.5, "end": 11.2},
        {"text": "Вторая", "start": 25.0, "end": 25.6},
        {"text": "строка", "start": 25.6, "end": 26.3},
    ]
    ref = [
        "[no words 0:00-0:05]",
        "[0:10] Первая строка",
        "[0:25] Вторая фо=то=гра=фи=я",
    ]
    lines = align_words_to_reference_lines(rec_words, ref, vocals_path=None)
    assert len(lines) == 2
    assert lines[0][0]["start"] >= 9.9
    assert lines[1][0]["start"] >= 24.9
    # Explicit syllable marker '=' stripped from final display text
    assert lines[1][1]["text"] == "фотография"
    assert lines[1][1]["syllables"] == 5


def test_split_and_join_line_by_breath_pause():
    from karaoke.aligner import split_line_by_breath_pause, join_with_next_line

    lines = [[
        {"text": "Раз", "start": 1.0, "end": 1.3},
        {"text": "два", "start": 1.32, "end": 1.6},
        {"text": "три", "start": 2.4, "end": 2.8},  # longest pause (0.8s) before "три"
        {"text": "четыре", "start": 2.82, "end": 3.4},
    ]]
    split_lines = split_line_by_breath_pause(lines, 0)
    assert len(split_lines) == 2
    assert [w["text"] for w in split_lines[0]] == ["Раз", "два"]
    assert [w["text"] for w in split_lines[1]] == ["три", "четыре"]

    joined = join_with_next_line(split_lines, 0)
    assert len(joined) == 1
    assert [w["text"] for w in joined[0]] == ["Раз", "два", "три", "четыре"]


def test_export_standalone_html_and_pitch_shift(tmp_path):
    from karaoke.mixer import shift_pitch_wav
    from karaoke.pro_exporter import export_standalone_html

    vocals = tmp_path / "vocals.wav"
    _write_synthetic_vocals(vocals, duration_s=3.0, active_ranges=[(0.5, 2.5)])

    # Zero pitch shift returns source path directly
    assert shift_pitch_wav(vocals, tmp_path / "out_0.wav", 0.0) == vocals

    # +2 semitones pitch shift creates valid WAV
    shifted = shift_pitch_wav(vocals, tmp_path / "out_p2.wav", 2.0)
    assert shifted.exists() and shifted.stat().st_size > 1024

    # Standalone HTML export embeds audio and lyrics
    html_out = tmp_path / "demo_karaoke.html"
    lines = [[
        {"text": "Привет", "start": 0.5, "end": 1.2},
        {"text": "мир", "start": 1.2, "end": 2.0, "voice": 2},
    ]]
    export_standalone_html(lines, vocals, html_out, title="Demo Track", vocals_wav=vocals)
    content = html_out.read_text(encoding="utf-8")
    assert "data:audio/mpeg;base64," in content
    assert "Привет" in content and "Demo Track" in content





