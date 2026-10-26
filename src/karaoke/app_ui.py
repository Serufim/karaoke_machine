import json
import inspect
from pathlib import Path
from typing import Optional, Dict, Any, List
import gradio as gr

from karaoke.cli import analyze_and_transcribe, render_from_state
from karaoke.aligner import (
    editor_text_to_lines,
    lines_to_editor_text,
    regroup_editor_lines,
    split_long_editor_lines,
)
from karaoke.separator import DEMUCS_MODELS
from karaoke.transcriber import WHISPER_MODELS
from karaoke.downloader import ensure_project_cover
from karaoke.mixer import (
    compute_waveform_peaks,
    detect_chorus_fx_intervals,
)
from karaoke.video import extract_cover_edge_colors
from karaoke.cancel_manager import (
    reset_cancel,
    request_cancel,
    GenerationCancelledError,
)


STUDIO_JS = """
() => {
    if (window.__karaokeStudioInitialized) return;
    window.__karaokeStudioInitialized = true;

    window.__karaokeStudio = {
        vocalVolBase: 0.0,
        videoVol: 1.0,
        liveVocalMultiplier: 0.0,
        vocalAudio: null,
        boundVideo: null,
        audioPlayPending: false,
        audioPlayError: '',
        instPeaks: [],
        vocalPeaks: [],
        duration: 0.0,
        vocalIntervals: [],
        fxIntervals: [],
        lines: [],
        selStart: null,
        selEnd: null,
        isDragging: false,
        dragMode: null, // 'new' | 'left' | 'right' | 'move'
        dragStartSec: 0,
        dragOrigStart: 0,
        dragOrigEnd: 0,
        loopSelection: false,
        zoomFactor: 1,
        lastJsonSignature: '',

        formatTime(sec) {
            if (!sec || isNaN(sec) || sec < 0) sec = 0;
            const totalCs = Math.round(sec * 100);
            const mins = Math.floor(totalCs / 6000);
            const rem = totalCs % 6000;
            const secs = Math.floor(rem / 100);
            const cs = rem % 100;
            return `[${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(cs).padStart(2, '0')}]`;
        },

        getMedia() {
            const video = document.querySelector('#karaoke-main-video video');
            const container = document.querySelector('#karaoke-vocal-audio');
            const nativeAudio = container?.querySelector('audio');
            // Gradio's waveform player can fail to mount and leave <audio> without
            // src. Its download link still contains the registered, served file URL.
            const source = container?.querySelector('a[download]')?.href || nativeAudio?.currentSrc || '';
            if (!this.vocalAudio) {
                this.vocalAudio = new Audio();
                this.vocalAudio.preload = 'auto';
            }
            const audio = this.vocalAudio;
            if (source !== (audio.getAttribute('src') || '')) {
                audio.pause();
                this.audioPlayError = '';
                if (source) audio.src = source;
                else audio.removeAttribute('src');
                audio.load();
            }
            // Use one playback owner; the Gradio widget is only a file transport.
            if (nativeAudio && !nativeAudio.paused) nativeAudio.pause();
            if (video && video !== this.boundVideo) {
                if (this.boundVideo) {
                    for (const event of ['play', 'pause', 'ended', 'seeking', 'seeked', 'ratechange']) {
                        this.boundVideo.removeEventListener(event, this.mediaListener);
                    }
                }
                this.boundVideo = video;
                this.mediaListener = () => this.tick();
                for (const event of ['play', 'pause', 'ended', 'seeking', 'seeked', 'ratechange']) {
                    video.addEventListener(event, this.mediaListener);
                }
            }
            return { video, audio };
        },

        syncMediaToSec(targetSec) {
            const { video, audio } = this.getMedia();
            const clamped = Math.max(0, Math.min(this.duration || 9999, Number(targetSec) || 0));
            if (video) {
                try { video.currentTime = clamped; } catch (e) {}
            }
            if (audio && audio.src) {
                try { audio.currentTime = clamped; } catch (e) {}
            }
        },

        playFromSelectionOrCursor() {
            const { video, audio } = this.getMedia();
            if (!video) {
                alert('Видео еще не загружено в плеер!');
                return;
            }
            if (!video.paused) {
                video.pause();
                if (audio) audio.pause();
                this.updatePlayButtonLabel();
                return;
            }
            if (this.selStart !== null && this.selEnd !== null) {
                const s = Math.min(this.selStart, this.selEnd);
                const e = Math.max(this.selStart, this.selEnd);
                if (video.currentTime < s || video.currentTime >= e - 0.08) {
                    this.syncMediaToSec(s);
                }
            }
            video.play().catch(() => {});
            this.updatePlayButtonLabel();
        },

        playFromSelectionStart() {
            const { video } = this.getMedia();
            if (!video) return;
            if (this.selStart !== null && this.selEnd !== null) {
                const s = Math.min(this.selStart, this.selEnd);
                this.syncMediaToSec(s);
            } else {
                this.syncMediaToSec(0);
            }
            video.play().catch(() => {});
            this.updatePlayButtonLabel();
        },

        toggleLoop() {
            this.loopSelection = !this.loopSelection;
            const btn = document.getElementById('btn-tl-loop');
            if (btn) {
                btn.style.background = this.loopSelection ? '#0284c7' : '#1e293b';
                btn.style.borderColor = this.loopSelection ? '#38bdf8' : '#475569';
                btn.textContent = this.loopSelection ? '🔁 Петля: ВКЛ' : '🔁 Петля: ВЫКЛ';
            }
        },

        toggleLeftDrawer(force) {
            const d = document.getElementById('studio-drawer-left');
            const b = document.getElementById('studio-drawer-backdrop');
            if (!d) return;
            const isOpen = d.classList.contains('open');
            const toOpen = force !== undefined ? force : !isOpen;
            if (toOpen) {
                d.classList.add('open');
                if (b) b.classList.add('active');
            } else {
                d.classList.remove('open');
                const rightD = document.getElementById('studio-drawer-right');
                if (b && (!rightD || !rightD.classList.contains('open'))) {
                    b.classList.remove('active');
                }
            }
        },

        toggleRightDrawer(force) {
            const d = document.getElementById('studio-drawer-right');
            const b = document.getElementById('studio-drawer-backdrop');
            if (!d) return;
            const isOpen = d.classList.contains('open');
            const toOpen = force !== undefined ? force : !isOpen;
            if (toOpen) {
                d.classList.add('open');
                if (b) b.classList.add('active');
            } else {
                d.classList.remove('open');
                const leftD = document.getElementById('studio-drawer-left');
                if (b && (!leftD || !leftD.classList.contains('open'))) {
                    b.classList.remove('active');
                }
            }
        },

        closeDrawers() {
            this.toggleLeftDrawer(false);
            this.toggleRightDrawer(false);
        },

        setZoom(factor) {
            this.zoomFactor = Math.max(1, Math.min(8, Number(factor) || 1));
            const canvas = document.getElementById('karaoke-studio-canvas');
            if (canvas) {
                const baseWidth = Math.max(1600, (canvas.parentElement ? canvas.parentElement.clientWidth : 1600));
                canvas.width = baseWidth * this.zoomFactor;
                canvas.style.width = (100 * this.zoomFactor) + '%';
            }
            [1, 2, 4].forEach(z => {
                const b = document.getElementById('btn-tl-zoom-' + z);
                if (b) {
                    b.style.background = (this.zoomFactor === z) ? '#0284c7' : '#1e293b';
                }
            });
            this.renderTimeline();
        },

        updatePlayButtonLabel() {
            const { video } = this.getMedia();
            const btn = document.getElementById('btn-tl-play');
            if (!btn) return;
            if (video && !video.paused && !video.ended) {
                btn.innerHTML = '⏸️ Пауза';
                btn.style.background = '#dc2626';
            } else {
                btn.innerHTML = '▶️ Пуск с момента';
                btn.style.background = '#16a34a';
            }
        },

        setGradioTextboxValue(el, strVal) {
            if (!el || el.value === strVal) return;
            const proto = el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) {
                desc.set.call(el, strVal);
            } else {
                el.value = strVal;
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        },

        checkDomDataBox() {
            const box = document.querySelector('#studio-timeline-data-json textarea, #studio-timeline-data-json input');
            if (!box || !box.value) return;
            const raw = box.value.trim();
            if (!raw || raw === this.lastJsonSignature) return;
            this.lastJsonSignature = raw;
            try {
                const parsed = JSON.parse(raw);
                this.loadProjectData(parsed, raw);
            } catch (e) {
                console.warn('[KaraokeStudio] Failed to parse timeline JSON:', e);
            }
        },

        loadProjectData(stateData, rawSignature = null) {
            if (!stateData) return;
            if (typeof stateData === 'string') {
                rawSignature = stateData.trim();
                try { stateData = JSON.parse(stateData); } catch (e) { return; }
            }
            if (rawSignature) {
                this.lastJsonSignature = rawSignature;
            }
            const box = document.querySelector('#studio-timeline-data-json textarea, #studio-timeline-data-json input');
            if (box && box.value) {
                this.lastJsonSignature = box.value.trim();
            }

            this.duration = Number(stateData.duration) || 0;
            this.instPeaks = Array.isArray(stateData.inst_peaks) ? stateData.inst_peaks : [];
            this.vocalPeaks = Array.isArray(stateData.vocal_peaks) ? stateData.vocal_peaks : [];
            this.vocalIntervals = Array.isArray(stateData.vocal_intervals) ? stateData.vocal_intervals : [];
            this.fxIntervals = Array.isArray(stateData.fx_intervals) ? stateData.fx_intervals : [];

            const rawLines = Array.isArray(stateData.lines) ? stateData.lines : [];
            this.lines = rawLines.map(line => {
                if (Array.isArray(line)) {
                    return {
                        start: Number(line[0]?.start ?? 0),
                        end: Number(line[line.length - 1]?.end ?? 0),
                        text: line.map(w => w.text || '').join(' ').trim()
                    };
                }
                return {
                    start: Number(line.start ?? 0),
                    end: Number(line.end ?? 0),
                    text: String(line.text ?? '')
                };
            }).filter(l => l.end > l.start);

            if (!this.duration && this.lines.length > 0) {
                this.duration = this.lines[this.lines.length - 1].end + 5.0;
            }

            this.selStart = null;
            this.selEnd = null;
            this.syncInputsToGradio();
            this.renderTimeline();
        },

        syncInputsToGradio() {
            const vBox = document.querySelector('#vocal-intervals-json textarea, #vocal-intervals-json input');
            const fBox = document.querySelector('#fx-intervals-json textarea, #fx-intervals-json input');
            const vStr = JSON.stringify(this.vocalIntervals || []);
            const fStr = JSON.stringify(this.fxIntervals || []);
            if (vBox) {
                this.setGradioTextboxValue(vBox, vStr);
            }
            if (fBox) {
                this.setGradioTextboxValue(fBox, fStr);
            }
            const info = document.getElementById('timeline-sel-info');
            if (info) {
                if (this.selStart !== null && this.selEnd !== null) {
                    const s = Math.min(this.selStart, this.selEnd);
                    const e = Math.max(this.selStart, this.selEnd);
                    let snippet = '';
                    for (const ln of this.lines) {
                        if (ln.end > s + 0.1 && ln.start < e - 0.1) {
                            snippet = ln.text;
                            break;
                        }
                    }
                    const snipHtml = snippet ? ` — <span style="color:#fde047">"${snippet.slice(0, 48)}"</span>` : '';
                    info.innerHTML = `🎯 Выделено: <strong style="color:#38bdf8">${this.formatTime(s)} ➔ ${this.formatTime(e)}</strong> (${(e - s).toFixed(2)} сек)${snipHtml}`;
                } else {
                    info.innerHTML = `💡 Потяните мышкой по любой дорожке для выделения участка или кликните по голубой плашке фразы (Длительность трека: <strong>${this.formatTime(this.duration)}</strong>)`;
                }
            }
        },

        setSelectionVocal(volume) {
            if (this.selStart === null || this.selEnd === null) {
                alert('Сначала выделите участок на таймлайне мышкой или кликните по фразе на Дорожке 1!');
                return;
            }
            const s = Number(Math.min(this.selStart, this.selEnd).toFixed(2));
            const e = Number(Math.max(this.selStart, this.selEnd).toFixed(2));
            if (e - s < 0.15) return;

            // Remove or trim overlapping intervals
            const updated = [];
            for (const itv of this.vocalIntervals) {
                if (itv.end <= s || itv.start >= e) {
                    updated.push(itv);
                } else {
                    if (itv.start < s) updated.push({ start: itv.start, end: s, volume: itv.volume });
                    if (itv.end > e) updated.push({ start: e, end: itv.end, volume: itv.volume });
                }
            }
            if (volume !== null) {
                updated.push({ start: s, end: e, volume: Number(volume) });
                updated.sort((a, b) => a.start - b.start);
            }
            this.vocalIntervals = updated;
            const customSlider = document.getElementById('tl-custom-vocal-range');
            const customLabel = document.getElementById('tl-custom-vocal-val');
            if (volume !== null && customSlider && customLabel) {
                const pct = Math.round(Number(volume) * 100);
                customSlider.value = pct;
                customLabel.textContent = pct + '%';
            }
            this.syncInputsToGradio();
            this.renderTimeline();
        },

        setSelectionFX(effect, intensity = 0.85, emojis = null) {
            if (this.selStart === null || this.selEnd === null) {
                alert('Сначала выделите участок на таймлайне мышкой или кликните по фразе на Дорожке 1!');
                return;
            }
            const s = Number(Math.min(this.selStart, this.selEnd).toFixed(2));
            const e = Number(Math.max(this.selStart, this.selEnd).toFixed(2));
            if (e - s < 0.15) return;

            const updated = [];
            for (const itv of this.fxIntervals) {
                if (itv.end <= s || itv.start >= e) {
                    updated.push(itv);
                } else {
                    if (itv.start < s) updated.push({ start: itv.start, end: s, effect: itv.effect, intensity: itv.intensity, emojis: itv.emojis });
                    if (itv.end > e) updated.push({ start: e, end: itv.end, effect: itv.effect, intensity: itv.intensity, emojis: itv.emojis });
                }
            }
            if (effect !== null) {
                const item = { start: s, end: e, effect, intensity: Number(intensity) };
                if (emojis) item.emojis = emojis;
                updated.push(item);
                updated.sort((a, b) => a.start - b.start);
            }
            this.fxIntervals = updated;
            this.syncInputsToGradio();
            this.renderTimeline();
        },

        applyCustomEmojiFX() {
            const input = document.getElementById('tl-custom-emoji-input');
            const ems = (input && input.value ? input.value.trim() : '') || '🔥';
            this.setSelectionFX('emoji_burst', 0.90, ems);
        },

        clearAll() {
            this.vocalIntervals = [];
            this.fxIntervals = [];
            this.selStart = null;
            this.selEnd = null;
            this.syncInputsToGradio();
            this.renderTimeline();
        },

        getEffectiveVocalVolume(currTime) {
            for (const itv of this.vocalIntervals) {
                if (currTime >= itv.start && currTime <= itv.end) {
                    return Number(itv.volume);
                }
            }
            return this.vocalVolBase;
        },

        renderTimeline() {
            const canvas = document.getElementById('karaoke-studio-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;
            const { video } = this.getMedia();
            const dur = Math.max(1, this.duration || (video && video.duration) || 60);

            ctx.clearRect(0, 0, w, h);

            // Background zones
            ctx.fillStyle = '#0f172a';
            ctx.fillRect(0, 0, w, h);

            // Track layout (height 172px):
            // 0..22: Time ruler
            // 22..72: Track 1 (Instrumental + Lyric phrase blocks)
            // 74..124: Track 2 (Vocals + Vocal Volume Automation)
            // 126..172: Track 3 (Visual FX Intervals)
            ctx.fillStyle = '#1e293b';
            ctx.fillRect(0, 0, w, 22);
            ctx.fillStyle = '#090d16';
            ctx.fillRect(0, 22, w, 50);
            ctx.fillStyle = '#111827';
            ctx.fillRect(0, 74, w, 50);
            ctx.fillStyle = '#191538';
            ctx.fillRect(0, 126, w, 46);

            // Track labels on left
            ctx.fillStyle = 'rgba(15, 23, 42, 0.78)';
            ctx.fillRect(4, 24, 108, 15);
            ctx.fillRect(4, 76, 108, 15);
            ctx.fillRect(4, 128, 108, 15);
            ctx.font = 'bold 10px sans-serif';
            ctx.fillStyle = '#38bdf8';
            ctx.fillText('🎵 1. МИНУС + ФРАЗЫ', 8, 35);
            ctx.fillStyle = '#fbbf24';
            ctx.fillText('🎤 2. ВОКАЛ %', 8, 87);
            ctx.fillStyle = '#c084fc';
            ctx.fillText('✨ 3. ЭФФЕКТЫ FX', 8, 139);

            // Time ruler ticks
            ctx.fillStyle = '#94a3b8';
            ctx.font = '10px monospace';
            const stepSec = Math.max(5, Math.round((dur > 180 ? 20 : 10) / this.zoomFactor));
            for (let sec = 0; sec <= dur; sec += stepSec) {
                const x = (sec / dur) * w;
                ctx.fillStyle = '#475569';
                ctx.fillRect(x, 0, 1, 22);
                ctx.fillStyle = 'rgba(71, 85, 105, 0.22)';
                ctx.fillRect(x, 22, 1, h - 22);
                const m = Math.floor(sec / 60);
                const s = Math.floor(sec % 60);
                ctx.fillStyle = '#cbd5e1';
                ctx.fillText(`${m}:${String(s).padStart(2, '0')}`, x + 4, 14);
            }

            // Track 1: Instrumental waveform (Y center = 52)
            if (this.instPeaks.length > 0) {
                ctx.fillStyle = 'rgba(2, 132, 199, 0.65)';
                const nBins = this.instPeaks.length;
                for (let i = 0; i < nBins; i++) {
                    const x = (i / nBins) * w;
                    const bW = Math.max(1.2, (w / nBins) * 0.9);
                    const bH = Math.max(2, this.instPeaks[i] * 38);
                    ctx.fillRect(x, 51 - bH / 2, bW, bH);
                }
            }

            // Lyric phrase blocks on Track 1 (Y: 23..42)
            for (const ln of this.lines) {
                const x1 = (ln.start / dur) * w;
                const x2 = (ln.end / dur) * w;
                const pw = Math.max(4, x2 - x1);
                ctx.fillStyle = 'rgba(56, 189, 248, 0.28)';
                ctx.fillRect(x1, 24, pw, 18);
                ctx.strokeStyle = '#38bdf8';
                ctx.lineWidth = 1;
                ctx.strokeRect(x1, 24, pw, 18);
                if (pw > 38) {
                    ctx.fillStyle = '#e0f2fe';
                    ctx.font = '10px sans-serif';
                    const maxChars = Math.max(3, Math.floor(pw / 6.5));
                    ctx.fillText(ln.text.slice(0, maxChars), x1 + 3, 36);
                }
            }

            // Track 2: Vocal waveform (Y center = 99)
            if (this.vocalPeaks.length > 0) {
                ctx.fillStyle = 'rgba(245, 158, 11, 0.55)';
                const nBins = this.vocalPeaks.length;
                for (let i = 0; i < nBins; i++) {
                    const x = (i / nBins) * w;
                    const bW = Math.max(1.2, (w / nBins) * 0.9);
                    const bH = Math.max(2, this.vocalPeaks[i] * 40);
                    ctx.fillRect(x, 99 - bH / 2, bW, bH);
                }
            }

            // Vocal automation overlay blocks on Track 2 (Y: 74..124)
            for (const itv of this.vocalIntervals) {
                const x1 = (itv.start / dur) * w;
                const x2 = (itv.end / dur) * w;
                const blockW = Math.max(4, x2 - x1);
                const vol = Number(itv.volume ?? 0);
                const fillH = Math.max(8, Math.round(vol * 46));
                const fillY = 124 - fillH;
                ctx.fillStyle = vol > 0.02 ? 'rgba(234, 88, 12, 0.72)' : 'rgba(71, 85, 105, 0.75)';
                ctx.fillRect(x1, fillY, blockW, fillH);
                ctx.strokeStyle = vol > 0.02 ? '#fb923c' : '#94a3b8';
                ctx.lineWidth = 1.5;
                ctx.strokeRect(x1, 74, blockW, 50);
                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 10px sans-serif';
                ctx.fillText(`🎤 ${Math.round(vol * 100)}%`, x1 + 4, 90);
            }

            // Track 3: FX Intervals (Y: 126..172)
            for (const itv of this.fxIntervals) {
                const x1 = (itv.start / dur) * w;
                const x2 = (itv.end / dur) * w;
                const blockW = Math.max(4, x2 - x1);
                let col = 'rgba(147, 51, 234, 0.72)';
                let label = '✨ Блестки+Пульс';
                if (itv.effect === 'sparkles') { col = 'rgba(202, 138, 4, 0.78)'; label = '🌟 Блестки'; }
                else if (itv.effect === 'pulse') { col = 'rgba(8, 145, 178, 0.78)'; label = '💓 Неон-Пульс'; }
                else if (itv.effect === 'climax') { col = 'rgba(219, 39, 119, 0.85)'; label = '🔥 ПРИПЕВ MAX'; }
                else if (itv.effect === 'police_strobe') { col = 'rgba(220, 38, 38, 0.88)'; label = '🚨 Мигалка'; }
                else if (itv.effect === 'emoji_burst') {
                    col = 'rgba(234, 88, 12, 0.85)';
                    const em = itv.emojis || '🔥';
                    label = `${em} Салют эмодзи`;
                }
                else if (itv.effect === 'emoji_pulse') {
                    col = 'rgba(168, 85, 247, 0.85)';
                    const em = itv.emojis || '✨';
                    label = `${em} Эмодзи+Пульс`;
                }
                ctx.fillStyle = col;
                ctx.fillRect(x1, 126, blockW, 46);
                ctx.strokeStyle = '#f5d0fe';
                ctx.lineWidth = 1.2;
                ctx.strokeRect(x1, 126, blockW, 46);
                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 10px sans-serif';
                if (blockW > 24) {
                    ctx.fillText(label, x1 + 4, 152);
                }
            }

            // Selection region highlight + resize handles
            if (this.selStart !== null && this.selEnd !== null) {
                const s = Math.min(this.selStart, this.selEnd);
                const e = Math.max(this.selStart, this.selEnd);
                const x1 = (s / dur) * w;
                const x2 = (e / dur) * w;
                const sw = Math.max(3, x2 - x1);
                ctx.fillStyle = 'rgba(56, 189, 248, 0.24)';
                ctx.fillRect(x1, 22, sw, h - 22);
                ctx.strokeStyle = '#38bdf8';
                ctx.lineWidth = 2;
                ctx.strokeRect(x1, 22, sw, h - 22);

                // Left & Right drag handles
                ctx.fillStyle = '#38bdf8';
                ctx.fillRect(x1 - 3, 22, 6, 18);
                ctx.fillRect(x2 - 3, 22, 6, 18);
            }

            // Playhead cursor
            if (video) {
                const pX = ((video.currentTime || 0) / dur) * w;
                ctx.fillStyle = '#ef4444';
                ctx.fillRect(pX - 1, 0, 2.5, h);
                ctx.beginPath();
                ctx.moveTo(pX - 6, 0);
                ctx.lineTo(pX + 6, 0);
                ctx.lineTo(pX, 9);
                ctx.fill();
            }
        },

        initCanvasEvents() {
            const canvas = document.getElementById('karaoke-studio-canvas');
            if (!canvas || canvas.__eventsInit) return;
            canvas.__eventsInit = true;

            if (canvas.parentElement) {
                const baseW = Math.max(1600, canvas.parentElement.clientWidth || 1600);
                canvas.width = baseW * this.zoomFactor;
            }
            window.addEventListener('resize', () => {
                if (canvas && canvas.parentElement) {
                    const baseW = Math.max(1600, canvas.parentElement.clientWidth || 1600);
                    canvas.width = baseW * this.zoomFactor;
                    this.renderTimeline();
                }
            });
            window.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    this.closeDrawers();
                }
            });

            const getEffectiveDur = () => {
                const { video } = this.getMedia();
                return Math.max(1, this.duration || (video && video.duration) || 60);
            };

            const getSecFromEvent = (e) => {
                const rect = canvas.getBoundingClientRect();
                const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
                const ratio = x / Math.max(1, rect.width);
                return Math.max(0, Math.min(getEffectiveDur(), ratio * getEffectiveDur()));
            };

            canvas.addEventListener('mousedown', (e) => {
                const dur = getEffectiveDur();
                this.duration = dur;
                const sec = getSecFromEvent(e);
                const rect = canvas.getBoundingClientRect();
                const y = (e.clientY - rect.top) * (canvas.height / Math.max(1, rect.height));
                const pxPerSec = rect.width / dur;

                // 1) Check if user clicked near existing selection edges to resize
                if (this.selStart !== null && this.selEnd !== null) {
                    const s = Math.min(this.selStart, this.selEnd);
                    const eSec = Math.max(this.selStart, this.selEnd);
                    if (Math.abs(sec - s) * pxPerSec < 9) {
                        this.isDragging = true;
                        this.dragMode = 'left';
                        this.selStart = s;
                        this.selEnd = eSec;
                        return;
                    }
                    if (Math.abs(sec - eSec) * pxPerSec < 9) {
                        this.isDragging = true;
                        this.dragMode = 'right';
                        this.selStart = s;
                        this.selEnd = eSec;
                        return;
                    }
                }

                // 2) If clicked on top time ruler (Y <= 22): immediate seek & playhead move
                if (y <= 22) {
                    this.syncMediaToSec(sec);
                    this.renderTimeline();
                    return;
                }

                // 3) Begin drag selection
                this.isDragging = true;
                this.dragMode = 'new';
                this.dragStartSec = sec;
                this.selStart = sec;
                this.selEnd = sec;
                this.syncInputsToGradio();
                this.renderTimeline();
            });

            window.addEventListener('mousemove', (e) => {
                if (!this.isDragging) return;
                const sec = getSecFromEvent(e);
                if (this.dragMode === 'left') {
                    this.selStart = Math.min(sec, this.selEnd - 0.15);
                } else if (this.dragMode === 'right') {
                    this.selEnd = Math.max(sec, this.selStart + 0.15);
                } else {
                    this.selEnd = sec;
                }
                this.syncInputsToGradio();
                this.renderTimeline();
            });

            window.addEventListener('mouseup', (e) => {
                if (!this.isDragging) return;
                this.isDragging = false;
                const s = Math.min(this.selStart, this.selEnd);
                const eSec = Math.max(this.selStart, this.selEnd);
                const rect = canvas.getBoundingClientRect();
                const y = (e.clientY - rect.top) * (canvas.height / Math.max(1, rect.height));

                if (eSec - s < 0.22) {
                    // Single click without drag: check if clicked on a Lyric Phrase Pill or Vocal/FX block
                    let matchedBlock = null;
                    if (y >= 22 && y <= 72) {
                        for (const ln of this.lines) {
                            if (s >= ln.start && s <= ln.end) {
                                matchedBlock = { start: ln.start, end: ln.end };
                                break;
                            }
                        }
                    } else if (y >= 74 && y <= 124) {
                        for (const itv of this.vocalIntervals) {
                            if (s >= itv.start && s <= itv.end) {
                                matchedBlock = { start: itv.start, end: itv.end };
                                break;
                            }
                        }
                    } else if (y >= 126) {
                        for (const itv of this.fxIntervals) {
                            if (s >= itv.start && s <= itv.end) {
                                matchedBlock = { start: itv.start, end: itv.end };
                                break;
                            }
                        }
                    }

                    if (matchedBlock) {
                        this.selStart = matchedBlock.start;
                        this.selEnd = matchedBlock.end;
                        this.syncMediaToSec(matchedBlock.start);
                    } else {
                        // Simple click on empty waveform -> seek video to clicked point
                        this.selStart = null;
                        this.selEnd = null;
                        this.syncMediaToSec(s);
                    }
                } else {
                    this.selStart = s;
                    this.selEnd = eSec;
                    // Automatically seek video to start of newly selected region for instant debugging!
                    this.syncMediaToSec(s);
                }
                this.syncInputsToGradio();
                this.renderTimeline();
            });
        },

        tick() {
            this.checkDomDataBox();
            this.initCanvasEvents();

            const { video, audio } = this.getMedia();
            const badge = document.getElementById('karaoke-live-timecode-val');
            const stateBadge = document.getElementById('karaoke-live-sync-badge');

            if (video) {
                if (!this.duration && video.duration && !isNaN(video.duration)) {
                    this.duration = video.duration;
                }
                if (badge) {
                    badge.textContent = this.formatTime(video.currentTime);
                }
                if (Math.abs(video.volume - this.videoVol) > 0.01) {
                    video.volume = Math.max(0, Math.min(1, this.videoVol));
                }

                // Loop selection if enabled
                if (this.loopSelection && !video.paused && this.selStart !== null && this.selEnd !== null) {
                    const s = Math.min(this.selStart, this.selEnd);
                    const e = Math.max(this.selStart, this.selEnd);
                    if (e - s >= 0.3 && video.currentTime >= e) {
                        this.syncMediaToSec(s);
                    }
                }

                this.updatePlayButtonLabel();

                // This is an additional live stem. The video's own guide vocal
                // and automation are already baked into its audio track.
                const targetAudioVol = Math.max(0, Math.min(1, this.liveVocalMultiplier));

                if (audio && audio.src) {
                    audio.volume = targetAudioVol;
                    audio.muted = (targetAudioVol <= 0.005);

                    if (stateBadge) {
                        if (targetAudioVol > 0.005) {
                            stateBadge.textContent = this.audioPlayError || `🎤 Живой подмес: ${Math.round(targetAudioVol * 100)}%`;
                            stateBadge.style.color = '#fbbf24';
                        } else {
                            stateBadge.textContent = '🎤 Живой подмес выключен';
                            stateBadge.style.color = '#9ca3af';
                        }
                    }

                    if (!video.paused && !video.ended && targetAudioVol > 0.005) {
                        if (!audio.seeking && Math.abs(audio.currentTime - video.currentTime) > 0.15) {
                            audio.currentTime = video.currentTime;
                        }
                        if (audio.playbackRate !== video.playbackRate) {
                            audio.playbackRate = video.playbackRate;
                        }
                        if (audio.paused && !this.audioPlayPending && !this.audioPlayError) {
                            this.audioPlayPending = true;
                            audio.play().catch((error) => {
                                if (error.name !== 'AbortError') {
                                    this.audioPlayError = '🎤 Нажмите «Пуск» или измените подмес, чтобы включить вокал';
                                }
                            }).finally(() => { this.audioPlayPending = false; });
                        }
                    } else {
                        if (!audio.paused) {
                            audio.pause();
                        }
                        if (!audio.seeking && Math.abs(audio.currentTime - video.currentTime) > 0.06) {
                            audio.currentTime = video.currentTime;
                        }
                    }
                }
            } else if (audio && !audio.paused) {
                audio.pause();
            }

            this.renderTimeline();
        }
    };

    setInterval(() => {
        window.__karaokeStudio.tick();
    }, 40);

    // Native input events retain browser user activation (including Safari) and
    // update continuously while dragging, without waiting for a Gradio callback.
    document.addEventListener('input', (event) => {
        const studio = window.__karaokeStudio;
        if (event.target.closest('#live-vocal-slider')) {
            studio.liveVocalMultiplier = (Number(event.target.value) || 0) / 100;
        } else if (event.target.closest('#live-video-vol-slider')) {
            studio.videoVol = (Number(event.target.value) || 0) / 100;
        } else return;
        studio.audioPlayError = '';
        studio.tick();
    });
    document.addEventListener('click', () => {
        const studio = window.__karaokeStudio;
        studio.audioPlayError = '';
        studio.tick();
    });
}
"""


UPDATE_SLIDERS_JS = """
(vocalPct, videoPct) => {
    if (window.__karaokeStudio) {
        window.__karaokeStudio.liveVocalMultiplier = (Number(vocalPct) || 0) / 100.0;
        window.__karaokeStudio.audioPlayError = '';
        window.__karaokeStudio.videoVol = (Number(videoPct) ?? 100) / 100.0;
        window.__karaokeStudio.tick();
    }
}
"""

PUSH_TIMELINE_JSON_JS = """
(timelineJsonStr) => {
    if (window.__karaokeStudio && timelineJsonStr) {
        window.__karaokeStudio.loadProjectData(timelineJsonStr);
    }
}
"""

SYNC_TIMELINE_TO_GRADIO_JS = """
(vocalJson, fxJson) => {
    if (window.__karaokeStudio) {
        const liveVocal = JSON.stringify(window.__karaokeStudio.vocalIntervals || []);
        const liveFx = JSON.stringify(window.__karaokeStudio.fxIntervals || []);
        return [liveVocal, liveFx];
    }
    return [vocalJson, fxJson];
}
"""

STUDIO_CSS = """
/* 100% Full-Width Layout */
body {
    overflow-x: hidden !important;
}

.gradio-container {
    max-width: 100% !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 8px 18px !important;
    overflow-x: hidden !important;
}

/* Slide-out Drawers with unified single scroll */
#studio-drawer-left {
    position: fixed !important;
    top: 0 !important;
    left: -580px !important;
    width: 540px !important;
    max-width: 90vw !important;
    height: 100vh !important;
    display: block !important;
    background: #0b1120 !important;
    border-right: 2px solid #38bdf8 !important;
    box-shadow: 18px 0 50px rgba(0,0,0,0.8) !important;
    z-index: 1050 !important;
    transition: left 0.32s cubic-bezier(0.16, 1, 0.3, 1) !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    overscroll-behavior: contain !important;
    padding: 16px 18px 64px 16px !important;
}
#studio-drawer-left.open {
    left: 0 !important;
}

#studio-drawer-right {
    position: fixed !important;
    top: 0 !important;
    right: -600px !important;
    width: 560px !important;
    max-width: 90vw !important;
    height: 100vh !important;
    display: block !important;
    background: #0b1120 !important;
    border-left: 2px solid #a855f7 !important;
    box-shadow: -18px 0 50px rgba(0,0,0,0.8) !important;
    z-index: 1050 !important;
    transition: right 0.32s cubic-bezier(0.16, 1, 0.3, 1) !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    overscroll-behavior: contain !important;
    padding: 16px 18px 64px 16px !important;
}
#studio-drawer-right.open {
    right: 0 !important;
}

/* Prevent inner sections inside drawers from creating nested scrollbars */
#studio-drawer-right > *,
#studio-drawer-left > * {
    margin-bottom: 12px !important;
    flex-shrink: 0 !important;
    max-height: none !important;
    height: auto !important;
    overflow: visible !important;
}

#studio-drawer-right .styler,
#studio-drawer-right .form,
#studio-drawer-right .block,
#studio-drawer-right .gr-group,
#studio-drawer-right .gr-box,
#studio-drawer-right .accordion,
#studio-drawer-right .wrap,
#studio-drawer-left .styler,
#studio-drawer-left .form,
#studio-drawer-left .block,
#studio-drawer-left .gr-group {
    overflow: visible !important;
    overflow-y: visible !important;
    overflow-x: visible !important;
    max-height: none !important;
    height: auto !important;
    flex-shrink: 0 !important;
}

/* Backdrop for smooth closing on click */
#studio-drawer-backdrop {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    background: rgba(15, 23, 42, 0.65) !important;
    backdrop-filter: blur(4px) !important;
    -webkit-backdrop-filter: blur(4px) !important;
    z-index: 1040 !important;
    display: none !important;
    opacity: 0 !important;
    transition: opacity 0.25s ease !important;
}
#studio-drawer-backdrop.active {
    display: block !important;
    opacity: 1 !important;
}

/* Main stage full width */
#karaoke-main-stage {
    width: 100% !important;
    max-width: 100% !important;
}

#karaoke-main-video video {
    max-height: 56vh !important;
    width: auto !important;
    margin: 0 auto !important;
    border-radius: 8px !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5) !important;
}

/* Top bar controls */
.studio-nav-btn {
    display: inline-flex !important;
    align-items: center !important;
    gap: 8px !important;
    padding: 8px 16px !important;
    border-radius: 8px !important;
    font-weight: bold !important;
    font-size: 13px !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
}

/* Offscreen DOM bridge so Gradio 6 mounts textareas while keeping them invisible */
#studio-hidden-sync-bridge {
    position: fixed !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    z-index: -1 !important;
}

/* Custom scrollbars */
#karaoke-vocal-audio audio {
    display: none;
}

::-webkit-scrollbar {
    width: 7px;
    height: 7px;
}
::-webkit-scrollbar-track {
    background: #0f172a;
}
::-webkit-scrollbar-thumb {
    background: #334155;
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: #475569;
}
"""


def _build_timeline_payload(state_data: Dict[str, Any]) -> str:
    """Serializes the timeline waveform peaks, lines, and intervals into a compact JSON string for the browser Canvas."""
    if not state_data:
        return ""
    payload = {
        "title": state_data.get("title", ""),
        "duration": float(state_data.get("duration") or 0.0),
        "inst_peaks": state_data.get("inst_peaks") or [],
        "vocal_peaks": state_data.get("vocal_peaks") or [],
        "vocal_intervals": state_data.get("vocal_intervals") or [],
        "fx_intervals": state_data.get("fx_intervals") or [],
        "lines": state_data.get("lines") or [],
    }
    return json.dumps(payload, ensure_ascii=False)


def list_saved_states(output_dir: Path = Path("./output")) -> List[str]:
    """Finds cached *_state.json files in output/work."""
    work_dir = output_dir.resolve() / "work"
    if not work_dir.exists():
        return []
    files = sorted(work_dir.glob("*_state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [f.stem.replace("_state", "") for f in files]


def load_saved_project(project_title: str):
    """Loads a previously processed song into the Studio & Lyrics Editor without re-running models."""
    if not project_title:
        raise gr.Error("Выберите проект из списка!")
    state_file = Path("./output/work").resolve() / f"{project_title}_state.json"
    if not state_file.exists():
        raise gr.Error(f"Файл состояния не найден: {state_file}")
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    editor_text = state_data.get("editor_text", "")
    vocals_wav = state_data.get("vocals_wav")
    no_vocals_wav = state_data.get("no_vocals_wav")
    vocals_val = str(vocals_wav) if vocals_wav and Path(vocals_wav).exists() else None

    changed = False
    # Check cover
    cover_img = state_data.get("cover_image")
    if not cover_img or not Path(cover_img).exists():
        cover_img = ensure_project_cover(project_title, state_file.parent)
        if cover_img:
            state_data["cover_image"] = str(cover_img)
            changed = True

    if cover_img and Path(cover_img).exists() and not state_data.get("cover_edge_colors"):
        state_data["cover_edge_colors"] = extract_cover_edge_colors(Path(cover_img))
        changed = True

    # Ensure waveform peaks and duration exist for the 3-track timeline
    if (not state_data.get("inst_peaks") or not state_data.get("duration")) and no_vocals_wav and Path(no_vocals_wav).exists():
        i_peaks, dur = compute_waveform_peaks(Path(no_vocals_wav))
        v_peaks, _ = compute_waveform_peaks(Path(vocals_wav)) if vocals_wav and Path(vocals_wav).exists() else ([], 0.0)
        state_data["inst_peaks"] = i_peaks
        state_data["vocal_peaks"] = v_peaks
        state_data["duration"] = dur
        if not state_data.get("fx_intervals") and vocals_wav and Path(vocals_wav).exists():
            state_data["fx_intervals"] = detect_chorus_fx_intervals(Path(no_vocals_wav), Path(vocals_wav))
        changed = True

    if changed:
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    video_candidate = Path("./output").resolve() / f"{project_title}_karaoke.mp4"
    video_val = str(video_candidate) if video_candidate.exists() else None

    vocal_itv_json = json.dumps(state_data.get("vocal_intervals", []))
    fx_itv_json = json.dumps(state_data.get("fx_intervals", []))
    timeline_payload_json = _build_timeline_payload(state_data)

    return (
        state_data,
        editor_text,
        vocals_val,
        video_val,
        str(cover_img) if cover_img and Path(cover_img).exists() else None,
        vocal_itv_json,
        fx_itv_json,
        timeline_payload_json,
        f"✅ Загружен проект: {project_title}. 3-дорожечный таймлайн синхронизирован с видео!",
    )


def auto_load_initial_project():
    """Automatically loads the most recent project on UI startup so the timeline is immediately ready."""
    projects = list_saved_states()
    if not projects:
        return None, "", None, None, None, "[]", "[]", "", "Готов к работе. Загрузите трек или вставьте ссылку."
    try:
        return load_saved_project(projects[0])
    except Exception:
        return None, "", None, None, None, "[]", "[]", "", "Готов к работе."


def sync_timeline_boxes_ui(vocal_intervals_json: str, fx_intervals_json: str):
    """Receives live JSON strings directly from window.__karaokeStudio via JS and stores them in Gradio textboxes."""
    return vocal_intervals_json, fx_intervals_json


def _parse_intervals_json(raw_json: Optional[str], fallback: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Safely parses a JSON list of intervals, respecting an explicit empty list '[]'."""
    if raw_json is None:
        return fallback
    stripped = raw_json.strip()
    if not stripped:
        return fallback
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    return fallback


def regroup_project_lines_ui(
    state_data: Optional[Dict[str, Any]],
    editor_text: str,
    vocal_intervals_json: str = "",
    fx_intervals_json: str = "",
):
    """Logically regroups short 2-3 word orphan lines into full poetic clauses while preserving timeline FX/vocal zones."""
    if not state_data or "title" not in state_data:
        raise gr.Error("Сначала распознайте трек или загрузите проект из кэша!")
    original_lines = state_data.get("lines", [])
    current_lines = editor_text_to_lines(editor_text, original_lines=original_lines) if editor_text else original_lines

    old_count = len(current_lines)
    new_lines = regroup_editor_lines(current_lines)
    new_editor_text = lines_to_editor_text(new_lines)

    state_data["lines"] = new_lines
    state_data["editor_text"] = new_editor_text
    state_data["vocal_intervals"] = _parse_intervals_json(vocal_intervals_json, state_data.get("vocal_intervals", []))
    state_data["fx_intervals"] = _parse_intervals_json(fx_intervals_json, state_data.get("fx_intervals", []))

    title = state_data["title"]
    state_file = Path("./output/work").resolve() / f"{title}_state.json"
    if state_file.parent.exists():
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return (
        state_data,
        new_editor_text,
        _build_timeline_payload(state_data),
        f"✨ Строки логически склеены ({old_count} -> {len(new_lines)} строк). Нажми «Пересобрать видео», чтобы обновить MP4!",
    )


def split_project_lines_ui(
    state_data: Optional[Dict[str, Any]],
    editor_text: str,
    vocal_intervals_json: str = "",
    fx_intervals_json: str = "",
):
    """Splits long lines into balanced karaoke lines while preserving timeline FX/vocal zones."""
    if not state_data or "title" not in state_data:
        raise gr.Error("Сначала распознайте трек или загрузите проект из кэша!")
    original_lines = state_data.get("lines", [])
    current_lines = editor_text_to_lines(editor_text, original_lines=original_lines) if editor_text else original_lines

    old_count = len(current_lines)
    new_lines = split_long_editor_lines(current_lines)
    new_editor_text = lines_to_editor_text(new_lines)

    state_data["lines"] = new_lines
    state_data["editor_text"] = new_editor_text
    state_data["vocal_intervals"] = _parse_intervals_json(vocal_intervals_json, state_data.get("vocal_intervals", []))
    state_data["fx_intervals"] = _parse_intervals_json(fx_intervals_json, state_data.get("fx_intervals", []))

    title = state_data["title"]
    state_file = Path("./output/work").resolve() / f"{title}_state.json"
    if state_file.parent.exists():
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    split_diff = len(new_lines) - old_count
    msg = (
        f"✂️ Длинные строки разделены ({old_count} -> {len(new_lines)} строк, +{split_diff}). Нажми «Пересобрать видео»!"
        if split_diff > 0
        else "✂️ Слишком длинных строк для разделения не обнаружено."
    )

    return (
        state_data,
        new_editor_text,
        _build_timeline_payload(state_data),
        msg,
    )


def auto_detect_fx_ui(state_data: Optional[Dict[str, Any]]):
    """Detects energetic choruses and emotional climaxes and places FX on the timeline."""
    if not state_data or "title" not in state_data:
        raise gr.Error("Сначала загрузите или распознайте трек!")
    no_vocals = Path(state_data.get("no_vocals_wav", ""))
    vocals = Path(state_data.get("vocals_wav", ""))
    if not no_vocals.exists() or not vocals.exists():
        raise gr.Error("Аудиофайлы проекта не найдены на диске!")
    auto_fx = detect_chorus_fx_intervals(no_vocals, vocals)
    state_data["fx_intervals"] = auto_fx
    return (
        state_data,
        json.dumps(auto_fx),
        _build_timeline_payload(state_data),
        f"⚡ Автоматически обнаружено {len(auto_fx)} припевов/пиков для визуальных эффектов!",
    )


def cancel_generation_ui():
    """Immediately signals cancellation and kills active Demucs/FFmpeg subprocesses."""
    killed = request_cancel()
    return f"🛑 Генерация остановлена пользователем (прервано процессов: {killed})."


def run_full_karaoke_ui(
    url_input: str,
    file_input: Optional[str],
    bg_input: Optional[str],
    use_cover_bg: bool,
    use_video_bg: bool,
    cookies_browser: str,
    cookies_file: Optional[str],
    fx_mode: str,
    edge_color_mode: str,
    font_size_mode: str,
    highlight_color: str,
    video_quality: str,
    reference_lyrics: str,
    vocal_volume_pct: float,
    num_lines: int,
    model_size: str,
    demucs_model: str,
    language: str,
    use_ctc_align: bool,
    progress=gr.Progress(track_tqdm=True),
):
    # A single upload accepts either audio or video; ffprobe detects its streams.
    # A local upload takes precedence over a previously entered URL.
    if file_input:
        source = str(file_input)
    elif url_input and url_input.strip():
        source = url_input.strip()
    else:
        raise gr.Error("Загрузите аудио или видео либо укажите ссылку на YouTube.")
    effective_use_video_bg = use_video_bg

    # Format cookies configuration
    cb = cookies_browser if cookies_browser not in ("none", "file") else None
    cf = str(cookies_file) if (cookies_browser == "file" and cookies_file) else None

    reset_cancel()
    output_dir = Path("./output").resolve()
    bg_path = Path(bg_input) if bg_input else None
    lang = language.strip() if language and language.strip() else "ru"
    vocal_volume = float(vocal_volume_pct) / 100.0

    def update_progress(msg: str, frac: float):
        progress(frac, desc=msg)

    try:
        state_data = analyze_and_transcribe(
            source=source,
            output_dir=output_dir,
            model_size=model_size,
            demucs_model=demucs_model,
            language=lang,
            reference_lyrics=reference_lyrics,
            use_ctc_align=use_ctc_align,
            download_video=effective_use_video_bg,
            cookies_browser=cb,
            cookies_file=cf,
            progress_callback=update_progress,
        )
        final_video, _mixed_audio, updated_editor_text = render_from_state(
            state_data=state_data,
            output_dir=output_dir,
            editor_text=state_data["editor_text"],
            vocal_volume=vocal_volume,
            vocal_intervals=state_data.get("vocal_intervals", []),
            fx_intervals=state_data.get("fx_intervals", []),
            visual_effects=fx_mode,
            edge_color_mode=edge_color_mode,
            font_size_mode=font_size_mode,
            highlight_color=highlight_color,
            video_quality=video_quality,
            num_lines=int(num_lines),
            background=bg_path,
            use_cover_bg=use_cover_bg,
            use_video_bg=effective_use_video_bg,
            progress_callback=update_progress,
        )
        choices = list_saved_states(output_dir)
        vocals_wav = state_data.get("vocals_wav")
        vocals_val = str(vocals_wav) if vocals_wav and Path(vocals_wav).exists() else None
        cover_img = state_data.get("cover_image")
        cover_val = str(cover_img) if cover_img and Path(cover_img).exists() else None

        vocal_itv_json = json.dumps(state_data.get("vocal_intervals", []))
        fx_itv_json = json.dumps(state_data.get("fx_intervals", []))
        timeline_payload_json = _build_timeline_payload(state_data)

        return (
            state_data,
            updated_editor_text,
            vocals_val,
            str(final_video),
            cover_val,
            vocal_itv_json,
            fx_itv_json,
            timeline_payload_json,
            f"✅ Готово (Full HD 1080p): {final_video.name}! " + " ".join(state_data.get("alignment_warnings", [])),
            gr.update(choices=choices, value=state_data["title"]),
        )
    except GenerationCancelledError as e:
        gr.Warning(str(e))
        return (*[gr.skip() for _ in range(8)], str(e), gr.skip())
    except Exception as e:
        raise gr.Error(f"Ошибка при создании караоке: {str(e)}")


def rebuild_video_from_editor_ui(
    state_data: Optional[Dict[str, Any]],
    editor_text: str,
    bg_input: Optional[str],
    use_cover_bg: bool,
    use_video_bg: bool,
    fx_mode: str,
    edge_color_mode: str,
    font_size_mode: str,
    highlight_color: str,
    video_quality: str,
    vocal_volume_pct: float,
    num_lines: int,
    vocal_intervals_json: str,
    fx_intervals_json: str,
    progress=gr.Progress(track_tqdm=True),
):
    if not state_data or "title" not in state_data:
        raise gr.Error("Сначала распознайте трек или загрузите готовый проект из списка!")
    if not editor_text or not editor_text.strip():
        raise gr.Error("Поле редактора текста пустое!")

    reset_cancel()
    output_dir = Path("./output").resolve()
    bg_path = Path(bg_input) if bg_input else None
    vocal_volume = float(vocal_volume_pct) / 100.0

    vocal_intervals = _parse_intervals_json(vocal_intervals_json, state_data.get("vocal_intervals", []))
    fx_intervals = _parse_intervals_json(fx_intervals_json, state_data.get("fx_intervals", []))

    def update_progress(msg: str, frac: float):
        progress(frac, desc=msg)

    try:
        final_video, _mixed_audio, updated_editor_text = render_from_state(
            state_data=state_data,
            output_dir=output_dir,
            editor_text=editor_text,
            vocal_volume=vocal_volume,
            vocal_intervals=vocal_intervals,
            fx_intervals=fx_intervals,
            visual_effects=fx_mode,
            edge_color_mode=edge_color_mode,
            font_size_mode=font_size_mode,
            highlight_color=highlight_color,
            video_quality=video_quality,
            num_lines=int(num_lines),
            background=bg_path,
            use_cover_bg=use_cover_bg,
            use_video_bg=use_video_bg,
            progress_callback=update_progress,
        )
        updated_lines = editor_text_to_lines(updated_editor_text, original_lines=state_data.get("lines", []))
        state_data["lines"] = updated_lines
        state_data["editor_text"] = updated_editor_text
        state_data["vocal_intervals"] = vocal_intervals
        state_data["fx_intervals"] = fx_intervals
        title = state_data["title"]
        state_file = output_dir / "work" / f"{title}_state.json"
        if state_file.parent.exists():
            state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

        vocals_wav = state_data.get("vocals_wav")
        vocals_val = str(vocals_wav) if vocals_wav and Path(vocals_wav).exists() else None
        cover_img = state_data.get("cover_image")
        cover_val = str(cover_img) if cover_img and Path(cover_img).exists() else None
        vocal_itv_out = json.dumps(vocal_intervals, ensure_ascii=False)
        fx_itv_out = json.dumps(fx_intervals, ensure_ascii=False)
        timeline_payload_json = _build_timeline_payload(state_data)
        return (
            state_data,
            updated_editor_text,
            vocals_val,
            str(final_video),
            cover_val,
            vocal_itv_out,
            fx_itv_out,
            timeline_payload_json,
            f"✅ Видео 1080p пересобрано (зон вокала: {len(vocal_intervals)}, зон FX: {len(fx_intervals)}): {final_video.name}",
        )
    except GenerationCancelledError as e:
        gr.Warning(str(e))
        return (*[gr.skip() for _ in range(8)], str(e))
    except Exception as e:
        raise gr.Error(f"Ошибка при пересборке видео: {str(e)}")


def preview_background_image(file_path: Optional[str]):
    """Preview image uploads and clear the preview for videos or removed files."""
    from PIL import Image, UnidentifiedImageError

    if file_path:
        try:
            with Image.open(file_path) as image:
                image.verify()
            return gr.update(value=str(file_path), visible=True)
        except (OSError, UnidentifiedImageError, ValueError):
            pass
    return gr.update(value=None, visible=False)


def build_ui():
    block_options = {"title": "AI Karaoke Studio v0.3.9 (Timing Boundaries)"}
    if "css" in inspect.signature(gr.Blocks.__init__).parameters:
        block_options["css"] = STUDIO_CSS
    with gr.Blocks(**block_options) as demo:
        state_store = gr.State(value=None)

        # 1. Semi-transparent backdrop to close drawers on click or Esc
        gr.HTML('<div id="studio-drawer-backdrop" onclick="window.__karaokeStudio.closeDrawers()"></div>')

        # 2. Top Navigation Bar (Quick drawer toggles & live status badges)
        gr.HTML(
            """
            <div id="studio-top-bar" style="display:flex; justify-content:space-between; align-items:center; background:#0f172a; padding:10px 18px; border-radius:10px; border:1px solid #1e293b; margin-bottom:12px; box-shadow:0 4px 12px rgba(0,0,0,0.4);">
                <div style="display:flex; align-items:center; gap:12px;">
                    <button type="button" class="studio-nav-btn" onclick="window.__karaokeStudio.toggleLeftDrawer()" style="background:#0284c7; color:#fff; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; font-size:13px; cursor:pointer;">
                        📝 Текст и тайминги
                    </button>
                    <span style="font-weight:bold; font-size:16px; color:#f8fafc;">🎤 AI Karaoke Studio v0.3.9</span>
                    <span style="font-size:12px; color:#38bdf8; background:#1e293b; padding:3px 8px; border-radius:6px; border:1px solid #334155;">Full HD 1080p · 16:9</span>
                </div>
                <div style="display:flex; align-items:center; gap:14px;">
                    <div style="font-family:monospace; font-size:14px; color:#cbd5e1;">⏱️ <strong id="karaoke-live-timecode-val" style="color:#38bdf8; font-size:16px;">[00:00.00]</strong></div>
                    <div id="karaoke-live-sync-badge" style="font-size:13px; color:#9ca3af; font-family:monospace;">🎤 Живой подмес выключен</div>
                    <button type="button" class="studio-nav-btn" onclick="window.__karaokeStudio.toggleRightDrawer()" style="background:#9333ea; color:#fff; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; font-size:13px; cursor:pointer;">
                        📂 Источники
                    </button>
                </div>
            </div>
            """
        )

        # 3. Left Slide-out Drawer: Lyrics & Timecode Editor
        with gr.Column(elem_id="studio-drawer-left"):
            gr.HTML(
                """
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid #1e293b;">
                    <h3 style="margin:0; color:#38bdf8; font-size:16px;">📝 Редактор текста и таймингов</h3>
                    <button type="button" onclick="window.__karaokeStudio.toggleLeftDrawer(false)" style="background:#1e293b; color:#94a3b8; border:1px solid #475569; padding:4px 10px; border-radius:6px; cursor:pointer; font-weight:bold;">✕ Закрыть (Esc)</button>
                </div>
                <div style="font-size:12px; color:#94a3b8; margin-bottom:8px;">
                    💡 Вставляйте любые нативные эмодзи Apple (<code>🔥</code>, <code>🎤</code>, <code>👑</code>, <code>✨</code>, <code>💔</code>) прямо в текст или правьте таймкоды!
                </div>
                """
            )
            with gr.Row():
                regroup_btn = gr.Button("✨ Авто-склейка коротких строк", variant="secondary", size="sm")
                split_btn = gr.Button("✂️ Разделить длинные строки", variant="secondary", size="sm")
            editor_box = gr.Textbox(
                label="Построчный текст караоке с таймкодами",
                lines=24,
                interactive=True,
            )
            with gr.Row():
                rebuild_btn = gr.Button(
                    "🔄 Пересобрать видео в 1080p",
                    variant="primary",
                    size="lg",
                    scale=3,
                )
                cancel_left_btn = gr.Button(
                    "🛑 Стоп",
                    variant="stop",
                    size="lg",
                    scale=1,
                )

        # 4. Right Slide-out Drawer: Project Settings, Neon, Quality, Models & Sources
        with gr.Column(elem_id="studio-drawer-right"):
            gr.HTML(
                """
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid #1e293b;">
                    <h3 style="margin:0; color:#c084fc; font-size:16px;">📂 Источники и распознавание</h3>
                    <button type="button" onclick="window.__karaokeStudio.toggleRightDrawer(false)" style="background:#1e293b; color:#94a3b8; border:1px solid #475569; padding:4px 10px; border-radius:6px; cursor:pointer; font-weight:bold;">✕ Закрыть (Esc)</button>
                </div>
                """
            )

            with gr.Group():
                gr.Markdown("### Источник трека")
                url_box = gr.Textbox(
                    label="🔗 Ссылка на YouTube / видео",
                    placeholder="https://www.youtube.com/watch?v=...",
                )
                use_video_bg_cb = gr.Checkbox(
                    label="🎬 Использовать оригинальное видео с YouTube как фон",
                    value=False,
                    info="Скачивает клип с YouTube в 1080p и накладывает караоке-текст и эффекты прямо поверх видео",
                )
                with gr.Accordion("🍪 Настройки YouTube (авторизация / cookies для обхода бот-защиты)", open=False):
                    gr.Markdown(
                        "Если YouTube пишет *«Sign in to confirm you’re not a bot»*, выберите браузер, "
                        "в котором выполнен вход в YouTube, или загрузите файл cookies.txt."
                    )
                    cookie_browser_radio = gr.Radio(
                        label="🌐 Браузер для импорта cookies",
                        choices=[
                            ("Google Chrome (по умолчанию)", "chrome"),
                            ("Chromium", "chromium"),
                            ("Firefox", "firefox"),
                            ("Safari", "safari"),
                            ("Edge", "edge"),
                            ("Brave", "brave"),
                            ("Vivaldi", "vivaldi"),
                            ("Opera", "opera"),
                            ("Свой файл cookies.txt", "file"),
                            ("Без cookies (анонимно)", "none"),
                        ],
                        value="chrome",
                    )
                    cookie_file_input = gr.File(
                        label="📄 Файл cookies.txt (Netscape формат)",
                        file_types=[".txt"],
                        visible=False,
                    )
                file_box = gr.File(
                    label="🎵 Трек: аудио или видео",
                    file_types=["audio", "video"],
                    type="filepath",
                    elem_id="track-upload",
                )
                gr.Markdown("Перетащите один аудио- или видеофайл. Загруженный файл используется вместо ссылки. "
                            "Видео автоматически становится фоном; оформление настраивается под плеером.")

            with gr.Accordion("⚙️ Модели нейросетей & Свой текст", open=False):
                model_dropdown = gr.Dropdown(
                    label="Распознавание речи (Whisper)",
                    choices=WHISPER_MODELS,
                    value="large-v3-turbo",
                )
                demucs_dropdown = gr.Dropdown(
                    label="Отделение вокала (Demucs)",
                    choices=[
                        ("htdemucs (Быстрая Hybrid Transformer — 30 сек)", "htdemucs"),
                        ("htdemucs_ft (4x HQ Studio Fine-Tuned Ensemble — лучшее разделение)", "htdemucs_ft"),
                        ("hdemucs_mmi (Hybrid Demucs MMI)", "hdemucs_mmi"),
                        ("mdx_extra (MDX-Net Extra)", "mdx_extra"),
                    ],
                    value="htdemucs",
                )
                lang_box = gr.Textbox(label="Код языка", value="ru")
                ctc_checkbox = gr.Checkbox(
                    label="Кириллическое CTC выравнивание (Wav2Vec2)",
                    value=False,
                )
                ref_lyrics_box = gr.Textbox(
                    label="Вставьте текст песни из интернета (опционально)",
                    placeholder="Если вставить текст песни до запуска, нейросеть разобьет куплеты строго по строкам...",
                    lines=3,
                )

            with gr.Row():
                run_btn = gr.Button("🚀 Создать караоке", variant="primary", size="lg", scale=3)
                cancel_right_btn = gr.Button("🛑 Отменить", variant="stop", size="lg", scale=1, elem_id="cancel-main-btn")

            with gr.Accordion("📂 Открыть сохраненный проект из кэша", open=True):
                with gr.Row():
                    saved_dropdown = gr.Dropdown(
                        label="Проекты в output/work",
                        choices=list_saved_states(),
                        value=list_saved_states()[0] if list_saved_states() else None,
                        interactive=True,
                    )
                    load_btn = gr.Button("📂 Загрузить", variant="secondary")

        # 5. Main Center Stage: 100% Full-Width Video & 3-Track Timeline
        with gr.Column(elem_id="karaoke-main-stage"):
            status_box = gr.Textbox(label="Статус выполнения", interactive=False)
            video_out = gr.Video(
                label="🎬 Готовое караоке-видео (Full HD 1920x1080)",
                elem_id="karaoke-main-video",
                interactive=False,
            )

            # Пульт Live-отладки вокала (синхронно с видео)
            with gr.Group():
                with gr.Row():
                    live_vocal_slider = gr.Slider(
                        minimum=0,
                        maximum=100,
                        value=0,
                        step=1,
                        label="🎤 Live-подмес чистого вокала поверх видео (%)",
                        info="Крути во время просмотра для проверки синхрона слов",
                        elem_id="live-vocal-slider",
                    )
                    live_video_vol_slider = gr.Slider(
                        minimum=0,
                        maximum=100,
                        value=100,
                        step=1,
                        label="🎵 Громкость видео (%)",
                        info="Приглушай видео, чтобы слышать только чистый голос",
                        elem_id="live-video-vol-slider",
                    )

            with gr.Accordion("🎨 Оформление, фон и звук", open=True, elem_id="render-settings"):
                gr.Markdown("Для первой сборки задайте оформление здесь, затем запустите создание в разделе «Источники». "
                            "После изменений готового проекта нажмите «Пересобрать видео».")
                with gr.Tab("Эффекты и текст"):
                    with gr.Group():
                        gr.Markdown("### Оформление и эффекты")
                        edge_color_radio = gr.Radio(
                            label="🌈 Стиль и цвета неоновой рамки",
                            choices=[
                                ("⚡ Киберпанк (Неон-циан + Маджента + Фиолет)", "cyberpunk"),
                                ("🌸 Розовый (Hot Pink / Synthwave)", "pink"),
                                ("❄️ Голубой (Electric Ice Blue)", "blue"),
                                ("🔮 Фиолетовый (Deep Violet / Neon Purple)", "purple"),
                                ("🔥 Огонь (Fire Orange & Gold)", "fire"),
                                ("🎨 Цвета обложки (Ambilight)", "cover_colors"),
                                ("🌈 Радуга (Иридесцентные переливы)", "neon_rainbow"),
                                ("🚨 Полицейская мигалка (Красный + Синий стробоскоп)", "police"),
                            ],
                            value="cyberpunk",
                        )
                        font_size_radio = gr.Radio(
                            label="🔤 Размер шрифта текста",
                            choices=[
                                ("Стандартный (54px)", "standard"),
                                ("Крупный (64px, контрастный — по умолчанию)", "large"),
                                ("Огромный (74px)", "huge"),
                            ],
                            value="large",
                        )
                        highlight_color_radio = gr.Radio(
                            label="🌟 Цвет караоке-выделения (Свип)",
                            choices=[
                                ("Золотой неон (#FFDF00)", "gold_neon"),
                                ("Электрик циан (#00F0FF)", "electric_cyan"),
                                ("Неон маджента (#FF1493)", "neon_magenta"),
                                ("Кислотный лайм (#39FF14)", "acid_lime"),
                                ("Огненный оранж (#FF6A00)", "fire_orange"),
                            ],
                            value="gold_neon",
                        )
                        fx_dropdown = gr.Dropdown(
                            label="✨ Режим спецэффектов",
                            choices=[
                                ("✨ Блестки + Неон-пульсация рамки (Рекомендуется)", "sparkles_pulse"),
                                ("🔥 Салют эмодзи (летящие частицы на припевах)", "emoji_burst"),
                                ("🔮 Эмодзи + Неон-пульсация рамки", "emoji_pulse"),
                                ("💓 Только пульсация всего периметра 1920x1080", "pulse"),
                                ("🌟 Только летящие блестки и боке", "sparkles"),
                                ("🚨 Полицейская мигалка (красно-синий стробоскоп)", "police_strobe"),
                                ("💥 Эпичный припев (мощный неон + двойные блестки)", "climax"),
                                ("🎯 Только зоны с дорожки FX (по таймлайну)", "timeline_only"),
                                ("Без эффектов", "none"),
                            ],
                            value="sparkles_pulse",
                        )

                        lines_radio = gr.Radio(
                            choices=[3, 4],
                            value=4,
                            label="📺 Строк телесуфлера",
                            info="Активная строка всегда по центру",
                        )

                with gr.Tab("Фон"):
                    with gr.Group():
                        bg_box = gr.File(
                            label="🖼️ Фоновая картинка или видео",
                            file_types=["image", "video"],
                            type="filepath",
                            elem_id="background-upload",
                        )
                        background_preview = gr.Image(
                            label="Предпросмотр фоновой картинки",
                            interactive=False,
                            visible=False,
                            height=220,
                            elem_id="background-preview",
                        )
                        gr.Markdown("Свой фон заменяет исходное видео и обложку. Картинка масштабируется с обрезкой до 16:9.")
                        use_cover_cb = gr.Checkbox(
                            label="🖼️ Обложка трека как фон (Apple Music 1080p Blur)",
                            value=True,
                            info="Четкий Full HD задник с карточкой трека и эффектами",
                        )
                        cover_preview = gr.Image(
                            label="Найденная обложка трека",
                            interactive=False,
                            height=100,
                        )

                with gr.Tab("Звук и экспорт"):
                    with gr.Group():
                        vocal_vol_slider = gr.Slider(
                            minimum=0,
                            maximum=100,
                            value=0,
                            step=1,
                            label="🎙️ Базовый вокал в минусовке (Guide %)",
                            info="По умолчанию 0% — чистая минусовка. Отдельные участки можно настроить на таймлайне.",
                        )
                    with gr.Group():
                        gr.Markdown("### Качество экспорта")
                        video_quality_radio = gr.Radio(
                            label="Битрейт и скорость рендера (1080p)",
                            choices=[
                                ("Web Light (~2.2 Mbps, небольшой размер файла)", "light"),
                                ("Balanced 1080p (~4.2 Mbps, рекомендовано)", "balanced"),
                                ("Studio HQ (~8.5 Mbps, архивное качество)", "hq"),
                            ],
                            value="balanced",
                        )


            # 3-дорожечный интерактивный Таймлайн с синхронным Play и панелью эмодзи
            with gr.Group():
                gr.Markdown("### 🎚️ Студийный 3-дорожечный Таймлайн (Минус, Вокал, Спецэффекты)")
                gr.HTML(
                    """
                    <div style="background:#0f172a; padding:12px; border-radius:10px; border:1px solid #334155;">
                        <!-- Панель транспорта и зума -->
                        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; justify-content:space-between; margin-bottom:8px; padding-bottom:8px; border-bottom:1px solid #1e293b;">
                            <div style="display:flex; gap:6px; align-items:center;">
                                <button type="button" id="btn-tl-play" onclick="window.__karaokeStudio.playFromSelectionOrCursor()" style="background:#16a34a; color:#fff; border:none; padding:5px 14px; border-radius:6px; font-size:12px; font-weight:bold; cursor:pointer;">▶️ Пуск с момента</button>
                                <button type="button" onclick="window.__karaokeStudio.playFromSelectionStart()" style="background:#0369a1; color:#fff; border:none; padding:5px 10px; border-radius:6px; font-size:12px; cursor:pointer;" title="Перемотать в начало выделенного участка и включить Play">⏮️ Старт выделения</button>
                                <button type="button" id="btn-tl-loop" onclick="window.__karaokeStudio.toggleLoop()" style="background:#1e293b; color:#e2e8f0; border:1px solid #475569; padding:4px 10px; border-radius:6px; font-size:12px; cursor:pointer;">🔁 Петля: ВЫКЛ</button>
                            </div>
                            <div style="display:flex; gap:4px; align-items:center; font-size:11px; color:#94a3b8;">
                                <span>🔍 Зум:</span>
                                <button type="button" id="btn-tl-zoom-1" onclick="window.__karaokeStudio.setZoom(1)" style="background:#0284c7; color:#fff; border:none; padding:3px 8px; border-radius:4px; cursor:pointer;">1x</button>
                                <button type="button" id="btn-tl-zoom-2" onclick="window.__karaokeStudio.setZoom(2)" style="background:#1e293b; color:#fff; border:none; padding:3px 8px; border-radius:4px; cursor:pointer;">2x</button>
                                <button type="button" id="btn-tl-zoom-4" onclick="window.__karaokeStudio.setZoom(4)" style="background:#1e293b; color:#fff; border:none; padding:3px 8px; border-radius:4px; cursor:pointer;">4x</button>
                            </div>
                        </div>

                        <!-- Прокручиваемый холст 3 дорожек -->
                        <div style="overflow-x:auto; width:100%; border-radius:6px; border:1px solid #1e293b;">
                            <canvas id="karaoke-studio-canvas" width="1600" height="172" style="width:100%; height:172px; display:block; cursor:crosshair;"></canvas>
                        </div>

                        <div id="timeline-sel-info" style="margin-top:8px; font-size:12px; color:#cbd5e1; font-family:monospace;">
                            💡 Потяните мышкой по любой дорожке для выделения участка или кликните по фразе
                        </div>

                        <!-- Управление уровнем вокала на выделенном участке -->
                        <div style="margin-top:8px; padding-top:8px; border-top:1px solid #1e293b; display:flex; flex-wrap:wrap; gap:6px; align-items:center;">
                            <span style="font-size:12px; color:#fbbf24; font-weight:bold;">🎤 Вокал:</span>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionVocal(1.0)" style="background:#ea580c; color:#fff; border:none; padding:4px 9px; border-radius:4px; font-size:11px; font-weight:bold; cursor:pointer;">🔥 100% Оригинал</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionVocal(0.75)" style="background:#d97706; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">75%</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionVocal(0.50)" style="background:#b45309; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">🎙️ 50% Бэк</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionVocal(0.25)" style="background:#78350f; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">25%</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionVocal(0.0)" style="background:#374151; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">🔇 0% Чистый минус</button>
                            <div style="display:flex; align-items:center; gap:4px; background:#1e293b; padding:2px 8px; border-radius:4px;">
                                <input type="range" id="tl-custom-vocal-range" min="0" max="100" value="60" style="width:75px; cursor:pointer;" oninput="document.getElementById('tl-custom-vocal-val').textContent=this.value+'%'; window.__karaokeStudio.setSelectionVocal(Number(this.value)/100);" />
                                <span id="tl-custom-vocal-val" style="font-size:11px; color:#fde047; font-family:monospace; min-width:32px;">60%</span>
                            </div>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionVocal(null)" style="background:#4b5563; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">↩️ Сброс</button>
                        </div>

                        <!-- Управление эффектами FX на выделенном участке -->
                        <div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:5px; align-items:center;">
                            <span style="font-size:12px; color:#c084fc; font-weight:bold;">✨ Эффекты:</span>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('sparkles_pulse', 0.85)" style="background:#9333ea; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">✨ Блестки + Неон</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('pulse', 0.90)" style="background:#0891b2; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">💓 Неон-Рамка</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('sparkles', 0.85)" style="background:#ca8a04; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">🌟 Блестки</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('climax', 1.0)" style="background:#db2777; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:bold; cursor:pointer;">🔥 ПРИПЕВ MAX</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('police_strobe', 1.0)" style="background:#dc2626; border:1px solid #2563eb; color:#fff; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:bold; cursor:pointer;">🚨 Мигалка</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX(null)" style="background:#4b5563; color:#fff; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">❌ Убрать FX</button>
                            <button type="button" onclick="window.__karaokeStudio.clearAll()" style="background:#1e293b; color:#94a3b8; border:1px solid #475569; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer; margin-left:auto;">🗑️ Очистить все</button>
                        </div>

                        <!-- Выбор летящих эмодзи на участке -->
                        <div style="margin-top:6px; padding-top:6px; border-top:1px dashed #334155; display:flex; flex-wrap:wrap; gap:5px; align-items:center;">
                            <span style="font-size:12px; color:#fb923c; font-weight:bold;">🎉 Салют эмодзи:</span>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '🔥')" style="background:#1e293b; border:1px solid #ea580c; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">🔥 Огонь</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '🎤')" style="background:#1e293b; border:1px solid #38bdf8; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">🎤 Вокал</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '👑')" style="background:#1e293b; border:1px solid #eab308; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">👑 Корона</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '✨')" style="background:#1e293b; border:1px solid #a855f7; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">✨ Звёзды</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '💔')" style="background:#1e293b; border:1px solid #ec4899; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">💔 Сердце</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '🚀')" style="background:#1e293b; border:1px solid #06b6d4; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">🚀 Ракета</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '💣')" style="background:#1e293b; border:1px solid #ef4444; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">💣 Бомба</button>
                            <button type="button" onclick="window.__karaokeStudio.setSelectionFX('emoji_burst', 0.9, '🥂')" style="background:#1e293b; border:1px solid #f59e0b; color:#fff; padding:3px 7px; border-radius:4px; font-size:11px; cursor:pointer;">🥂 Тост</button>

                            <div style="display:flex; align-items:center; gap:4px; margin-left:4px;">
                                <input type="text" id="tl-custom-emoji-input" placeholder="Свои эмодзи (🎉⚡️)" style="width:115px; background:#0f172a; color:#fff; border:1px solid #475569; border-radius:4px; padding:3px 6px; font-size:11px;" />
                                <button type="button" onclick="window.__karaokeStudio.applyCustomEmojiFX()" style="background:#ea580c; color:#fff; border:none; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:bold; cursor:pointer;">🚀 Добавить</button>
                            </div>
                        </div>
                    </div>
                    """
                )
                with gr.Row():
                    auto_fx_btn = gr.Button("⚡ Авто-разметка эффектов на припевы и кульминации", variant="secondary", size="sm")
                    rebuild_stage_btn = gr.Button("🔄 Пересобрать видео в 1080p", variant="primary", size="sm")
                    cancel_stage_btn = gr.Button("🛑 Отменить генерацию", variant="stop", size="sm")

            # Offscreen DOM textboxes (visible=True so Gradio 6 mounts <textarea> in DOM, hidden via CSS)
            with gr.Column(elem_id="studio-hidden-sync-bridge"):
                vocal_intervals_box = gr.Textbox(visible=True, interactive=True, container=False, elem_id="vocal-intervals-json")
                fx_intervals_box = gr.Textbox(visible=True, interactive=True, container=False, elem_id="fx-intervals-json")
                studio_data_box = gr.Textbox(visible=True, interactive=True, container=False, elem_id="studio-timeline-data-json")

            audio_preview = gr.Audio(
                label="🎧 Чистая дорожка вокала (vocals.wav — автоматически синхронизирована с плеером)",
                elem_id="karaoke-vocal-audio",
                interactive=False,
                waveform_options=gr.WaveformOptions(show_recording_waveform=False),
            )

        bg_box.change(fn=preview_background_image, inputs=[bg_box], outputs=[background_preview], queue=False)

        # Wire Run Full Pipeline
        run_event = run_btn.click(
            fn=run_full_karaoke_ui,
            inputs=[
                url_box,
                file_box,
                bg_box,
                use_cover_cb,
                use_video_bg_cb,
                cookie_browser_radio,
                cookie_file_input,
                fx_dropdown,
                edge_color_radio,
                font_size_radio,
                highlight_color_radio,
                video_quality_radio,
                ref_lyrics_box,
                vocal_vol_slider,
                lines_radio,
                model_dropdown,
                demucs_dropdown,
                lang_box,
                ctc_checkbox,
            ],
            outputs=[
                state_store,
                editor_box,
                audio_preview,
                video_out,
                cover_preview,
                vocal_intervals_box,
                fx_intervals_box,
                studio_data_box,
                status_box,
                saved_dropdown,
            ],
            concurrency_id="karaoke_generation",
            concurrency_limit=1,
        )
        run_event.then(
            fn=None,
            inputs=[studio_data_box],
            js=PUSH_TIMELINE_JSON_JS,
        )

        # Wire Rebuild from Drawer & Rebuild from Stage (Step 1: pull live JS intervals -> Step 2: rebuild video)
        rebuild_events = []
        for b in [rebuild_btn, rebuild_stage_btn]:
            sync_ev = b.click(
                fn=sync_timeline_boxes_ui,
                inputs=[vocal_intervals_box, fx_intervals_box],
                outputs=[vocal_intervals_box, fx_intervals_box],
                js=SYNC_TIMELINE_TO_GRADIO_JS,
                queue=False,
            )
            ev = sync_ev.then(
                fn=rebuild_video_from_editor_ui,
                inputs=[
                    state_store,
                    editor_box,
                    bg_box,
                    use_cover_cb,
                    use_video_bg_cb,
                    fx_dropdown,
                    edge_color_radio,
                    font_size_radio,
                    highlight_color_radio,
                    video_quality_radio,
                    vocal_vol_slider,
                    lines_radio,
                    vocal_intervals_box,
                    fx_intervals_box,
                ],
                outputs=[
                    state_store,
                    editor_box,
                    audio_preview,
                    video_out,
                    cover_preview,
                    vocal_intervals_box,
                    fx_intervals_box,
                    studio_data_box,
                    status_box,
                ],
                concurrency_id="karaoke_generation",
                concurrency_limit=1,
            )
            ev.then(
                fn=None,
                inputs=[studio_data_box],
                js=PUSH_TIMELINE_JSON_JS,
            )
            rebuild_events.append(ev)

        # Wire Cancellation to all cancel buttons (cancels running Gradio events & terminates child OS processes)
        for c_btn in [cancel_right_btn, cancel_left_btn, cancel_stage_btn]:
            c_btn.click(
                fn=cancel_generation_ui,
                inputs=None,
                outputs=[status_box],
                cancels=[run_event] + rebuild_events,
                queue=False,
            )

        auto_fx_btn.click(
            fn=auto_detect_fx_ui,
            inputs=[state_store],
            outputs=[state_store, fx_intervals_box, studio_data_box, status_box],
        ).then(
            fn=None,
            inputs=[studio_data_box],
            js=PUSH_TIMELINE_JSON_JS,
        )

        regroup_btn.click(
            fn=sync_timeline_boxes_ui,
            inputs=[vocal_intervals_box, fx_intervals_box],
            outputs=[vocal_intervals_box, fx_intervals_box],
            js=SYNC_TIMELINE_TO_GRADIO_JS,
            queue=False,
        ).then(
            fn=regroup_project_lines_ui,
            inputs=[state_store, editor_box, vocal_intervals_box, fx_intervals_box],
            outputs=[state_store, editor_box, studio_data_box, status_box],
        ).then(
            fn=None,
            inputs=[studio_data_box],
            js=PUSH_TIMELINE_JSON_JS,
        )

        split_btn.click(
            fn=sync_timeline_boxes_ui,
            inputs=[vocal_intervals_box, fx_intervals_box],
            outputs=[vocal_intervals_box, fx_intervals_box],
            js=SYNC_TIMELINE_TO_GRADIO_JS,
            queue=False,
        ).then(
            fn=split_project_lines_ui,
            inputs=[state_store, editor_box, vocal_intervals_box, fx_intervals_box],
            outputs=[state_store, editor_box, studio_data_box, status_box],
        ).then(
            fn=None,
            inputs=[studio_data_box],
            js=PUSH_TIMELINE_JSON_JS,
        )

        load_btn.click(
            fn=load_saved_project,
            inputs=[saved_dropdown],
            outputs=[
                state_store,
                editor_box,
                audio_preview,
                video_out,
                cover_preview,
                vocal_intervals_box,
                fx_intervals_box,
                studio_data_box,
                status_box,
            ],
        ).then(
            fn=None,
            inputs=[studio_data_box],
            js=PUSH_TIMELINE_JSON_JS,
        )

        # Auto-initialize JS and auto-load the most recent cached project on page open
        demo.load(
            fn=auto_load_initial_project,
            inputs=None,
            outputs=[
                state_store,
                editor_box,
                audio_preview,
                video_out,
                cover_preview,
                vocal_intervals_box,
                fx_intervals_box,
                studio_data_box,
                status_box,
            ],
            js=STUDIO_JS,
        ).then(
            fn=None,
            inputs=[studio_data_box],
            js=PUSH_TIMELINE_JSON_JS,
        )

        live_vocal_slider.change(
            fn=None,
            inputs=[live_vocal_slider, live_video_vol_slider],
            js=UPDATE_SLIDERS_JS,
        )
        live_video_vol_slider.change(
            fn=None,
            inputs=[live_vocal_slider, live_video_vol_slider],
            js=UPDATE_SLIDERS_JS,
        )

        def toggle_cookie_file(browser_choice):
            return gr.update(visible=(browser_choice == "file"))

        cookie_browser_radio.change(
            fn=toggle_cookie_file,
            inputs=[cookie_browser_radio],
            outputs=[cookie_file_input],
        )

    return demo


def launch_ui(server_port: int = 7860, share: bool = False):
    demo = build_ui()
    output_dir = str(Path("./output").resolve())
    print(f"\n[Karaoke] Запуск AI Karaoke Studio v0.3.9 на http://127.0.0.1:{server_port}")
    launch_options = {}
    if "css" in inspect.signature(demo.launch).parameters:
        launch_options["css"] = STUDIO_CSS
    demo.launch(
        server_name="127.0.0.1",
        server_port=server_port,
        share=share,
        allowed_paths=[output_dir],
        **launch_options,
    )


def main():
    launch_ui()


if __name__ == "__main__":
    main()
