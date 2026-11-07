<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePlayerStore } from '@/stores/player'
import type { VocalInterval, FxInterval, EmojiInterval } from '@/types'
import EffectsMenuModal from './EffectsMenuModal.vue'
import EmojiBurstModal from './EmojiBurstModal.vue'
import ManualAlignModal from './ManualAlignModal.vue'
import {
  VolumeX,
  Volume1,
  Volume2,
  SmilePlus,
  Palette,
  Wand2,
  Trash2,
} from 'lucide-vue-next'

const projectStore = useProjectStore()
const playerStore = usePlayerStore()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const scrollContainerRef = ref<HTMLDivElement | null>(null)

const showFxModal = ref(false)
const showEmojiModal = ref(false)
const showManualModal = ref(false)

function openManualModal() {
  if (playerStore.selStart === null || playerStore.selEnd === null) {
    const cur = Number((playerStore.currentTime || 0).toFixed(2))
    playerStore.setSelection(cur, Number((cur + 5.0).toFixed(2)))
  }
  showManualModal.value = true
}

const zoomFactor = ref<number>(1)
const logicalWidth = ref<number>(1200)
const isDragging = ref<boolean>(false)
const dragMode = ref<
  | 'seek'
  | 'select'
  | 'move_lyric'
  | 'resize_lyric_l'
  | 'resize_lyric_r'
  | 'move_vocal'
  | 'resize_vocal_l'
  | 'resize_vocal_r'
  | 'move_fx'
  | 'resize_fx_l'
  | 'resize_fx_r'
  | 'move_emoji'
  | 'resize_emoji_l'
  | 'resize_emoji_r'
  | null
>(null)

const activeIntervalIdx = ref<number>(-1)
const dragStartSec = ref<number>(0)
const dragOrigStart = ref<number>(0)
const dragOrigEnd = ref<number>(0)

const TRACK_HEIGHTS = {
  ruler: 24,
  lyrics: 46,
  vocals: 48,
  inst: 44,
  emoji: 44,
}
const TOTAL_HEIGHT = 206

const UI_FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", system-ui, sans-serif'
const MONO_FONT = '"SF Mono", ui-monospace, Menlo, Monaco, monospace'

const duration = computed(() => Math.max(1, projectStore.duration || 60))

// Parsed lyric blocks for Track 1
const lyricBlocks = computed(() => {
  const rawLines = projectStore.currentProject?.lines || []
  return rawLines
    .map((line: any, idx: number) => {
      let s = 0,
        e = 0,
        text = ''
      if (Array.isArray(line) && line.length > 0) {
        s = Number(line[0]?.start ?? 0)
        e = Number(line[line.length - 1]?.end ?? 0)
        text = line.map((w: any) => w.text || '').join(' ').trim()
      } else if (line) {
        s = Number(line.start ?? 0)
        e = Number(line.end ?? 0)
        text = String(line.text ?? '')
      }
      return {
        index: idx,
        start: s,
        end: e,
        text,
      }
    })
    .filter((l: any) => l.end > l.start)
})

function formatTime(sec: number): string {
  if (!sec || isNaN(sec) || sec < 0) sec = 0
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const cs = Math.floor((sec % 1) * 100)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${cs.toString().padStart(2, '0')}`
}

function timeToX(time: number, width: number): number {
  return (time / duration.value) * width
}

function xToTime(x: number, width: number): number {
  return Math.max(0, Math.min(duration.value, (x / width) * duration.value))
}

function resizeCanvas() {
  const canvas = canvasRef.value
  const container = scrollContainerRef.value
  if (!canvas || !container) return

  const baseWidth = Math.max(container.clientWidth, 960)
  const targetWidth = Math.round(baseWidth * zoomFactor.value)
  logicalWidth.value = targetWidth

  // Retina / HiDPI crispness (minimum 2x supersampling so text & waveforms are razor-sharp)
  const dpr = Math.max(2, window.devicePixelRatio || 2)
  canvas.width = Math.round(targetWidth * dpr)
  canvas.height = Math.round(TOTAL_HEIGHT * dpr)
  canvas.style.width = `${targetWidth}px`
  canvas.style.height = `${TOTAL_HEIGHT}px`
  draw()
}

function setZoom(factor: number) {
  zoomFactor.value = Math.max(1, Math.min(8, factor))
  nextTick(() => {
    resizeCanvas()
  })
}

function drawPillBlock(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  topColor: string,
  bottomColor: string,
  borderColor: string,
  text: string,
  textColor: string = '#f8fafc',
  fontSpec: string = `600 11px ${UI_FONT}`
) {
  const rx = Math.round(x) + 0.5
  const ry = Math.round(y) + 0.5
  const rw = Math.max(4, Math.round(w) - 1)
  const rh = Math.round(h) - 1
  const radius = Math.min(5, rw / 2)

  const grad = ctx.createLinearGradient(0, ry, 0, ry + rh)
  grad.addColorStop(0, topColor)
  grad.addColorStop(1, bottomColor)

  ctx.fillStyle = grad
  ctx.strokeStyle = borderColor
  ctx.lineWidth = 1

  ctx.beginPath()
  ctx.roundRect(rx, ry, rw, rh, radius)
  ctx.fill()
  ctx.stroke()

  // Resize grip bars only when pill is wide enough not to clutter
  if (rw >= 22) {
    ctx.fillStyle = 'rgba(255, 255, 255, 0.55)'
    ctx.fillRect(Math.round(rx + 2.5), Math.round(ry + rh * 0.28), 1.5, Math.round(rh * 0.44))
    ctx.fillRect(Math.round(rx + rw - 4), Math.round(ry + rh * 0.28), 1.5, Math.round(rh * 0.44))
  }

  // Crisp clipped label
  if (rw >= 16 && text) {
    ctx.save()
    ctx.beginPath()
    ctx.rect(rx + 4, ry + 1, Math.max(0, rw - 8), rh - 2)
    ctx.clip()
    ctx.font = fontSpec
    ctx.fillStyle = textColor
    ctx.textBaseline = 'middle'
    ctx.textAlign = 'left'
    ctx.fillText(text, Math.round(rx + (rw >= 24 ? 7 : 4)), Math.round(ry + rh / 2 + 0.5))
    ctx.restore()
  }
}

function draw() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const dpr = Math.max(2, window.devicePixelRatio || 2)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  const w = logicalWidth.value
  const h = TOTAL_HEIGHT
  const dur = duration.value
  const currTime = playerStore.currentTime

  ctx.clearRect(0, 0, w, h)

  // 1. Track lane backgrounds
  ctx.fillStyle = '#0d1322'
  ctx.fillRect(0, 0, w, 24)

  ctx.fillStyle = '#090d16'
  ctx.fillRect(0, 24, w, 46)

  ctx.fillStyle = '#0d1424'
  ctx.fillRect(0, 70, w, 48)

  ctx.fillStyle = '#090d16'
  ctx.fillRect(0, 118, w, 44)

  ctx.fillStyle = '#0d1322'
  ctx.fillRect(0, 162, w, 44)

  // Crisp 1px horizontal divider lines aligned to half-pixel
  ctx.strokeStyle = '#1e293b'
  ctx.lineWidth = 1
  ;[24, 70, 118, 162].forEach((y) => {
    const py = Math.floor(y) + 0.5
    ctx.beginPath()
    ctx.moveTo(0, py)
    ctx.lineTo(w, py)
    ctx.stroke()
  })

  // 2. Time Ruler ticks & vertical grid lines
  const stepSec = zoomFactor.value >= 6 ? 1 : zoomFactor.value >= 4 ? 2 : zoomFactor.value >= 2 ? 5 : 10
  const subStepSec = stepSec / 5

  // Subtle sub-ticks
  ctx.fillStyle = '#1e293b'
  for (let sec = 0; sec <= dur; sec += subStepSec) {
    const sx = Math.floor(timeToX(sec, w))
    ctx.fillRect(sx, 19, 1, 5)
  }

  ctx.font = `500 10px ${MONO_FONT}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'

  for (let sec = 0; sec <= dur; sec += stepSec) {
    const x = Math.floor(timeToX(sec, w)) + 0.5

    // Vertical grid line across tracks
    ctx.strokeStyle = 'rgba(30, 41, 59, 0.45)'
    ctx.beginPath()
    ctx.moveTo(x, 24)
    ctx.lineTo(x, h)
    ctx.stroke()

    // Ruler major tick
    ctx.fillStyle = '#475569'
    ctx.fillRect(Math.floor(x), 14, 1, 10)

    if (x + 36 < w) {
      ctx.fillStyle = '#94a3b8'
      ctx.fillText(formatTime(sec).slice(0, 5), Math.floor(x) + 4, 12)
    }
  }

  // 3. Track 1: Lyrics blocks (24..70)
  const yLyrics = 24
  const hLyrics = 46
  lyricBlocks.value.forEach((b: any) => {
    const bx = timeToX(b.start, w)
    const bw = Math.max(6, timeToX(b.end, w) - bx)
    drawPillBlock(
      ctx,
      bx,
      yLyrics + 6,
      bw,
      hLyrics - 12,
      'rgba(14, 165, 233, 0.42)',
      'rgba(2, 132, 199, 0.26)',
      '#38bdf8',
      b.text,
      '#f0f9ff',
      `600 11px ${UI_FONT}`
    )
  })

  // 4. Track 2: Vocal waveform & intervals (70..118)
  const yVoc = 70
  const hVoc = 48
  const vocPeaks = projectStore.currentProject?.vocal_peaks || []
  if (vocPeaks.length > 0) {
    ctx.fillStyle = 'rgba(16, 185, 129, 0.32)'
    const pLen = vocPeaks.length
    const barStride = w / pLen
    const barW = Math.max(1, barStride * 0.72)
    for (let i = 0; i < pLen; i++) {
      const px = i * barStride
      const ph = Math.max(1.5, vocPeaks[i] * (hVoc - 10))
      ctx.fillRect(px, yVoc + (hVoc - ph) / 2, barW, ph)
    }
  }

  const vocIntervals = projectStore.currentProject?.vocal_intervals || []
  vocIntervals.forEach((itv) => {
    const ix = timeToX(itv.start, w)
    const iw = Math.max(6, timeToX(itv.end, w) - ix)
    const isMuted = itv.volume === 0

    drawPillBlock(
      ctx,
      ix,
      yVoc + 5,
      iw,
      hVoc - 10,
      isMuted ? 'rgba(239, 68, 68, 0.52)' : 'rgba(16, 185, 129, 0.55)',
      isMuted ? 'rgba(185, 28, 28, 0.35)' : 'rgba(5, 150, 105, 0.35)',
      isMuted ? '#f87171' : '#34d399',
      `${Math.round(itv.volume * 100)}%`,
      '#ffffff',
      `600 10px ${MONO_FONT}`
    )
  })

  // 5. Track 3: Instrumental waveform & Stage FX intervals (118..162)
  const yInst = 118
  const hInst = 44
  const instPeaks = projectStore.currentProject?.inst_peaks || []
  if (instPeaks.length > 0) {
    ctx.fillStyle = 'rgba(245, 158, 11, 0.25)'
    const pLen = instPeaks.length
    const barStride = w / pLen
    const barW = Math.max(1, barStride * 0.72)
    for (let i = 0; i < pLen; i++) {
      const px = i * barStride
      const ph = Math.max(1.5, instPeaks[i] * (hInst - 10))
      ctx.fillRect(px, yInst + (hInst - ph) / 2, barW, ph)
    }
  }

  const fxIntervals = projectStore.currentProject?.fx_intervals || []
  fxIntervals.forEach((itv) => {
    const ix = timeToX(itv.start, w)
    const iw = Math.max(6, timeToX(itv.end, w) - ix)

    let topCol = 'rgba(168, 85, 247, 0.52)'
    let botCol = 'rgba(126, 34, 206, 0.35)'
    let strokeCol = '#c084fc'
    let label = itv.effect || 'FX'

    if (itv.effect === 'sparkles_pulse') {
      label = '✨ Неон + Искры'
    } else if (itv.effect === 'police_strobe') {
      topCol = 'rgba(239, 68, 68, 0.58)'
      botCol = 'rgba(37, 99, 235, 0.42)'
      strokeCol = '#60a5fa'
      label = '🚨 Мигалка'
    } else if (itv.effect === 'green_neon') {
      topCol = 'rgba(16, 185, 129, 0.55)'
      botCol = 'rgba(5, 150, 105, 0.35)'
      strokeCol = '#34d399'
      label = '🟢 Зеленый неон'
    } else if (itv.effect === 'sparkles') {
      topCol = 'rgba(245, 158, 11, 0.55)'
      botCol = 'rgba(217, 119, 6, 0.35)'
      strokeCol = '#fbbf24'
      label = '🌟 Блестки'
    } else if (itv.effect === 'climax') {
      topCol = 'rgba(236, 72, 153, 0.58)'
      botCol = 'rgba(190, 24, 93, 0.38)'
      strokeCol = '#f43f5e'
      label = '💥 Припев MAX'
    } else if (itv.effect === 'neon_rainbow') {
      topCol = 'rgba(6, 182, 212, 0.52)'
      botCol = 'rgba(59, 130, 246, 0.35)'
      strokeCol = '#38bdf8'
      label = '🌈 Радуга'
    } else if (itv.effect === 'emoji_burst') {
      topCol = 'rgba(249, 115, 22, 0.52)'
      botCol = 'rgba(194, 65, 12, 0.35)'
      strokeCol = '#fb923c'
      label = `🎉 Салют ${itv.emojis || '🔥'}`
    }

    drawPillBlock(
      ctx,
      ix,
      yInst + 5,
      iw,
      hInst - 10,
      topCol,
      botCol,
      strokeCol,
      label,
      '#ffffff',
      `600 10.5px ${UI_FONT}`
    )
  })

  // 6. Track 4: Emoji FX Intervals (162..206)
  const yEmoji = 162
  const hEmoji = 44
  const emojiIntervals = projectStore.currentProject?.emoji_intervals || []
  emojiIntervals.forEach((itv) => {
    const ix = timeToX(itv.start, w)
    const iw = Math.max(6, timeToX(itv.end, w) - ix)

    drawPillBlock(
      ctx,
      ix,
      yEmoji + 5,
      iw,
      hEmoji - 10,
      'rgba(192, 132, 252, 0.50)',
      'rgba(147, 51, 234, 0.32)',
      '#d8b4fe',
      `${itv.emojis || '🔥'} (${Math.round(itv.intensity * 100)}%)`,
      '#ffffff',
      `600 11px ${UI_FONT}`
    )
  })

  // 7. User Selection Range
  if (playerStore.selStart !== null && playerStore.selEnd !== null) {
    const s = Math.min(playerStore.selStart, playerStore.selEnd)
    const e = Math.max(playerStore.selStart, playerStore.selEnd)
    const sx = Math.round(timeToX(s, w)) + 0.5
    const sw = Math.max(2, Math.round(timeToX(e, w) - sx))

    ctx.fillStyle = 'rgba(56, 189, 248, 0.14)'
    ctx.fillRect(sx, 0, sw, h)

    ctx.strokeStyle = '#38bdf8'
    ctx.lineWidth = 1.5
    ctx.strokeRect(sx, 0.5, sw, h - 1)
  }

  // 8. Playhead Scrubber Cursor
  const curX = Math.round(timeToX(currTime, w)) + 0.5
  ctx.strokeStyle = '#f43f5e'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.moveTo(curX, 0)
  ctx.lineTo(curX, h)
  ctx.stroke()

  // Head shield
  ctx.fillStyle = '#f43f5e'
  ctx.beginPath()
  ctx.moveTo(curX - 6, 0)
  ctx.lineTo(curX + 6, 0)
  ctx.lineTo(curX + 6, 6)
  ctx.lineTo(curX, 12)
  ctx.lineTo(curX - 6, 6)
  ctx.closePath()
  ctx.fill()
}

let mouseDownClientX = 0
let mouseDownClientY = 0

// Mouse Event Handlers (using CSS logicalWidth so Retina 2x/3x maps accurately)
function onMouseDown(e: MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas || !projectStore.hasProject) return

  mouseDownClientX = e.clientX
  mouseDownClientY = e.clientY

  const rect = canvas.getBoundingClientRect()
  const w = logicalWidth.value
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top
  const clickTime = xToTime(mouseX, w)

  isDragging.value = true
  dragStartSec.value = clickTime

  // Click on Ruler -> Seek & Play immediately
  if (mouseY <= TRACK_HEIGHTS.ruler) {
    dragMode.value = 'seek'
    playerStore.seek(clickTime)
    playerStore.play()
    draw()
    return
  }

  // Track 1 (Lyrics): Moving or Resizing line
  if (mouseY > 24 && mouseY <= 70) {
    for (let i = 0; i < lyricBlocks.value.length; i++) {
      const b = lyricBlocks.value[i]
      const bx = timeToX(b.start, w)
      const bw = timeToX(b.end, w) - bx

      if (mouseX >= bx - 5 && mouseX <= bx + 6) {
        dragMode.value = 'resize_lyric_l'
        activeIntervalIdx.value = b.index
        dragOrigStart.value = b.start
        dragOrigEnd.value = b.end
        playerStore.setSelection(b.start, b.end)
        return
      }
      if (mouseX >= bx + bw - 6 && mouseX <= bx + bw + 5) {
        dragMode.value = 'resize_lyric_r'
        activeIntervalIdx.value = b.index
        dragOrigStart.value = b.start
        dragOrigEnd.value = b.end
        playerStore.setSelection(b.start, b.end)
        return
      }
      if (mouseX >= bx && mouseX <= bx + bw) {
        dragMode.value = 'move_lyric'
        activeIntervalIdx.value = b.index
        dragOrigStart.value = b.start
        dragOrigEnd.value = b.end
        playerStore.setSelection(b.start, b.end)
        playerStore.seek(b.start)
        playerStore.play()
        return
      }
    }
  }

  // Track 2 (Vocals)
  if (mouseY > 70 && mouseY <= 118) {
    const vocs = projectStore.currentProject?.vocal_intervals || []
    for (let i = 0; i < vocs.length; i++) {
      const itv = vocs[i]
      const ix = timeToX(itv.start, w)
      const iw = timeToX(itv.end, w) - ix

      if (mouseX >= ix - 4 && mouseX <= ix + 6) {
        dragMode.value = 'resize_vocal_l'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
      if (mouseX >= ix + iw - 6 && mouseX <= ix + iw + 4) {
        dragMode.value = 'resize_vocal_r'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
      if (mouseX >= ix && mouseX <= ix + iw) {
        dragMode.value = 'move_vocal'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
    }
  }

  // Track 3 (Stage FX)
  if (mouseY > 118 && mouseY <= 162) {
    const fxs = projectStore.currentProject?.fx_intervals || []
    for (let i = 0; i < fxs.length; i++) {
      const itv = fxs[i]
      const ix = timeToX(itv.start, w)
      const iw = timeToX(itv.end, w) - ix

      if (mouseX >= ix - 4 && mouseX <= ix + 6) {
        dragMode.value = 'resize_fx_l'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
      if (mouseX >= ix + iw - 6 && mouseX <= ix + iw + 4) {
        dragMode.value = 'resize_fx_r'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
      if (mouseX >= ix && mouseX <= ix + iw) {
        dragMode.value = 'move_fx'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
    }
  }

  // Track 4 (Emoji FX)
  if (mouseY > 162 && mouseY <= 206) {
    const ems = projectStore.currentProject?.emoji_intervals || []
    for (let i = 0; i < ems.length; i++) {
      const itv = ems[i]
      const ix = timeToX(itv.start, w)
      const iw = timeToX(itv.end, w) - ix

      if (mouseX >= ix - 4 && mouseX <= ix + 6) {
        dragMode.value = 'resize_emoji_l'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
      if (mouseX >= ix + iw - 6 && mouseX <= ix + iw + 4) {
        dragMode.value = 'resize_emoji_r'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
      if (mouseX >= ix && mouseX <= ix + iw) {
        dragMode.value = 'move_emoji'
        activeIntervalIdx.value = i
        dragOrigStart.value = itv.start
        dragOrigEnd.value = itv.end
        return
      }
    }
  }

  // Default: drag selection
  dragMode.value = 'select'
  playerStore.setSelection(clickTime, clickTime)
  draw()
}

function onMouseMove(e: MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas || !isDragging.value) return

  const rect = canvas.getBoundingClientRect()
  const w = logicalWidth.value
  const mouseX = e.clientX - rect.left
  const currSec = xToTime(mouseX, w)

  if (dragMode.value === 'seek') {
    playerStore.seek(currSec)
  } else if (dragMode.value === 'select') {
    playerStore.setSelection(dragStartSec.value, currSec)
  } else if (dragMode.value === 'move_lyric' && activeIntervalIdx.value >= 0) {
    const delta = currSec - dragStartSec.value
    const len = dragOrigEnd.value - dragOrigStart.value
    const newStart = Math.max(0, dragOrigStart.value + delta)
    const newEnd = Math.min(duration.value, newStart + len)
    projectStore.shiftLineTiming(activeIntervalIdx.value, newStart, newEnd)
    playerStore.setSelection(newStart, newEnd)
  } else if (dragMode.value === 'resize_lyric_l' && activeIntervalIdx.value >= 0) {
    if (currSec < dragOrigEnd.value - 0.15) {
      projectStore.shiftLineTiming(activeIntervalIdx.value, currSec, dragOrigEnd.value)
      playerStore.setSelection(currSec, dragOrigEnd.value)
    }
  } else if (dragMode.value === 'resize_lyric_r' && activeIntervalIdx.value >= 0) {
    if (currSec > dragOrigStart.value + 0.15) {
      projectStore.shiftLineTiming(activeIntervalIdx.value, dragOrigStart.value, currSec)
      playerStore.setSelection(dragOrigStart.value, currSec)
    }
  } else if (dragMode.value === 'move_vocal' && activeIntervalIdx.value >= 0) {
    const delta = currSec - dragStartSec.value
    const itv = projectStore.currentProject?.vocal_intervals[activeIntervalIdx.value]
    if (itv) {
      const len = dragOrigEnd.value - dragOrigStart.value
      itv.start = Math.max(0, Number((dragOrigStart.value + delta).toFixed(2)))
      itv.end = Math.min(duration.value, Number((itv.start + len).toFixed(2)))
    }
  } else if (dragMode.value === 'resize_vocal_l' && activeIntervalIdx.value >= 0) {
    const itv = projectStore.currentProject?.vocal_intervals[activeIntervalIdx.value]
    if (itv && currSec < itv.end - 0.1) {
      itv.start = Math.max(0, Number(currSec.toFixed(2)))
    }
  } else if (dragMode.value === 'resize_vocal_r' && activeIntervalIdx.value >= 0) {
    const itv = projectStore.currentProject?.vocal_intervals[activeIntervalIdx.value]
    if (itv && currSec > itv.start + 0.1) {
      itv.end = Math.min(duration.value, Number(currSec.toFixed(2)))
    }
  } else if (dragMode.value === 'move_fx' && activeIntervalIdx.value >= 0) {
    const delta = currSec - dragStartSec.value
    const itv = projectStore.currentProject?.fx_intervals[activeIntervalIdx.value]
    if (itv) {
      const len = dragOrigEnd.value - dragOrigStart.value
      itv.start = Math.max(0, Number((dragOrigStart.value + delta).toFixed(2)))
      itv.end = Math.min(duration.value, Number((itv.start + len).toFixed(2)))
    }
  } else if (dragMode.value === 'resize_fx_l' && activeIntervalIdx.value >= 0) {
    const itv = projectStore.currentProject?.fx_intervals[activeIntervalIdx.value]
    if (itv && currSec < itv.end - 0.1) {
      itv.start = Math.max(0, Number(currSec.toFixed(2)))
    }
  } else if (dragMode.value === 'resize_fx_r' && activeIntervalIdx.value >= 0) {
    const itv = projectStore.currentProject?.fx_intervals[activeIntervalIdx.value]
    if (itv && currSec > itv.start + 0.1) {
      itv.end = Math.min(duration.value, Number(currSec.toFixed(2)))
    }
  } else if (dragMode.value === 'move_emoji' && activeIntervalIdx.value >= 0) {
    const delta = currSec - dragStartSec.value
    const ems = projectStore.currentProject?.emoji_intervals || []
    const itv = ems[activeIntervalIdx.value]
    if (itv) {
      const len = dragOrigEnd.value - dragOrigStart.value
      itv.start = Math.max(0, Number((dragOrigStart.value + delta).toFixed(2)))
      itv.end = Math.min(duration.value, Number((itv.start + len).toFixed(2)))
    }
  } else if (dragMode.value === 'resize_emoji_l' && activeIntervalIdx.value >= 0) {
    const ems = projectStore.currentProject?.emoji_intervals || []
    const itv = ems[activeIntervalIdx.value]
    if (itv && currSec < itv.end - 0.1) {
      itv.start = Math.max(0, Number(currSec.toFixed(2)))
    }
  } else if (dragMode.value === 'resize_emoji_r' && activeIntervalIdx.value >= 0) {
    const ems = projectStore.currentProject?.emoji_intervals || []
    const itv = ems[activeIntervalIdx.value]
    if (itv && currSec > itv.start + 0.1) {
      itv.end = Math.min(duration.value, Number(currSec.toFixed(2)))
    }
  }

  draw()
}

function onMouseUp(e: MouseEvent) {
  if (isDragging.value) {
    const wasSelect = dragMode.value === 'select'
    const wasSeek = dragMode.value === 'seek'
    isDragging.value = false
    dragMode.value = null
    activeIntervalIdx.value = -1

    if (e && (wasSelect || wasSeek)) {
      const dist = Math.hypot(e.clientX - mouseDownClientX, e.clientY - mouseDownClientY)
      // If mouse moved less than 6 pixels, it's a simple click on the timeline: seek & play!
      if (dist < 6) {
        playerStore.clearSelection()
        playerStore.seek(dragStartSec.value)
        playerStore.play()
      }
    }

    projectStore.isDirty = true
    draw()
  }
}

// Modal actions
function onApplyFx(payload: { effect: string; intensity: number }) {
  if (playerStore.selStart === null || playerStore.selEnd === null || !projectStore.currentProject) return
  const s = Math.min(playerStore.selStart, playerStore.selEnd)
  const e = Math.max(playerStore.selStart, playerStore.selEnd)
  if (e - s < 0.1) return

  const updated: FxInterval[] = []
  const old = projectStore.currentProject.fx_intervals || []
  for (const itv of old) {
    if (itv.end <= s || itv.start >= e) {
      updated.push(itv)
    } else {
      if (itv.start < s) updated.push({ ...itv, end: s })
      if (itv.end > e) updated.push({ ...itv, start: e })
    }
  }
  updated.push({
    start: Number(s.toFixed(2)),
    end: Number(e.toFixed(2)),
    effect: payload.effect,
    intensity: payload.intensity,
  })
  updated.sort((a, b) => a.start - b.start)
  projectStore.setFxIntervals(updated)
  showFxModal.value = false
  draw()
}

function onRemoveFx() {
  if (playerStore.selStart === null || playerStore.selEnd === null || !projectStore.currentProject) return
  const s = Math.min(playerStore.selStart, playerStore.selEnd)
  const e = Math.max(playerStore.selStart, playerStore.selEnd)
  const updated: FxInterval[] = []
  const old = projectStore.currentProject.fx_intervals || []
  for (const itv of old) {
    if (itv.end <= s || itv.start >= e) {
      updated.push(itv)
    } else {
      if (itv.start < s) updated.push({ ...itv, end: s })
      if (itv.end > e) updated.push({ ...itv, start: e })
    }
  }
  projectStore.setFxIntervals(updated)
  showFxModal.value = false
  draw()
}

function onApplyEmoji(payload: { emojis: string; intensity: number }) {
  if (playerStore.selStart === null || playerStore.selEnd === null || !projectStore.currentProject) return
  const s = Math.min(playerStore.selStart, playerStore.selEnd)
  const e = Math.max(playerStore.selStart, playerStore.selEnd)
  if (e - s < 0.1) return

  const updated: EmojiInterval[] = []
  const old = projectStore.currentProject.emoji_intervals || []
  for (const itv of old) {
    if (itv.end <= s || itv.start >= e) {
      updated.push(itv)
    } else {
      if (itv.start < s) updated.push({ ...itv, end: s })
      if (itv.end > e) updated.push({ ...itv, start: e })
    }
  }
  updated.push({
    start: Number(s.toFixed(2)),
    end: Number(e.toFixed(2)),
    emojis: payload.emojis,
    intensity: payload.intensity,
  })
  updated.sort((a, b) => a.start - b.start)
  projectStore.setEmojiIntervals(updated)
  showEmojiModal.value = false
  draw()
}

function onRemoveEmoji() {
  if (playerStore.selStart === null || playerStore.selEnd === null || !projectStore.currentProject) return
  const s = Math.min(playerStore.selStart, playerStore.selEnd)
  const e = Math.max(playerStore.selStart, playerStore.selEnd)
  const updated: EmojiInterval[] = []
  const old = projectStore.currentProject.emoji_intervals || []
  for (const itv of old) {
    if (itv.end <= s || itv.start >= e) {
      updated.push(itv)
    } else {
      if (itv.start < s) updated.push({ ...itv, end: s })
      if (itv.end > e) updated.push({ ...itv, start: e })
    }
  }
  projectStore.setEmojiIntervals(updated)
  showEmojiModal.value = false
  draw()
}

function applyVocalToSelection(volume: number | null) {
  if (playerStore.selStart === null || playerStore.selEnd === null || !projectStore.currentProject) return
  const s = Math.min(playerStore.selStart, playerStore.selEnd)
  const e = Math.max(playerStore.selStart, playerStore.selEnd)
  if (e - s < 0.1) return

  const updated: VocalInterval[] = []
  const old = projectStore.currentProject.vocal_intervals || []
  for (const itv of old) {
    if (itv.end <= s || itv.start >= e) {
      updated.push(itv)
    } else {
      if (itv.start < s) updated.push({ start: itv.start, end: s, volume: itv.volume })
      if (itv.end > e) updated.push({ start: e, end: itv.end, volume: itv.volume })
    }
  }
  if (volume !== null) {
    updated.push({ start: Number(s.toFixed(2)), end: Number(e.toFixed(2)), volume })
    updated.sort((a, b) => a.start - b.start)
  }
  projectStore.setVocalIntervals(updated)
  draw()
}

function clearAllIntervals() {
  projectStore.setVocalIntervals([])
  projectStore.setFxIntervals([])
  projectStore.setEmojiIntervals([])
  playerStore.clearSelection()
  draw()
}

watch(
  [
    () => playerStore.currentTime,
    () => projectStore.currentProject,
    () => playerStore.selStart,
    () => playerStore.selEnd,
  ],
  () => {
    draw()
  }
)

onMounted(() => {
  window.addEventListener('resize', resizeCanvas)
  window.addEventListener('mouseup', onMouseUp)
  window.addEventListener('mousemove', onMouseMove)
  resizeCanvas()
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeCanvas)
  window.removeEventListener('mouseup', onMouseUp)
  window.removeEventListener('mousemove', onMouseMove)
})
</script>

<template>
  <div class="h-64 bg-studio-panel border-t border-studio-border flex flex-col shrink-0 select-none">
    <!-- Toolbar: Modals Trigger & Quick Actions -->
    <div class="h-10 px-3 bg-studio-surface border-b border-studio-border flex items-center justify-between text-xs">
      <!-- Left: Effect Menu Triggers & Vocal Actions -->
      <div class="flex items-center space-x-2">
        <button
          @click="showFxModal = true"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-sky-600 hover:bg-sky-500 text-white font-medium shadow-sm disabled:opacity-40 transition-colors"
        >
          <Palette class="w-3.5 h-3.5" />
          <span>Меню эффектов сцены</span>
        </button>

        <button
          @click="showEmojiModal = true"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-purple-600 hover:bg-purple-500 text-white font-medium shadow-sm disabled:opacity-40 transition-colors"
        >
          <SmilePlus class="w-3.5 h-3.5" />
          <span>Салют эмодзи</span>
        </button>

        <button
          @click="openManualModal"
          class="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium shadow-sm transition-colors"
          title="Мануальный режим: точечное выравнивание и сборка превью куска видео"
        >
          <Wand2 class="w-3.5 h-3.5" />
          <span>Мануальный режим</span>
        </button>

        <div class="h-4 w-px bg-studio-border mx-1"></div>

        <span class="text-studio-muted font-medium">Вокал:</span>
        <button
          @click="applyVocalToSelection(0.0)"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1 px-2 py-1 rounded-md bg-red-600/20 text-red-300 border border-red-500/30 hover:bg-red-600/30 disabled:opacity-30 transition-colors"
        >
          <VolumeX class="w-3.5 h-3.5" />
          <span>Глушить (0%)</span>
        </button>

        <button
          @click="applyVocalToSelection(0.3)"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1 px-2 py-1 rounded-md bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/30 disabled:opacity-30 transition-colors"
        >
          <Volume1 class="w-3.5 h-3.5" />
          <span>Бэк (30%)</span>
        </button>

        <button
          @click="applyVocalToSelection(1.0)"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1 px-2 py-1 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30 disabled:opacity-30 transition-colors"
        >
          <Volume2 class="w-3.5 h-3.5" />
          <span>100%</span>
        </button>

        <button
          v-if="playerStore.selStart !== null"
          @click="playerStore.clearSelection()"
          class="text-studio-muted hover:text-white px-1.5 py-0.5 rounded text-xs ml-1"
        >
          Снять выбор
        </button>
      </div>

      <!-- Right: Zoom & Reset -->
      <div class="flex items-center space-x-2">
        <span class="text-studio-muted">Масштаб:</span>
        <div class="inline-flex rounded-lg overflow-hidden border border-[#26354d] bg-[#131c2e]">
          <button
            v-for="z in [1, 2, 4, 6]"
            :key="z"
            @click="setZoom(z)"
            :class="[
              'px-2.5 py-0.5 text-xs font-mono transition-colors',
              zoomFactor === z
                ? 'bg-sky-600 text-white font-semibold'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/70'
            ]"
          >
            {{ z }}x
          </button>
        </div>

        <div class="h-4 w-px bg-studio-border mx-1"></div>

        <button
          @click="clearAllIntervals"
          title="Сбросить все интервалы вокала и эффектов"
          class="p-1 text-slate-400 hover:text-red-400 rounded transition-colors"
        >
          <Trash2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Main Timeline Body: Fixed Left Track Headers + Scrollable Retina Canvas -->
    <div class="flex-1 flex min-h-0 overflow-hidden bg-[#090d16]">
      <!-- Fixed Track Headers Column (DAW Style) -->
      <div class="w-36 shrink-0 bg-[#0d1322] border-r border-studio-border flex flex-col text-[11px] font-medium select-none z-10">
        <div class="h-[24px] px-2.5 flex items-center text-[10px] font-mono uppercase tracking-wider text-slate-400 border-b border-studio-border bg-[#0b101d]">
          ⏱ Шкала времени
        </div>
        <div class="h-[46px] px-2.5 flex items-center space-x-2 border-b border-studio-border text-sky-300">
          <span class="w-1.5 h-5 rounded-full bg-sky-400 shrink-0"></span>
          <div class="leading-tight">
            <div class="font-semibold text-slate-100">1. Слова</div>
            <div class="text-[9px] text-slate-400">Фразы и сдвиг</div>
          </div>
        </div>
        <div class="h-[48px] px-2.5 flex items-center space-x-2 border-b border-studio-border text-emerald-300 bg-[#0f172a]/50">
          <span class="w-1.5 h-5 rounded-full bg-emerald-400 shrink-0"></span>
          <div class="leading-tight">
            <div class="font-semibold text-slate-100">2. Вокал</div>
            <div class="text-[9px] text-slate-400">Автоматизация</div>
          </div>
        </div>
        <div class="h-[44px] px-2.5 flex items-center space-x-2 border-b border-studio-border text-purple-300">
          <span class="w-1.5 h-5 rounded-full bg-purple-400 shrink-0"></span>
          <div class="leading-tight">
            <div class="font-semibold text-slate-100">3. Эффекты</div>
            <div class="text-[9px] text-slate-400">Неон и стробоскоп</div>
          </div>
        </div>
        <div class="h-[44px] px-2.5 flex items-center space-x-2 text-amber-300 bg-[#0f172a]/50">
          <span class="w-1.5 h-5 rounded-full bg-amber-400 shrink-0"></span>
          <div class="leading-tight">
            <div class="font-semibold text-slate-100">4. Салюты</div>
            <div class="text-[9px] text-slate-400">Взрывы эмодзи</div>
          </div>
        </div>
      </div>

      <!-- Scrollable HiDPI Retina Canvas -->
      <div
        ref="scrollContainerRef"
        class="flex-1 overflow-x-auto overflow-y-hidden relative bg-[#090d16]"
      >
        <canvas
          ref="canvasRef"
          @mousedown="onMouseDown"
          class="cursor-crosshair block"
        ></canvas>
      </div>
    </div>

    <!-- Modals -->
    <EffectsMenuModal
      v-if="showFxModal"
      @close="showFxModal = false"
      @apply="onApplyFx"
      @remove="onRemoveFx"
    />

    <EmojiBurstModal
      v-if="showEmojiModal"
      @close="showEmojiModal = false"
      @apply="onApplyEmoji"
      @remove="onRemoveEmoji"
    />

    <ManualAlignModal
      v-if="showManualModal"
      :initial-start="Math.min(playerStore.selStart ?? 0, playerStore.selEnd ?? 5)"
      :initial-end="Math.max(playerStore.selStart ?? 0, playerStore.selEnd ?? 5)"
      @close="showManualModal = false"
      @applied="draw()"
    />
  </div>
</template>
