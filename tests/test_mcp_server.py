import json
from pathlib import Path
from karaoke import mcp_server


def test_mcp_hardware_and_models():
    hw = mcp_server.get_hardware_profile()
    assert "platform" in hw
    assert "gpu_type" in hw
    assert hw["gpu_type"] in ["cuda", "mps", "cpu"]

    catalog = mcp_server.get_models_catalog()
    assert "models" in catalog
    assert len(catalog["models"]) > 0


def test_mcp_project_management(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "WORK_DIR", tmp_path)
    monkeypatch.setattr(mcp_server, "OUTPUT_DIR", tmp_path)

    title = "test_mcp_song"
    state_file = tmp_path / f"{title}_state.json"
    state_file.write_text(
        json.dumps({
            "title": title,
            "duration": 42.0,
            "lines": [
                [{"text": "Строка", "start": 1.0, "end": 2.0}, {"text": "один", "start": 2.0, "end": 3.0}],
                [{"text": "Строка", "start": 4.0, "end": 5.0}, {"text": "два", "start": 5.0, "end": 6.0}],
            ],
            "editor_text": "[00:01.00 -> 00:03.00] Строка один\n[00:04.00 -> 00:06.00] Строка два",
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    # 1. list_projects
    projs = mcp_server.list_projects()
    assert len(projs) == 1
    assert projs[0]["title"] == title
    assert projs[0]["duration"] == 42.0
    assert projs[0]["lines_count"] == 2

    # 2. get_project
    proj = mcp_server.get_project(title)
    assert proj["title"] == title
    assert proj["duration"] == 42.0
    assert "Строка один" in proj["editor_text"]

    # 3. update_project_lyrics
    new_text = "[00:01.00 -> 00:03.00] Новая строка\n[00:04.00 -> 00:06.00] Вторая строка"
    res_up = mcp_server.update_project_lyrics(title, new_text)
    assert res_up["status"] == "success"
    assert "Новая строка" in res_up["editor_text"]

    # 4. shift_line_timing
    res_shift = mcp_server.shift_line_timing(title, 0, 1.5, 3.5)
    assert res_shift["status"] == "success"
    assert res_shift["new_start"] == 1.5
    assert res_shift["new_end"] == 3.5
