from pathlib import Path

import pytest
from PIL import Image

from karaoke import app_ui


@pytest.mark.parametrize('upload', ['song.mp3', 'clip.mp4', None])
def test_unified_upload_reaches_pipeline_with_render_settings(monkeypatch, tmp_path, upload):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def analyze(**kwargs):
        captured['analysis'] = kwargs
        return {'title': 'fixture', 'editor_text': '', 'lines': [], 'video_bg': upload}

    def render(**kwargs):
        captured['render'] = kwargs
        return Path('result.mp4'), Path('mix.wav'), ''

    monkeypatch.setattr(app_ui, 'analyze_and_transcribe', analyze)
    monkeypatch.setattr(app_ui, 'render_from_state', render)
    app_ui.run_full_karaoke_ui(
        url_input='https://example.test/song', file_input=upload,
        bg_input='background.png', use_cover_bg=False, use_video_bg=False,
        cookies_browser='none', cookies_file=None, fx_mode='none',
        edge_color_mode='fire', font_size_mode='large', highlight_color='electric_cyan',
        video_quality='light', reference_lyrics='', vocal_volume_pct=0,
        num_lines=3, model_size='large-v3-turbo', demucs_model='htdemucs',
        language='ru', use_ctc_align=False,
    )
    assert captured['analysis']['source'] == (upload or 'https://example.test/song')
    assert captured['render']['vocal_volume'] == 0
    assert captured['render']['background'] == Path('background.png')
    assert captured['render']['visual_effects'] == 'none'
    assert captured['render']['num_lines'] == 3


def test_background_preview_upload_replace_and_clear(tmp_path):
    picture = tmp_path / 'фон.png'
    Image.new('RGB', (40, 20), 'blue').save(picture)
    result = app_ui.preview_background_image(str(picture))
    assert result['value'] == str(picture) and result['visible']
    non_image = tmp_path / 'clip.mp4'
    non_image.write_bytes(b'not an image')
    for value in (str(non_image), None):
        result = app_ui.preview_background_image(value)
        assert result['value'] is None and not result['visible']
