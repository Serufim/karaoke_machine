import json
from pathlib import Path
import pytest

from karaoke.slice_editor import (
    align_audio_slice,
    apply_slice_to_project,
)


def test_align_audio_slice_syllables_rms(tmp_path):
    # Test fallback syllable & RMS distribution
    res = align_audio_slice(
        title="test_song",
        start=10.0,
        end=14.0,
        text="Привет прекрасный мир",
        mode="syllables_rms",
        work_dir=tmp_path,
    )
    assert len(res) == 3
    assert res[0]["text"] == "Привет"
    assert res[1]["text"] == "прекрасный"
    assert res[2]["text"] == "мир"
    assert res[0]["start"] >= 10.0
    assert res[-1]["end"] <= 14.1
    # Check monotonicity
    for i in range(len(res) - 1):
        assert res[i]["end"] <= res[i + 1]["start"] + 0.01


def test_apply_slice_to_project(tmp_path):
    title = "fixture_song"
    initial_words = [
        {"text": "Начало", "start": 1.0, "end": 2.0, "syllables": 3},
        {"text": "старый", "start": 5.0, "end": 6.0, "syllables": 2},
        {"text": "текст", "start": 6.0, "end": 7.0, "syllables": 1},
        {"text": "Конец", "start": 15.0, "end": 16.0, "syllables": 2},
    ]
    state_file = tmp_path / f"{title}_state.json"
    state_file.write_text(
        json.dumps({
            "title": title,
            "lines": [initial_words],
            "editor_text": "[00:01.00 -> 00:16.00] Начало старый текст Конец",
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    new_slice_words = [
        {"text": "новый", "start": 5.2, "end": 6.1, "syllables": 2},
        {"text": "правильный", "start": 6.1, "end": 7.5, "syllables": 3},
        {"text": "вокал", "start": 7.5, "end": 8.2, "syllables": 2},
    ]

    res = apply_slice_to_project(
        title=title,
        start=5.0,
        end=8.5,
        words=new_slice_words,
        work_dir=tmp_path,
    )

    assert res["status"] == "applied"
    all_res_words = [w["text"] for line in res["lines"] for w in line]
    assert "Начало" in all_res_words
    assert "новый" in all_res_words
    assert "правильный" in all_res_words
    assert "вокал" in all_res_words
    assert "Конец" in all_res_words
    assert "старый" not in all_res_words
    assert "текст" not in all_res_words

    # Verify state saved to disk
    updated_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "новый" in updated_state["editor_text"]
