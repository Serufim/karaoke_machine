import json
from fastapi.testclient import TestClient
from karaoke.server import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_models_list():
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "demucs" in data
    assert "whisper" in data
    assert "htdemucs" in data["demucs"]
    assert "large-v3-turbo" in data["whisper"]


def test_projects_list():
    response = client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert "projects" in data
    assert isinstance(data["projects"], list)


def test_regroup_lines():
    sample_text = "[00:01.00 -> 00:02.00] Привет\n[00:02.50 -> 00:04.00] мир!"
    response = client.post(
        "/api/tools/regroup-lines",
        json={"editor_text": sample_text},
    )
    assert response.status_code == 200
    data = response.json()
    assert "editor_text" in data
    assert "lines" in data


def test_split_lines():
    sample_text = "[00:01.00 -> 00:08.00] Я помню чудное мгновенье передо мной явилась ты как мимолетное виденье"
    response = client.post(
        "/api/tools/split-lines",
        json={"editor_text": sample_text, "max_chars": 35, "max_words": 6},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["original_count"] == 1
    assert data["new_count"] > 1
    assert data["split_count"] > 0
    assert len(data["lines"]) == data["new_count"]


def test_get_nonexistent_project():
    response = client.get("/api/projects/non_existent_project_123456")
    assert response.status_code == 404


def test_hardware_profile_endpoint():
    response = client.get("/api/system/hardware")
    assert response.status_code == 200
    data = response.json()
    assert "platform" in data
    assert "cpu_cores" in data
    assert data["cpu_cores"] > 0
    assert "ram_gb" in data
    assert data["ram_gb"] > 0
    assert "gpu_type" in data
    assert data["gpu_type"] in ["cuda", "mps", "cpu"]
    assert "tier" in data
    assert data["tier"] in ["ultra", "high", "medium", "low"]
    assert "recommended_whisper" in data
    assert "recommended_demucs" in data


def test_models_catalog_endpoint():
    response = client.get("/api/models/catalog")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert len(data["models"]) >= 5
    ids = [m["id"] for m in data["models"]]
    assert "large-v3-turbo" in ids
    assert "htdemucs" in ids
    for m in data["models"]:
        assert "min_vram_gb" in m
        assert "download_size_mb" in m
        assert "status" in m



def test_upload_cover_image(tmp_path):
    import io
    import json
    from pathlib import Path
    from PIL import Image

    work_dir = Path("./output/work").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    title = "_test_auto_cover_project_"
    state_file = work_dir / f"{title}_state.json"
    cover_file = work_dir / f"{title}_cover.png"

    # Create dummy project state
    state_file.write_text(json.dumps({"title": title, "duration": 10.0}), encoding="utf-8")

    try:
        # Create small test image
        img = Image.new("RGB", (64, 64), color=(255, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        response = client.post(
            f"/api/projects/{title}/cover",
            files={"file": ("test_cover.png", img_bytes, "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "cover_url" in data
        assert "cover_edge_colors" in data
        assert cover_file.exists()
    finally:
        if state_file.exists():
            state_file.unlink()
        if cover_file.exists():
            cover_file.unlink()


def test_export_dj_pack_endpoint(tmp_path):
    import json
    from pathlib import Path
    import numpy as np
    import soundfile as sf

    output_dir = Path("./output").resolve()
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    title = "_test_dj_pack_api_"
    state_file = work_dir / f"{title}_state.json"

    sr = 44100
    t = np.linspace(0, 1.5, int(sr * 1.5), endpoint=False)
    inst_wav = tmp_path / "inst.wav"
    voc_wav = tmp_path / "voc.wav"
    sf.write(str(inst_wav), (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr)
    sf.write(str(voc_wav), (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr)

    lines = [[{"text": "Тест", "start": 0.2, "end": 0.8}, {"text": "диджей", "start": 0.85, "end": 1.3}]]
    state_data = {
        "title": title,
        "vocals_wav": str(voc_wav),
        "no_vocals_wav": str(inst_wav),
        "lines": lines,
        "editor_text": "[00:00.20 -> 00:01.30] Тест диджей",
        "duration": 1.5,
        "vocal_intervals": [],
        "fx_intervals": [],
    }
    state_file.write_text(json.dumps(state_data, ensure_ascii=False), encoding="utf-8")

    try:
        res = client.post(
            f"/api/projects/{title}/export-dj-pack",
            json={"vocal_volume": 0.1},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["dj_pack_filename"] == f"{title}_DJ_Pack.zip"
        assert data["kfn_filename"] == f"{title}.kfn"

        res_kfn = client.get(data["kfn_url"])
        assert res_kfn.status_code == 200
        assert res_kfn.content[:4] == b"KFNB"

        res_zip = client.get(data["dj_pack_url"])
        assert res_zip.status_code == 200
        assert len(res_zip.content) > 1024
    finally:
        for f in [
            state_file,
            output_dir / f"{title}.kfn",
            output_dir / f"{title}.lrc",
            output_dir / f"{title}_ultrastar.txt",
            output_dir / f"{title}_DJ_Pack.zip",
            work_dir / f"{title}_cdg.zip",
            work_dir / f"{title}_mix_10pct.wav",
            work_dir / f"{title}_instrumental.mp3",
            work_dir / f"{title}_vocals.mp3",
        ]:
            f.unlink(missing_ok=True)


def test_rebuild_preserves_fx_intervals_in_state(tmp_path):
    import json
    from pathlib import Path

    output_dir = Path("./output").resolve()
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    title = "_test_rebuild_fx_persist_"
    state_file = work_dir / f"{title}_state.json"

    initial_state = {
        "title": title,
        "vocals_wav": str(tmp_path / "vocals.wav"),
        "no_vocals_wav": str(tmp_path / "no_vocals.wav"),
        "lines": [],
        "editor_text": "",
        "duration": 5.0,
        "vocal_intervals": [],
        "fx_intervals": [],
    }
    state_file.write_text(json.dumps(initial_state, ensure_ascii=False), encoding="utf-8")

    try:
        new_fx = [{"start": 1.0, "end": 4.0, "effect": "sparkles_pulse", "intensity": 0.9}]
        new_vocal = [{"start": 2.0, "end": 3.5, "volume": 0.6}]

        # Send rebuild request with new intervals
        res = client.post(
            "/api/pipeline/rebuild",
            json={
                "title": title,
                "fx_intervals": new_fx,
                "vocal_intervals": new_vocal,
                "editor_text": "[00:01.00 -> 00:04.00] Припев с эффектами",
                "use_cover_bg": True,
            },
        )
        assert res.status_code == 200

        # Verify state on disk is immediately updated and preserved
        updated_state = json.loads(state_file.read_text(encoding="utf-8"))
        assert updated_state["fx_intervals"] == new_fx
        assert updated_state["vocal_intervals"] == new_vocal
        assert updated_state["use_cover_bg"] is True
        assert "[00:01.00 -> 00:04.00]" in updated_state["editor_text"]
    finally:
        state_file.unlink(missing_ok=True)


def test_system_folder_endpoints():
    res = client.get("/api/system/folders")
    assert res.status_code == 200
    data = res.json()
    assert "presets" in data
    assert "default" in data
    assert "output" in data["presets"]

    res_open = client.post("/api/system/open-folder", json={"path": "./output"})
    assert res_open.status_code == 200
    assert res_open.json()["status"] == "opened"


def test_charts_endpoints():
    # 1. Yandex chart
    res_ya = client.get("/api/charts?platform=yandex&limit=5")
    assert res_ya.status_code == 200
    ya_data = res_ya.json()
    assert ya_data["platform"] == "yandex"
    assert ya_data["status"] in ("ok", "error")
    if ya_data["status"] == "ok":
        assert len(ya_data["tracks"]) > 0
        t0 = ya_data["tracks"][0]
        assert "rank" in t0
        assert "title" in t0
        assert "artist" in t0

    # 2. Apple Music chart
    res_apple = client.get("/api/charts?platform=apple&country=ru&limit=5")
    assert res_apple.status_code == 200
    apple_data = res_apple.json()
    assert apple_data["platform"] == "apple"
    assert apple_data["status"] in ("ok", "error")

    # 3. Spotify chart
    res_sp = client.get("/api/charts?platform=spotify&limit=5")
    assert res_sp.status_code == 200
    sp_data = res_sp.json()
    assert sp_data["platform"] == "spotify"
    assert sp_data["status"] in ("ok", "error")

    # 4. Zvuk protection status
    res_zvuk = client.get("/api/charts?platform=zvuk")
    assert res_zvuk.status_code == 200
    zvuk_data = res_zvuk.json()
    assert zvuk_data["status"] == "protected"
    assert "Servicepipe" in zvuk_data["description"]

    # 5. VK auth required status
    res_vk = client.get("/api/charts?platform=vk")
    assert res_vk.status_code == 200
    vk_data = res_vk.json()
    assert vk_data["status"] == "auth_required"


def test_slice_align_and_apply_endpoints(tmp_path, monkeypatch):
    from karaoke.api import routes
    monkeypatch.setattr(routes, "WORK_DIR", tmp_path)

    title = "test_slice_proj"
    state_file = tmp_path / f"{title}_state.json"
    state_file.write_text(
        json.dumps({
            "title": title,
            "lines": [[{"text": "старый", "start": 1.0, "end": 2.0}]],
            "editor_text": "[00:01.00 -> 00:02.00] старый",
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    # 1. Align slice
    res_align = client.post(
        "/api/tools/slice-align",
        json={
            "title": title,
            "start": 10.0,
            "end": 13.0,
            "text": "новый крутой вокал",
            "mode": "syllables_rms",
        }
    )
    assert res_align.status_code == 200
    align_data = res_align.json()
    assert align_data["status"] == "ok"
    assert len(align_data["words"]) == 3

    # 2. Apply slice
    res_apply = client.post(
        "/api/tools/slice-apply",
        json={
            "title": title,
            "start": 10.0,
            "end": 13.0,
            "words": align_data["words"],
        }
    )
    assert res_apply.status_code == 200
    apply_data = res_apply.json()
    assert apply_data["status"] == "applied"
    assert "новый" in apply_data["editor_text"]


def test_project_state_reconstruction_and_generation_params(tmp_path, monkeypatch):
    from karaoke.api import routes
    monkeypatch.setattr(routes, "WORK_DIR", tmp_path)

    title = "test_params_proj"
    state_file = tmp_path / f"{title}_state.json"
    state_file.write_text(
        json.dumps({
            "title": title,
            "lines": [[{"text": "Строка", "start": 1.0, "end": 2.0}]],
            "editor_text": "[00:01.00 -> 00:02.00] Строка первая\n[00:03.00 -> 00:04.00] Строка вторая",
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    response = client.get(f"/api/projects/{title}")
    assert response.status_code == 200
    data = response.json()
    assert "reference_lyrics" in data
    assert "Строка первая" in data["reference_lyrics"]
    assert "Строка вторая" in data["reference_lyrics"]
    assert "[" not in data["reference_lyrics"]  # timestamps stripped
    assert "generation_params" in data
    assert data["generation_params"]["model_size"] == "large-v3-turbo"


def test_pipeline_generate_existing_project(tmp_path, monkeypatch):
    from karaoke.api import routes
    monkeypatch.setattr(routes, "WORK_DIR", tmp_path)

    title = "test_regen_proj"
    audio_file = tmp_path / f"{title}_source.wav"
    audio_file.write_bytes(b"dummy audio data")

    state_file = tmp_path / f"{title}_state.json"
    state_file.write_text(
        json.dumps({
            "title": title,
            "source_audio": str(audio_file),
            "lines": [],
            "editor_text": "",
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    # Mock _run_generate_task so it doesn't actually run heavy AI models in test
    called_args = []
    def dummy_run_task(*args, **kwargs):
        called_args.append(args)

    monkeypatch.setattr(routes, "_run_generate_task", dummy_run_task)

    response = client.post(
        "/api/pipeline/generate",
        data={
            "existing_project_title": title,
            "model_size": "bond005/whisper-podlodka-turbo",
            "reference_lyrics": "Тестовый текст песни",
            "use_ctc_align": "true",
            "vad": "auditok",
        }
    )
    assert response.status_code == 200
    assert len(called_args) == 1
    args = called_args[0]
    # source should match audio_file
    assert str(audio_file) in args[0]
    assert args[1] == "bond005/whisper-podlodka-turbo"
    assert args[4] == "Тестовый текст песни"
    assert args[5] is True  # use_ctc_align




