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
