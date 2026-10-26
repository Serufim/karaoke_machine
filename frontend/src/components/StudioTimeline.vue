<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePlayerStore } from '@/stores/player'
import type { VocalInterval, FxInterval, EmojiInterval } from '@/types'
import EffectsMenuModal from './EffectsMenuModal.vue'
import EmojiBurstModal from './EmojiBurstModal.vue'
import {
  VolumeX,
  Volume1,
  Volume2,
  Sparkles,
  SmilePlus,
  Palette,
  Trash2,
} from 'lucide-vue-next'

const projectStore = useProjectStore()
const playerStore = usePlayerStore()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const scrollContainerRef = ref<HTMLDivElement | null>(null)

const showFxModal = ref(false)
const showEmojiModal = ref(false)

const zoomFactor = ref<number>(1)
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

const duration = computed(() => Math.max(1, projectStore.duration || 60))

// Parsed lyric blocks for Track 1
const lyricBlocks = computed(() => {
  const rawLines = projectStore.currentProject?.lines || []
  return rawLines.map((line: any, idx: number) => {
    let s = 0, e = 0, text = ''
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
  }).filter((l: any) => l.end > l.start)
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

  const baseWidth = Math.max(container.clientWidth, 1200)
  const targetWidth = baseWidth * zoomFactor.value
  canvas.width = targetWidth
  canvas.height = TOTAL_HEIGHT
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

function draw() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const w = canvas.width
  const h = canvas.height
  const dur = duration.value
  const currTime = playerStore.currentTime

  ctx.clearRect(0, 0, w, h)

  // 1. Backgrounds for 4 tracks
  // Ruler: 0..24
  ctx.fillStyle = '#0f172a'
  ctx.fillRect(0, 0, w, 24)

  // Track 1 (Lyrics): 24..70
  ctx.fillStyle = '#090d16'
  ctx.fillRect(0, 24, w, 46)

  // Track 2 (Vocals): 70..118
  ctx.fillStyle = '#111827'
  ctx.fillRect(0, 70, w, 48)

  // Track 3 (Stage FX): 118..162
  ctx.fillStyle = '#090d16'
  ctx.fillRect(0, 118, w, 44)

  // Track 4 (Emoji FX): 162..206
  ctx.fillStyle = '#0f172a'
  ctx.fillRect(0, 162, w, 44)

  // Track divider lines
  ctx.strokeStyle = '#1e293b'
  ctx.lineWidth = 1
  ;[24, 70, 118, 162].forEach((y) => {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  })

  // Track Left Labels (subtle)
  ctx.font = '10px sans-serif'
  ctx.fillStyle = 'rgba(148, 163, 184, 0.25)'
  ctx.fillText('1. СЛОВА (ПЕРЕТАСКИВАНИЕ/ПОДГОНКА)', 12, 40)
  ctx.fillText('2. ВОКАЛ (ГЛУШЕНИЕ/БУСТ)', 12, 86)
  ctx.fillText('3. ЭФФЕКТЫ СЦЕНЫ (НЕОН/МИГАЛКА/ИСКРЫ)', 12, 134)
  ctx.fillText('4. САЛЮТЫ ЭМОДЗИ', 12, 178)

  // 2. Time Ruler ticks & labels
  ctx.fillStyle = '#64748b'
  ctx.font = '10px monospace'
  ctx.textAlign = 'left'

  const stepSec = zoomFactor.value >= 4 ? 1 : zoomFactor.value >= 2 ? 5 : 10
  for (let sec = 0; sec <= dur; sec += stepSec) {
    const x = timeToX(sec, w)
    ctx.fillRect(x, 14, 1, 10)
    if (x + 35 < w) {
      ctx.fillText(formatTime(sec).slice(0, 5), x + 3, 11)
    }
  }

  // 3. Track 1: Lyrics blocks (with draggable & resizable handles!)
  const yLyrics = 24
  const hLyrics = 46
  ctx.font = '11px sans-serif'
  lyricBlocks.value.forEach((b: any) => {
    const bx = timeToX(b.start, w)
    const bw = Math.max(10, timeToX(b.end, w) - bx)

    ctx.fillStyle = 'rgba(2, 132, 199, 0.45)'
    ctx.strokeStyle = '#38bdf8'
    ctx.lineWidth = 1.2

    ctx.beginPath()
    ctx.roundRect(bx, yLyrics + 5, bw, hLyrics - 10, 4)
    ctx.fill()
    ctx.stroke()

    // Left & Right resize handles
    ctx.fillStyle = '#38bdf8'
    ctx.fillRect(bx + 1, yLyrics + 12, 2.5, hLyrics - 24)
    ctx.fillRect(bx + bw - 3.5, yLyrics + 12, 2.5, hLyrics - 24)

    // Text label
    ctx.fillStyle = '#f0f9ff'
    ctx.save()
    ctx.beginPath()
    ctx.rect(bx + 4, yLyrics + 5, bw - 8, hLyrics - 10)
    ctx.clip()
    ctx.fillText(b.text, bx + 6, yLyrics + 25)
    ctx.restore()
  })

  // 4. Track 2: Vocal waveform & intervals
  const yVoc = 70
  const hVoc = 48
  const vocPeaks = projectStore.currentProject?.vocal_peaks || []
  if (vocPeaks.length > 0) {
    ctx.fillStyle = 'rgba(16, 185, 129, 0.35)'
    const pLen = vocPeaks.length
    for (let i = 0; i < pLen; i++) {
      const px = (i / pLen) * w
      const ph = Math.max(1, vocPeaks[i] * (hVoc - 8))
      ctx.fillRect(px, yVoc + (hVoc - ph) / 2, Math.max(1, w / pLen - 0.5), ph)
    }
  }

  // Vocal Intervals
  const vocIntervals = projectStore.currentProject?.vocal_intervals || []
  vocIntervals.forEach((itv) => {
    const ix = timeToX(itv.start, w)
    const iw = Math.max(6, timeToX(itv.end, w) - ix)
    const isMuted = itv.volume === 0

    ctx.fillStyle = isMuted ? 'rgba(239, 68, 68, 0.45)' : 'rgba(16, 185, 129, 0.5)'
    ctx.strokeStyle = isMuted ? '#ef4444' : '#10b981'
    ctx.lineWidth = 1.5

    ctx.beginPath()
    ctx.roundRect(ix, yVoc + 4, iw, hVoc - 8, 4)
    ctx.fill()
    ctx.stroke()

    ctx.fillStyle = '#ffffff'
    ctx.fillRect(ix + 1, yVoc + 12, 2, hVoc - 24)
    ctx.fillRect(ix + iw - 3, yVoc + 12, 2, hVoc - 24)

    ctx.fillStyle = '#ffffff'
    ctx.font = '10px monospace'
    ctx.fillText(`${Math.round(itv.volume * 100)}%`, ix + 6, yVoc + 18)
  })

  // 5. Track 3: Instrumental waveform & Stage FX intervals
  const yInst = 118
  const hInst = 44
  const instPeaks = projectStore.currentProject?.inst_peaks || []
  if (instPeaks.length > 0) {
    ctx.fillStyle = 'rgba(245, 158, 11, 0.30)'
    const pLen = instPeaks.length
    for (let i = 0; i < pLen; i++) {
      const px = (i / pLen) * w
      const ph = Math.max(1, instPeaks[i] * (hInst - 8))
      ctx.fillRect(px, yInst + (hInst - ph) / 2, Math.max(1, w / pLen - 0.5), ph)
    }
  }

  // Stage FX Intervals
  const fxIntervals = projectStore.currentProject?.fx_intervals || []
  fxIntervals.forEach((itv) => {
    const ix = timeToX(itv.start, w)
    const iw = Math.max(6, timeToX(itv.end, w) - ix)

    let fillCol = 'rgba(139, 92, 246, 0.45)'
    let strokeCol = '#a855f7'
    let label = itv.effect || 'FX'

    if (itv.effect === 'police_strobe') {
      fillCol = 'rgba(239, 68, 68, 0.55)'
      strokeCol = '#3b82f6'
      label = '🚨 Мигалка'
    } else if (itv.effect === 'green_neon') {
      fillCol = 'rgba(16, 185, 129, 0.55)'
      strokeCol = '#10b981'
      label = '🟢 Зеленый неон'
    } else if (itv.effect === 'sparkles') {
      fillCol = 'rgba(245, 158, 11, 0.50)'
      strokeCol = '#fbbf24'
      label = '🌟 Блестки'
    } else if (itv.effect === 'climax') {
      fillCol = 'rgba(236, 72, 153, 0.55)'
      strokeCol = '#f43f5e'
      label = '💥 Климакс'
    } else if (itv.effect === 'neon_rainbow') {
      fillCol = 'rgba(6, 182, 212, 0.50)'
      strokeCol = '#38bdf8'
      label = '🌈 Радуга'
    }

    ctx.fillStyle = fillCol
    ctx.strokeStyle = strokeCol
    ctx.lineWidth = 1.5

    ctx.beginPath()
    ctx.roundRect(ix, yInst + 3, iw, hInst - 6, 4)
    ctx.fill()
    ctx.stroke()

    ctx.fillStyle = '#ffffff'
    ctx.fillRect(ix + 1, yInst + 10, 2, hInst - 20)
    ctx.fillRect(ix + iw - 3, yInst + 10, 2, hInst - 20)

    ctx.font = '10px sans-serif'
    ctx.fillText(label, ix + 6, yInst + 18)
  })

  // 6. Track 4: Emoji FX Intervals (Dedicated layer!)
  const yEmoji = 162
  const hEmoji = 44
  const emojiIntervals = projectStore.currentProject?.emoji_intervals || []
  emojiIntervals.forEach((itv) => {
    const ix = timeToX(itv.start, w)
    const iw = Math.max(6, timeToX(itv.end, w) - ix)

    ctx.fillStyle = 'rgba(168, 85, 247, 0.45)'
    ctx.strokeStyle = '#c084fc'
    ctx.lineWidth = 1.5

    ctx.beginPath()
    ctx.roundRect(ix, yEmoji + 3, iw, hEmoji - 6, 4)
    ctx.fill()
    ctx.stroke()

    ctx.fillStyle = '#ffffff'
    ctx.fillRect(ix + 1, yEmoji + 10, 2, hEmoji - 20)
    ctx.fillRect(ix + iw - 3, yEmoji + 10, 2, hEmoji - 20)

    ctx.font = '12px sans-serif'
    ctx.fillText(`${itv.emojis || '🔥'} (${Math.round(itv.intensity * 100)}%)`, ix + 6, yEmoji + 20)
  })

  // 7. User Selection Range
  if (playerStore.selStart !== null && playerStore.selEnd !== null) {
    const s = Math.min(playerStore.selStart, playerStore.selEnd)
    const e = Math.max(playerStore.selStart, playerStore.selEnd)
    const sx = timeToX(s, w)
    const sw = Math.max(2, timeToX(e, w) - sx)

    ctx.fillStyle = 'rgba(56, 189, 248, 0.18)'
    ctx.fillRect(sx, 0, sw, h)

    ctx.strokeStyle = '#38bdf8'
    ctx.lineWidth = 1.5
    ctx.strokeRect(sx, 0, sw, h)
  }

  // 8. Playhead Scrubber Cursor
  const curX = timeToX(currTime, w)
  ctx.strokeStyle = '#ef4444'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(curX, 0)
  ctx.lineTo(curX, h)
  ctx.stroke()

  // Head triangle
  ctx.fillStyle = '#ef4444'
  ctx.beginPath()
  ctx.moveTo(curX - 6, 0)
  ctx.lineTo(curX + 6, 0)
  ctx.lineTo(curX, 9)
  ctx.closePath()
  ctx.fill()
}

// Mouse Event Handlers
function onMouseDown(e: MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas || !projectStore.hasProject) return

  const rect = canvas.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top
  const clickTime = xToTime(mouseX, canvas.width)

  isDragging.value = true
  dragStartSec.value = clickTime

  // Click on Ruler -> Seek
  if (mouseY <= TRACK_HEIGHTS.ruler) {
    dragMode.value = 'seek'
    playerStore.seek(clickTime)
    draw()
    return
  }

  // Track 1 (Lyrics): Moving or Resizing line
  if (mouseY > 24 && mouseY <= 70) {
    for (let i = 0; i < lyricBlocks.value.length; i++) {
      const b = lyricBlocks.value[i]
      const bx = timeToX(b.start, canvas.width)
      const bw = timeToX(b.end, canvas.width) - bx

      // Check left edge resize
      if (mouseX >= bx - 5 && mouseX <= bx + 6) {
        dragMode.value = 'resize_lyric_l'
        activeIntervalIdx.value = b.index
        dragOrigStart.value = b.start
        dragOrigEnd.value = b.end
        playerStore.setSelection(b.start, b.end)
        return
      }
      // Check right edge resize
      if (mouseX >= bx + bw - 6 && mouseX <= bx + bw + 5) {
        dragMode.value = 'resize_lyric_r'
        activeIntervalIdx.value = b.index
        dragOrigStart.value = b.start
        dragOrigEnd.value = b.end
        playerStore.setSelection(b.start, b.end)
        return
      }
      // Check center move
      if (mouseX >= bx && mouseX <= bx + bw) {
        dragMode.value = 'move_lyric'
        activeIntervalIdx.value = b.index
        dragOrigStart.value = b.start
        dragOrigEnd.value = b.end
        playerStore.setSelection(b.start, b.end)
        playerStore.seek(b.start)
        return
      }
    }
  }

  // Track 2 (Vocals)
  if (mouseY > 70 && mouseY <= 118) {
    const vocs = projectStore.currentProject?.vocal_intervals || []
    for (let i = 0; i < vocs.length; i++) {
      const itv = vocs[i]
      const ix = timeToX(itv.start, canvas.width)
      const iw = timeToX(itv.end, canvas.width) - ix

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
      const ix = timeToX(itv.start, canvas.width)
      const iw = timeToX(itv.end, canvas.width) - ix

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
      const ix = timeToX(itv.start, canvas.width)
      const iw = timeToX(itv.end, canvas.width) - ix

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
  if (!canvas) return

  const rect = canvas.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const currSec = xToTime(mouseX, canvas.width)

  if (!isDragging.value) {
    return
  }

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

function onMouseUp() {
  if (isDragging.value) {
    isDragging.value = false
    dragMode.value = null
    activeIntervalIdx.value = -1
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

// Quick Vocal Buttons
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

// Watchers & Mount
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
        <!-- Stage FX Menu Button -->
        <button
          @click="showFxModal = true"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1.5 px-2.5 py-1 rounded bg-sky-600 hover:bg-sky-500 text-white font-medium shadow-sm disabled:opacity-40 transition-colors"
        >
          <Palette class="w-3.5 h-3.5" />
          <span>Меню эффектов сцены</span>
        </button>

        <!-- Emoji Burst Modal Button -->
        <button
          @click="showEmojiModal = true"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1.5 px-2.5 py-1 rounded bg-purple-600 hover:bg-purple-500 text-white font-medium shadow-sm disabled:opacity-40 transition-colors"
        >
          <SmilePlus class="w-3.5 h-3.5" />
          <span>Салют эмодзи</span>
        </button>

        <div class="h-4 w-px bg-studio-border mx-1"></div>

        <!-- Vocal actions -->
        <span class="text-studio-muted font-medium">Вокал:</span>
        <button
          @click="applyVocalToSelection(0.0)"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1 px-2 py-1 rounded bg-red-600/20 text-red-300 border border-red-500/30 hover:bg-red-600/30 disabled:opacity-30 transition-colors"
        >
          <VolumeX class="w-3.5 h-3.5" />
          <span>Глушить (0%)</span>
        </button>

        <button
          @click="applyVocalToSelection(0.3)"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1 px-2 py-1 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/30 disabled:opacity-30 transition-colors"
        >
          <Volume1 class="w-3.5 h-3.5" />
          <span>Бэк (30%)</span>
        </button>

        <button
          @click="applyVocalToSelection(1.0)"
          :disabled="playerStore.selStart === null"
          class="flex items-center space-x-1 px-2 py-1 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30 disabled:opacity-30 transition-colors"
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
        <span class="text-studio-muted">Зум:</span>
        <div class="inline-flex rounded-md shadow-sm border border-studio-border">
          <button
            v-for="z in [1, 2, 4]"
            :key="z"
            @click="setZoom(z)"
            :class="[
              'px-2 py-0.5 text-xs font-mono transition-colors',
              zoomFactor === z
                ? 'bg-sky-600 text-white font-semibold'
                : 'bg-studio-surface text-studio-muted hover:text-white'
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

    <!-- Canvas Scroll Container -->
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
  </div>
</template>
