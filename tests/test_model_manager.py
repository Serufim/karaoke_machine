from karaoke.model_manager import (
    MODEL_CATALOG,
    get_models_status_list,
    is_model_downloaded,
)


def test_catalog_structure():
    assert len(MODEL_CATALOG) >= 8
    assert "large-v3-turbo" in MODEL_CATALOG
    assert "htdemucs" in MODEL_CATALOG

    turbo = MODEL_CATALOG["large-v3-turbo"]
    assert turbo.download_size_mb > 500
    assert turbo.min_vram_gb >= 2.0
    assert turbo.type == "whisper"


def test_models_status_list():
    status_list = get_models_status_list()
    assert len(status_list) == len(MODEL_CATALOG)
    for item in status_list:
        assert "id" in item
        assert "is_downloaded" in item
        assert "status" in item
        assert item["status"] in ("ready", "not_downloaded", "downloading", "error")
