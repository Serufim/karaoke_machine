"""Exercise the actual embedded player logic without requiring media codecs."""
import ast
import shutil
import subprocess
from pathlib import Path

import pytest


def test_live_vocal_transport_and_controls(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for browser JavaScript regressions')
    module = ast.parse((Path(__file__).parents[1] / 'src/karaoke/app_ui.py').read_text())
    studio_js = next(ast.literal_eval(n.value) for n in module.body
                     if isinstance(n, ast.Assign) and any(
                         isinstance(t, ast.Name) and t.id == 'STUDIO_JS' for t in n.targets))
    harness = r'''
const assert = require('node:assert/strict');
let source = 'http://localhost/vocals-first.wav';
const listeners = {};
const video = {paused: true, ended: false, currentTime: 12, duration: 120,
 volume: 1, playbackRate: 1, addEventListener() {}, removeEventListener() {}};
const nativeAudio = {paused: true, currentSrc: '', pause() {this.paused = true;}};
const container = {querySelector(s) {return s === 'audio' ? nativeAudio : (source ? {href: source} : null);}};
global.window = {};
global.document = {
 querySelector(s) {return s === '#karaoke-main-video video' ? video : s === '#karaoke-vocal-audio' ? container : null;},
 getElementById() {return null;},
 addEventListener(name, fn) {listeners[name] = fn;}
};
global.setInterval = () => {};
global.Audio = class {
 constructor() {this.paused = true; this.currentTime = 0; this.playbackRate = 1; this.seeking = false; this.src = '';}
 getAttribute() {return this.src || null;}
 removeAttribute() {this.src = '';}
 pause() {this.paused = true;}
 load() {this.currentTime = 0;}
 play() {this.paused = false; return Promise.resolve();}
};
'''
    checks = r'''
(async () => {
 const s = window.__karaokeStudio;
 s.checkDomDataBox = s.initCanvasEvents = s.renderTimeline = s.updatePlayButtonLabel = () => {};
 s.tick();
 const audio = s.getMedia().audio;
 assert.equal(audio.src, source); // Gradio's native audio has no source.
 assert.equal(audio.currentTime, 12);
 assert.equal(audio.volume, 0); // No automatic 10% floor on live playback.
 assert.equal(audio.paused, true);
 video.paused = false;
 listeners.input({target: {value: '75', closest: (id) => id === '#live-vocal-slider'}});
 assert.equal(audio.volume, .75);
 assert.equal(audio.paused, false);
 await new Promise(r => setImmediate(r));
 video.currentTime = 40; video.playbackRate = 1.5; s.tick();
 assert.equal(audio.currentTime, 40);
 assert.equal(audio.playbackRate, 1.5);
 video.paused = true; s.tick(); assert.equal(audio.paused, true);
 source = 'http://localhost/vocals-second.wav'; s.tick();
 assert.equal(audio.src, source); assert.equal(audio.paused, true);
 video.paused = false;
 listeners.input({target: {value: '0', closest: (id) => id === '#live-vocal-slider'}});
 assert.equal(audio.volume, 0); assert.equal(audio.muted, true); assert.equal(audio.paused, true);
 listeners.input({target: {value: '0', closest: (id) => id === '#live-video-vol-slider'}});
 assert.equal(video.volume, 0);
 source = ''; s.tick(); assert.equal(audio.src, ''); assert.equal(audio.paused, true);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    script = tmp_path / 'live_audio.cjs'
    script.write_text(harness + '\n(' + studio_js + ')();\n' + checks)
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True)
